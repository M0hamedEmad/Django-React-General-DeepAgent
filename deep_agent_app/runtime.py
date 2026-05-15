"""Process-scoped lifecycle for loop-bound chat resources.

One ASGI worker owns one event loop, one compiled graph, one checkpointer, and
one set of active thread ids. Keeping that ownership here prevents request
code and agent composition code from growing their own competing singletons.
"""

import asyncio
import logging

from deep_agent_app.utilities.constants import (
    CHECKPOINT_DB,
    MAX_CONCURRENT_RUNS,
)

log = logging.getLogger(__name__)

WRONG_LOOP = (
    "deep_agent_app needs an ASGI server: python -m uvicorn config.asgi:application. "
    "The agent runtime contains async resources bound to one event loop."
)


class RuntimeBusyError(RuntimeError):
    """The shared graph cannot be replaced while a turn is active."""


class ThreadBusyError(RuntimeBusyError):
    """A second turn tried to mutate the same checkpoint thread."""


class RuntimeCapacityError(RuntimeBusyError):
    """The process already owns its configured maximum active turns."""


class AgentRuntime:
    """Own the shared graph and its async resources for one ASGI process."""

    def __init__(self):
        self._graph = None
        self._saver = None
        self._checkpoint_connection = None
        self._loop = None
        self._build_lock = None
        self._running_threads: set[str] = set()
        self._reloading = False

    def try_start_turn(self, thread_id: str) -> bool:
        """Reserve a thread for one turn in this ASGI process.

        Check-and-add has no await point, so requests sharing this event loop
        cannot interleave it. Multi-process deployments need a database-backed
        lease instead; Django's local-memory cache would still be process-local.
        """
        if self._reloading or thread_id in self._running_threads:
            return False
        self._running_threads.add(thread_id)
        return True

    def reserve_chat_turn(self, thread_id: str) -> None:
        """Reserve capacity for a model turn or raise a precise API error."""
        if self._reloading:
            raise RuntimeBusyError("the agent is reloading")
        if thread_id in self._running_threads:
            raise ThreadBusyError("a turn is already running on this thread")
        if len(self._running_threads) >= MAX_CONCURRENT_RUNS:
            raise RuntimeCapacityError("the assistant is at capacity; retry shortly")
        self._running_threads.add(thread_id)

    def finish_turn(self, thread_id: str) -> None:
        self._running_threads.discard(thread_id)

    def is_turn_running(self, thread_id: str) -> bool:
        return thread_id in self._running_threads

    def public_status(self) -> dict:
        """Return process-local runtime state without credentials or errors."""
        if self._reloading:
            agent_status = "reloading"
        elif self._graph is None:
            agent_status = "not_loaded"
        else:
            agent_status = "ready"

        # Keep /api/config/ cheap on a cold process. Importing the MCP adapters
        # belongs to graph construction, not to rendering the initial page.
        if self._graph is None and not self._reloading:
            integrations = []
        else:
            from deep_agent_app.agent.integrations import PersistentMcpTools

            integrations = PersistentMcpTools.registered_statuses()
        return {
            "agent": {
                "status": agent_status,
                "active_turns": len(self._running_threads),
                "max_concurrent_turns": MAX_CONCURRENT_RUNS,
            },
            "integrations": integrations,
        }

    def check_loop(self):
        """Bind on first async use and reject accidental cross-loop reuse."""
        current = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = current
            self._build_lock = asyncio.Lock()
        elif self._loop is not current:
            raise RuntimeError(WRONG_LOOP)
        return current

    async def get_saver(self):
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        self.check_loop()
        async with self._build_lock:
            if self._saver is None:
                connection = await aiosqlite.connect(CHECKPOINT_DB)
                try:
                    saver = AsyncSqliteSaver(connection)
                    await saver.setup()
                except BaseException:
                    await connection.close()
                    raise
                self._checkpoint_connection = connection
                self._saver = saver
        return self._saver

    async def get_agent(self):
        """Build once; a failed graph build is retried by the next request."""
        from deep_agent_app.agent.agent import build_agent

        self.check_loop()
        if self._graph is None:
            saver = await self.get_saver()
            async with self._build_lock:
                if self._graph is None:
                    self._graph = await build_agent(saver)
        return self._graph

    async def reload_agent(self):
        """Reconnect integrations and atomically replace the compiled graph."""
        from deep_agent_app.agent.agent import build_agent
        from deep_agent_app.agent.integrations import PersistentMcpTools

        self.check_loop()
        if self._reloading or self._running_threads:
            raise RuntimeBusyError(
                "wait for running chats to finish before reloading the agent"
            )

        # No await occurs between the check and assignment, so another request
        # on this ASGI loop cannot begin a turn in the gap.
        self._reloading = True
        try:
            saver = await self.get_saver()
            async with self._build_lock:
                if self._running_threads:
                    raise RuntimeBusyError(
                        "wait for running chats to finish before reloading the agent"
                    )
                await PersistentMcpTools.close_registered()
                graph = await build_agent(saver)
                self._graph = graph
                log.info("deep-agent runtime reloaded")
                return graph
        finally:
            self._reloading = False

    async def shutdown(self):
        """Close process-owned transports and make the object reusable in tests."""
        from deep_agent_app.agent.integrations import PersistentMcpTools
        from deep_agent_app.agent.tools.search import close_search

        if self._loop is not None:
            self.check_loop()

        connection = self._checkpoint_connection
        self._graph = None
        self._saver = None
        self._checkpoint_connection = None
        self._running_threads.clear()
        self._reloading = False
        try:
            await PersistentMcpTools.close_registered()
        finally:
            try:
                await close_search()
            finally:
                if connection is not None:
                    await connection.close()
                self._build_lock = None
                self._loop = None
        log.info("deep-agent runtime stopped")


agent_runtime = AgentRuntime()
