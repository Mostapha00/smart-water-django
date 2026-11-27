"""
Stockage des modèles d'IA entraînés (fichiers joblib dans settings.AQUAMIND_ML_DIR).

Chaque modèle est un dictionnaire : {"schema", "model", "features", "version", "trained_at", "metrics", ...}.
- save_artifact() écrit dans un fichier temporaire puis le renomme : jamais de fichier à moitié écrit.
- load_artifact() garde le modèle en mémoire et le recharge si le fichier change (réentraînement),
  sans redémarrer le serveur. Un fichier absent, illisible ou d'un autre schéma renvoie None :
  l'appelant utilise alors sa règle simple.

Seuls des fichiers créés par les commandes d'entraînement sont chargés, jamais des fichiers envoyés
par un utilisateur (joblib peut exécuter du code à l'ouverture).
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

SCHEMA = 1
logger = logging.getLogger(__name__)
_cache: dict[str, tuple[float, dict]] = {}


def ml_dir() -> Path:
    return Path(getattr(settings, "AQUAMIND_ML_DIR", Path(settings.MEDIA_ROOT) / "ml"))


def artifact_path(name: str) -> Path:
    return ml_dir() / f"{name}.joblib"


def save_artifact(name: str, artifact: dict, path: Path | None = None) -> Path:
    import joblib

    path = Path(path) if path else artifact_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    joblib.dump({"schema": SCHEMA, **artifact}, tmp)
    tmp.replace(path)
    _cache.pop(str(path), None)
    return path


def load_artifact(name: str, path: Path | str | None = None) -> dict | None:
    path = Path(path) if path else artifact_path(name)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        import joblib

        artifact = joblib.load(path)
    except Exception:  # paquet manquant, fichier corrompu ou d'une autre version de scikit-learn
        logger.warning("Modèle IA illisible, règle simple utilisée : %s", path, exc_info=True)
        return None
    if not isinstance(artifact, dict) or artifact.get("schema") != SCHEMA or "model" not in artifact:
        logger.warning("Modèle IA d'un format inattendu, ignoré : %s", path)
        return None
    _cache[str(path)] = (mtime, artifact)
    return artifact


def is_ml_version(version: str | None) -> bool:
    """Vrai si un résultat vient d'un modèle d'IA entraîné ou d'un solveur, faux s'il vient d'une règle."""
    # Versions écrites par ce projet : random-forest-…, lightgbm-…, isolation-forest-…, PuLP.
    return bool(version) and version.split("-")[0].lower() in {"random", "lightgbm", "isolation", "pulp"}
