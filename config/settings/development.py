"""Local settings: SQLite, debug tooling, and uvicorn static-file serving."""

from .base import *  # noqa: F403


DEBUG = True
ALLOWED_HOSTS = env_list(  # noqa: F405
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1]",
)

# WAL and a busy timeout make local concurrent async requests less likely to
# contend. Production deployments should use PostgreSQL.
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":  # noqa: F405
    DATABASES["default"]["OPTIONS"] = {  # noqa: F405
        "timeout": 20,
        "init_command": "PRAGMA journal_mode=WAL;",
    }
