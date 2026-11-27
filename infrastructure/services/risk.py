"""
Risque de panne à 30 jours (predict_failure_30d).

Deux modes :
1. Random Forest entraîné HORS requête web (python manage.py train_models), voir risk_training.py.
   Il apprend sur l'historique des interventions : « une intervention corrective a-t-elle eu lieu
   dans les 30 jours ? ». Fichier : AQUAMIND_FAILURE_MODEL_PATH ou AQUAMIND_ML_DIR/failure_risk.joblib.
2. Sinon, une règle de base transparente (« baseline-0.1 »), utile pour la démo et pour comparer.
   Ce n'est PAS un modèle validé.

Le statut actuel (« en panne », « à surveiller ») n'est pas une variable du modèle : l'application ne
garde pas l'historique des statuts, le modèle ne pourrait donc pas apprendre ce lien sans tricher.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .artifacts import load_artifact

BASELINE_VERSION = "baseline-0.1"
ARTIFACT = "failure_risk"
FEATURES = ["age_years", "interventions_2y", "corrective_2y", "days_since_last", "is_pump", "status_watch", "status_broken"]
# Variables connues à n'importe quelle date passée : utilisées par le Random Forest.
MODEL_FEATURES = ["age_years", "interventions_2y", "corrective_2y", "days_since_last", "is_pump"]

logger = logging.getLogger(__name__)


def features(equipment, as_of: datetime | None = None, works=None) -> dict:
    """Variables de l'équipement à la date as_of (maintenant par défaut), sans regarder le futur."""
    as_of = as_of or timezone.now()
    works = list(equipment.maintenance_works.all()) if works is None else works
    past = [w for w in works if w.scheduled_at < as_of]
    recent = [w for w in past if w.scheduled_at >= as_of - timedelta(days=730)]
    last = max((w.completed_at if w.completed_at and w.completed_at <= as_of else w.scheduled_at for w in past), default=None)
    age = (timezone.localtime(as_of).date() - equipment.installation_date).days / 365.25 if equipment.installation_date else 0.0
    return {
        "age_years": round(max(age, 0.0), 2),
        "interventions_2y": len(recent),
        "corrective_2y": sum(1 for w in recent if w.maintenance_type == "corrective"),
        "days_since_last": (as_of - last).days if last else 3650,
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


def model_path():
    return getattr(settings, "AQUAMIND_FAILURE_MODEL_PATH", "") or None


def load_model() -> dict | None:
    return load_artifact(ARTIFACT, model_path())


def predict(equipment) -> tuple[float, str]:
    """Renvoie (risque entre 0 et 1, version du modèle utilisé)."""
    f = features(equipment)
    artifact = load_model()
    if artifact is not None:
        try:
            model = artifact["model"]
            proba = model.predict_proba([[f[k] for k in artifact["features"]]])[0]
            positive = list(model.classes_).index(1)
            return float(proba[positive]), artifact["version"]
        except Exception:
            logger.warning("Le modèle de risque a échoué, règle de base utilisée.", exc_info=True)
    return baseline_risk(f), BASELINE_VERSION
