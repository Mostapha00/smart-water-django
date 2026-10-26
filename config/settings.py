"""
Paramètres Django du projet AquaMind.

Configuration par variables d'environnement (voir .env.example).
Sans POSTGRES_DB, le projet utilise SQLite : pratique pour développer et pour la CI.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans dépendance externe."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Apps AquaMind
    "accounts",          # profils partagés (User abstrait, NetworkTechnician, AuditManager)
    "infrastructure",    # Student 1 : sites, zones, équipements, maintenance
    "consumption",       # Student 2 : compteurs, relevés, tarifs, factures
    "quality_leaks",     # Student 3 : qualité de l'eau, règles d'alerte, fuites
    "sustainability",    # Student 4 : objectifs, projets d'économie, audits
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", "aquamind"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Tunis"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"   # stockage privé : modèles IA, imports, PDF

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "infrastructure:site_list"
LOGOUT_REDIRECT_URL = "login"

# ---------------------------------------------------------------------------
# Paramètres métier AquaMind
# ---------------------------------------------------------------------------

# Modèle IA de risque de panne entraîné hors requête web (joblib). Vide = règle de base.
AQUAMIND_FAILURE_MODEL_PATH = os.environ.get("AQUAMIND_FAILURE_MODEL_PATH", "")

# Coûts unitaires pour estimate_replacement_cost().
# VALEURS D'EXEMPLE : à remplacer par des prix validés (devis, bordereau de prix).
AQUAMIND_REPLACEMENT_COSTS = {
    "pipe_tnd_per_m_per_100mm": {
        "PEHD": 60,
        "PVC": 45,
        "Acier galvanisé": 110,
        "Fonte": 140,
        "default": 80,
    },
    "pipe_install_tnd_per_m": 25,
    "pump_tnd_per_kw": 900,
    "pump_fixed_tnd": 600,
}
