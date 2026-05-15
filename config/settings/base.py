"""Settings shared by development and production deployments."""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


def env_list(name: str, default: str = "") -> list[str]:
    """Read a comma-separated environment variable without empty entries."""
    return [
        value.strip()
        for value in os.environ.get(name, default).split(",")
        if value.strip()
    ]


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-development-only-change-me",
)
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/chat/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

INSTALLED_APPS = [
    # First so its runserver command can replace Django's WSGI development
    # server with uvicorn. The agent runtime is ASGI-only.
    "deep_agent_app.apps.DeepAgentAppConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
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

ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.environ.get(
            "DJANGO_DB_ENGINE",
            "django.db.backends.sqlite3",
        ),
        "NAME": os.environ.get("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.environ.get("DJANGO_DB_USER", ""),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", ""),
        "PORT": os.environ.get("DJANGO_DB_PORT", ""),
        "CONN_MAX_AGE": int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", "0")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {"NAME": ("django.contrib.auth.password_validation.MinimumLengthValidator")},
    {"NAME": ("django.contrib.auth.password_validation.CommonPasswordValidator")},
    {"NAME": ("django.contrib.auth.password_validation.NumericPasswordValidator")},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} [{threadName}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "deep_agent_app": {
            "handlers": ["console"],
            "level": os.environ.get("DEEP_AGENT_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
