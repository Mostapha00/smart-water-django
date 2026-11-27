"""
Entraînement du Random Forest de risque de panne à 30 jours (hors requête web).

Jeu de données : pour chaque équipement, une « photo » par mois sur les 24 derniers mois.
- Variables (MODEL_FEATURES) calculées avec les seules interventions ANTÉRIEURES à la photo.
- Étiquette : 1 si une intervention corrective est planifiée dans les 30 jours qui suivent, sinon 0.
Les 30 derniers jours sont exclus : on ne sait pas encore s'ils se termineront par une panne.

Avec peu de pannes enregistrées (données de démonstration), le modèle est marqué « démo » :
il montre la méthode, pas une prédiction fiable.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from ..models import WaterPipe, WaterPump
from .artifacts import save_artifact
from .risk import ARTIFACT, MODEL_FEATURES, features, model_path

HORIZON = timedelta(days=30)
MIN_PER_CLASS = 3        # en dessous, impossible d'entraîner un classifieur
RELIABLE_POSITIVES = 30  # en dessous, le modèle est une démonstration


def snapshot_dates(now=None, months=24):
    now = now or timezone.now()
    end = now - HORIZON
    return [end - timedelta(days=30 * i) for i in range(months)][::-1]


def build_dataset(now=None, months=24):
    """Renvoie (X, y) : listes de variables et d'étiquettes 0/1."""
    X, y = [], []
    equipment = list(WaterPipe.objects.prefetch_related("maintenance_works")) + list(WaterPump.objects.prefetch_related("maintenance_works"))
    for eq in equipment:
        works = list(eq.maintenance_works.all())
        for as_of in snapshot_dates(now, months):
            if eq.installation_date and eq.installation_date > timezone.localtime(as_of).date():
                continue  # pas encore installé à cette date
            f = features(eq, as_of=as_of, works=works)
            X.append([f[k] for k in MODEL_FEATURES])
            y.append(int(any(w.maintenance_type == "corrective" and as_of <= w.scheduled_at < as_of + HORIZON for w in works)))
    return X, y


def train_failure_model(now=None) -> dict:
    try:
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as exc:
        raise ValidationError("Installez requirements-ml.txt pour entraîner le Random Forest.") from exc

    X, y = build_dataset(now)
    positives, negatives = sum(y), len(y) - sum(y)
    if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
        raise ValidationError(
            f"Pas assez d'historique : {positives} panne(s) et {negatives} période(s) sans panne "
            f"(au moins {MIN_PER_CLASS} de chaque). Enregistrez des interventions correctives."
        )
    model = RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_leaf=3, class_weight="balanced", random_state=42, n_jobs=1,
    ).fit(X, y)
    trained_at = timezone.now()
    metrics = {
        "samples": len(y), "positives": positives, "negatives": negatives,
        "demo": positives < RELIABLE_POSITIVES,
        "feature_importance": {k: round(float(v), 3) for k, v in zip(MODEL_FEATURES, model.feature_importances_)},
    }
    version = f"random-forest-{trained_at:%Y%m%d-%H%M}"
    path = save_artifact(ARTIFACT, {"model": model, "features": MODEL_FEATURES, "version": version,
                                    "trained_at": trained_at, "metrics": metrics}, model_path())
    return {"version": version, "path": str(path), **metrics}
