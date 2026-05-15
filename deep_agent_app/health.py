"""Minimal unauthenticated health probes for a reverse proxy or orchestrator."""

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from deep_agent_app.utilities.model_registry import (
    DEFAULT_PROVIDER,
    PROVIDERS,
)


@require_GET
def live(request):
    """The Django process can receive HTTP requests."""
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request):
    """The database and required model configuration are available."""
    try:
        connection.ensure_connection()
        model_ready = DEFAULT_PROVIDER in PROVIDERS
    except Exception:
        model_ready = False
    status = 200 if model_ready else 503
    return JsonResponse(
        {"status": "ready" if model_ready else "unavailable"},
        status=status,
    )
