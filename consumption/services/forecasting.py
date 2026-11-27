"""
Prévision de consommation par LightGBM (un modèle commun à tous les compteurs).

Les relevés sont mensuels et les compteurs très différents (une école consomme 100 fois moins qu'un
campus). Le modèle n'apprend donc pas des m³ mais un MULTIPLICATEUR par rapport au niveau habituel du
compteur (médiane de son historique, peu sensible aux vacances), par exemple « en juillet, × 0,3 » :
- month          : mois de la période (saisonnalité : vacances, été) ;
- days           : durée de la période ;
- category       : catégorie d'abonné (ménage, commercial, industriel, service public) ;
- last_vs_level  : dernière période / niveau habituel (tendance).
Prévision = multiplicateur prédit × niveau habituel × horizon (jours).

Il faut au moins un an d'historique pour que chaque mois ait été vu : avant, le modèle fait rarement
mieux que la règle et reste donc désactivé par la vérification ci-dessous.

Entraînement hors requête web (python manage.py train_models). L'erreur est mesurée sur la DERNIÈRE
période de chaque compteur (jamais vue à l'entraînement) et comparée à la règle « moyenne journalière ».
Le modèle n'est ACTIVÉ que s'il fait mieux que cette règle ; sinon la règle « average-daily-1 » reste utilisée.
"""
from __future__ import annotations

import math
from datetime import timedelta
from statistics import median

from django.core.exceptions import ValidationError
from django.utils import timezone

from infrastructure.services.artifacts import artifact_path, load_artifact, save_artifact

ARTIFACT = "consumption_forecast"
FEATURES = ["month", "days", "category", "last_vs_level"]
MIN_SAMPLES = 30
EPS = 1e-6


def _categories():
    from consumption.models import WaterMeter

    return {value: i for i, value in enumerate(WaterMeter.CustomerCategory.values)}


def _rates(meter):
    readings = sorted(meter.readings.all(), key=lambda r: (r.recorded_at, r.pk))
    out = []
    for prev, cur in zip(readings, readings[1:]):
        days = (cur.recorded_at - prev.recorded_at).total_seconds() / 86400
        volume = float(cur.index_m3 - prev.index_m3)
        if days > 0 and volume >= 0:
            out.append((cur.recorded_at, days, volume / days))
    return out


def _row(when, days, category, history):
    """(variables, niveau habituel) pour une période qui se termine à `when`, à partir des taux passés."""
    level = median(history)
    return [timezone.localtime(when).month, days, category, history[-1] / (level + EPS)], level


def build_samples(meters):
    """Échantillons d'entraînement et de test ; test = dernière période de chaque compteur.

    Renvoie un dict : X/y (multiplicateurs) pour l'entraînement, et pour le test X, niveaux, taux réels
    et prévision de la règle « moyenne journalière » (moyenne de toutes les périodes passées).
    """
    cats = _categories()
    s = {"X_train": [], "y_train": [], "X_test": [], "level_test": [], "rate_test": [], "rule_test": []}
    for meter in meters:
        rates = _rates(meter)
        for i in range(1, len(rates)):
            when, days, rate = rates[i]
            history = [r for _, _, r in rates[:i]]
            row, level = _row(when, days, cats.get(meter.customer_category, -1), history)
            if i == len(rates) - 1:
                s["X_test"].append(row); s["level_test"].append(level); s["rate_test"].append(rate)
                s["rule_test"].append(sum(history) / len(history))
            else:
                s["X_train"].append(row); s["y_train"].append(rate / (level + EPS))
    return s


def _mae(pred, true):
    return sum(abs(p - t) for p, t in zip(pred, true)) / len(true)


def train_consumption_model() -> dict:
    try:
        from lightgbm import LGBMRegressor
    except ImportError as exc:
        raise ValidationError("Installez requirements-ml.txt pour entraîner LightGBM.") from exc
    from consumption.models import WaterMeter

    s = build_samples(list(WaterMeter.objects.prefetch_related("readings")))
    if len(s["X_train"]) < MIN_SAMPLES or not s["X_test"]:
        raise ValidationError(f"Pas assez de relevés : {len(s['X_train'])} périodes d'entraînement (au moins {MIN_SAMPLES}).")
    params = dict(n_estimators=150, learning_rate=0.05, num_leaves=7, min_child_samples=5,
                  random_state=42, n_jobs=1, verbosity=-1)
    holdout = LGBMRegressor(**params).fit(s["X_train"], s["y_train"])
    predicted = [max(float(m), 0.0) * level for m, level in zip(holdout.predict(s["X_test"]), s["level_test"])]
    model_mae = round(_mae(predicted, s["rate_test"]), 4)
    rule_mae = round(_mae(s["rule_test"], s["rate_test"]), 4)
    metrics = {"train_periods": len(s["X_train"]), "test_periods": len(s["X_test"]),
               "mae_m3_per_day": model_mae, "baseline_mae_m3_per_day": rule_mae}
    if model_mae >= rule_mae:
        artifact_path(ARTIFACT).unlink(missing_ok=True)  # un ancien modèle ne doit pas rester actif
        raise ValidationError(
            f"LightGBM ne fait pas mieux que la moyenne simple sur les périodes de test "
            f"({model_mae} contre {rule_mae} m³/jour d'erreur) : modèle non activé."
        )
    # Modèle final : toutes les périodes, y compris celles de test.
    X_all = s["X_train"] + s["X_test"]
    y_all = s["y_train"] + [rate / (level + EPS) for rate, level in zip(s["rate_test"], s["level_test"])]
    model = LGBMRegressor(**params).fit(X_all, y_all)
    trained_at = timezone.now()
    version = f"lightgbm-{trained_at:%Y%m%d-%H%M}"
    path = save_artifact(ARTIFACT, {"model": model, "features": FEATURES, "version": version,
                                    "trained_at": trained_at, "metrics": metrics, "categories": _categories()})
    return {"version": version, "path": str(path), **metrics}


def predict(meter, horizon: int):
    """Renvoie (volume prévu en m³, version) avec LightGBM, ou None si le modèle n'est pas utilisable."""
    artifact = load_artifact(ARTIFACT)
    if artifact is None or artifact.get("features") != FEATURES:
        return None
    rates = _rates(meter)
    if not rates:
        return None
    history = [r for _, _, r in rates]
    row, level = _row(rates[-1][0] + timedelta(days=horizon / 2), horizon,
                      artifact["categories"].get(meter.customer_category, -1), history)
    try:
        multiplier = float(artifact["model"].predict([row])[0])
    except Exception:
        return None
    if not math.isfinite(multiplier):
        return None
    return max(multiplier, 0.0) * level * horizon, artifact["version"]
