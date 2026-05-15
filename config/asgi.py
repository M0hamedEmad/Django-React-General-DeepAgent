"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings.development",
)

application = get_asgi_application()

if settings.DEBUG:
    # uvicorn serves /static/ (the built chat app) in development; nginx does in production.
    application = ASGIStaticFilesHandler(application)

# Uvicorn now gets a real lifespan implementation. The wrapper leaves startup
# cheap and closes the persistent MCP/checkpointer resources on shutdown.
from deep_agent_app.asgi import AgentLifespanApplication  # noqa: E402

application = AgentLifespanApplication(application)
