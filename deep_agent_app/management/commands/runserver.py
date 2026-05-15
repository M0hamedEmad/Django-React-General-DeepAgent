"""`manage.py runserver` starts uvicorn.

The chat streams SSE and keeps loop-bound clients (LLM, MCP, checkpointer)
alive across requests. Django's own runserver is WSGI: it buffers streaming
responses and gives every request a new event loop, so the second turn dies.
This override keeps the familiar command and makes it start the ASGI server
instead — with auto-reload, like before. deep_agent_app is first in
INSTALLED_APPS so this wins over staticfiles' override.
"""

import uvicorn
from django.conf import settings
from django.core.management.commands.runserver import Command as Runserver


class Command(Runserver):
    help = "Start the development server (uvicorn, ASGI). --noreload turns auto-reload off."

    def run(self, **options):
        # handle() has parsed addr:port into self.addr / self.port by now.
        self.check(display_num_errors=True)
        self.check_migrations()
        module, attr = settings.ASGI_APPLICATION.rsplit(".", 1)
        reload = options["use_reloader"]
        self.stdout.write(
            f"Starting uvicorn (ASGI) at http://{self.addr}:{self.port}/ (reload {'on' if reload else 'off'})"
        )
        uvicorn.run(
            f"{module}:{attr}",
            host=self.addr,
            port=int(self.port),
            reload=reload,
            log_level="info",
        )
