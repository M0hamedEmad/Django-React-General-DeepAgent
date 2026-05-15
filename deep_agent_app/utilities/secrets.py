"""Load the private configuration owned by ``deep_agent_app``.

The real JSON file sits in ``deep_agent_app/config/`` and is ignored by Git. Production
may point ``DEEP_AGENT_SECRETS_FILE`` at a mounted secret without changing
application code. This module deliberately has no dependency on Django
settings, keeping private agent configuration independent of project settings.
"""

import json
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


DEFAULT_SECRETS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "secrets.json"
)
SECRETS_PATH = Path(
    os.environ.get("DEEP_AGENT_SECRETS_FILE", DEFAULT_SECRETS_PATH)
).expanduser()


def load_secrets(path=SECRETS_PATH):
    """Load the complete secret bundle, failing early with a safe message."""
    try:
        content = path.read_text()
    except FileNotFoundError as exc:
        raise ImproperlyConfigured(
            f"{path} is missing. Copy deep_agent_app/config/secrets.example.json to "
            "deep_agent_app/config/secrets.json and fill in the private values."
        ) from exc
    try:
        secrets = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ImproperlyConfigured(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(secrets, dict):
        raise ImproperlyConfigured(f"{path} must contain a JSON object")
    return secrets


SECRETS = load_secrets()


def secret_section(name):
    """Return one required object section without leaking values in errors."""
    section = SECRETS.get(name)
    if not isinstance(section, dict):
        raise ImproperlyConfigured(
            f"{SECRETS_PATH} requires an object section named '{name}'"
        )
    return section
