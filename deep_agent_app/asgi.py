"""ASGI lifecycle wrapper for the process-scoped agent runtime."""

import logging

from deep_agent_app.runtime import agent_runtime

log = logging.getLogger(__name__)


class AgentLifespanApplication:
    """Handle lifespan locally and delegate HTTP/WebSocket traffic to Django."""

    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] != "lifespan":
            return await self.application(scope, receive, send)

        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                # Keep graph construction lazy: an integration outage must not prevent
                # the Django application and its non-chat pages from starting.
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    await agent_runtime.shutdown()
                except Exception as exc:
                    log.exception("deep-agent shutdown failed")
                    await send(
                        {"type": "lifespan.shutdown.failed", "message": str(exc)}
                    )
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return
