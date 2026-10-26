"""
Risque de panne à 30 jours (predict_failure_30d).

Deux modes :
1. Un modèle entraîné HORS requête web (Random Forest / XGBoost), sauvegardé avec joblib,
   dont le chemin est donné par AQUAMIND_FAILURE_MODEL_PATH. Il doit exposer predict_proba()
   et recevoir les variables dans l'ordre de FEATURES.
2. Sinon, une règle de base transparente (« baseline »), utile pour la démo et pour
   comparer le futur modèle. Ce n'est PAS un modèle validé.
"""
from __future__ import annotations

import math
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone

BASELINE_VERSION = "baseline-0.1"
FEATURES = ["age_years", "interventions_2y", "corrective_2y", "days_since_last", "is_pump", "status_watch", "status_broken"]


def features(equipment) -> dict:
    now = timezone.now()
    works = list(equipment.maintenance_works.all())
    recent = [w for w in works if w.scheduled_at >= now - timedelta(days=730)]
    last = max((w.completed_at or w.scheduled_at for w in works), default=None)
    return {
        "age_years": round(equipment.age_years or 0.0, 2),
        "interventions_2y": len(recent),
        "corrective_2y": sum(1 for w in recent if w.maintenance_type == "corrective"),
        "days_since_last": (now - last).days if last else 3650,
        "is_pump": 1 if equipment.kind == "pump" else 0,
        "status_watch": 1 if equipment.status == "a_surveiller" else 0,
        "status_broken": 1 if equipment.status == "en_panne" else 0,
    }


def baseline_risk(f: dict) -> float:
    """Règle de base : l'âge, les pannes récentes et le statut augmentent le risque."""
    score = (
        -3.2
        + 0.07 * f["age_years"]
        + 0.55 * f["corrective_2y"]
        + 0.10 * (f["interventions_2y"] - f["corrective_2y"])
        + 0.25 * f["is_pump"]
        + 0.9 * f["status_watch"]
        + 2.2 * f["status_broken"]
    )
    return 1 / (1 + math.exp(-score))


@lru_cache(maxsize=1)
def _load_model(path: str):
    try:
        import joblib  # installé avec scikit-learn
    except ImportError:
        return None
    p = Path(path)
    return joblib.load(p) if p.exists() else None


def predict(equipment) -> tuple[float, str]:
    """Renvoie (risque entre 0 et 1, version du modèle utilisé)."""
    f = features(equipment)
    path = getattr(settings, "AQUAMIND_FAILURE_MODEL_PATH", "")
    model = _load_model(path) if path else None
    if model is not None:
        proba = model.predict_proba([[f[k] for k in FEATURES]])[0][1]
        return float(proba), f"model:{Path(path).stem}"
    return baseline_risk(f), BASELINE_VERSION
