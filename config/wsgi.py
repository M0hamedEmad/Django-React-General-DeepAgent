"""WSGI is not supported by this project.

The chat streams SSE and keeps loop-bound clients (LLM, MCP, checkpointer)
alive across requests. Under WSGI every request runs in its own event loop,
so the second chat turn fails and nothing streams. Run the ASGI app:

    python manage.py runserver                       # development (starts uvicorn, auto-reload)
    DJANGO_SETTINGS_MODULE=config.settings.production \
        python -m uvicorn config.asgi:application
"""

from django.core.exceptions import ImproperlyConfigured

raise ImproperlyConfigured(
    "config.wsgi: this project must run under ASGI "
    "(python -m uvicorn config.asgi:application). "
    "WSGI cannot stream the chat and breaks its event-loop-bound clients."
)
