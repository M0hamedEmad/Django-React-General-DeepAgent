"""Reusable persistent MCP client and tool lifecycle."""

import asyncio
import logging
from builtins import BaseExceptionGroup
from collections.abc import Mapping
from typing import ClassVar
from weakref import WeakSet

import anyio
import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.shared.exceptions import McpError

log = logging.getLogger(__name__)

SESSION_CLOSE_TIMEOUT = 10


class PersistentMcpTools:
    """Own one MCP server connection and its loaded LangChain tools.

    An instance belongs to exactly one ASGI process and event loop. Tool calls
    are not serialized: the lock protects only initialization, reconnection,
    and shutdown, allowing concurrent users to share the MCP session.
    """

    _instances: ClassVar[WeakSet] = WeakSet()

    def __init__(
        self,
        *,
        server_name: str,
        transport: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
        sse_read_timeout: float,
    ):
        self._server_name = server_name
        self._client = MultiServerMCPClient(
            {
                server_name: {
                    "transport": transport,
                    "url": url,
                    "headers": dict(headers),
                    "timeout": timeout,
                    "sse_read_timeout": sse_read_timeout,
                }
            }
        )
        self._session = None
        self._keeper: asyncio.Task | None = None
        self._closing: asyncio.Event | None = None
        self._tools = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._status = "not_loaded"
        self._instances.add(self)

    @classmethod
    def registered(cls):
        """Return every live instance of this MCP class or its subclasses."""
        instances = [
            integration
            for integration in PersistentMcpTools._instances
            if isinstance(integration, cls)
        ]
        return tuple(sorted(instances, key=lambda item: item._server_name))

    @classmethod
    async def load_registered_tools(cls):
        """Load every registered MCP concurrently and flatten their tools."""
        integrations = cls.registered()
        results = await asyncio.gather(
            *(item.get_tools(required=False) for item in integrations)
        )
        return [tool for tools in results for tool in tools]

    @classmethod
    async def close_registered(cls) -> None:
        """Close every registered MCP, allowing all closes to finish."""
        results = await asyncio.gather(
            *(item.close() for item in cls.registered()),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]

    @classmethod
    def registered_statuses(cls) -> list[dict[str, str]]:
        return [item.public_status() for item in cls.registered()]

    @staticmethod
    def _session_forgotten(exc: BaseException) -> bool:
        return isinstance(exc, McpError) and exc.error.message == "Session terminated"

    @classmethod
    def _session_lost(cls, exc: BaseException) -> bool:
        return cls._session_forgotten(exc) or isinstance(
            exc,
            (
                anyio.ClosedResourceError,
                anyio.BrokenResourceError,
                httpx.TransportError,
            ),
        )

    @classmethod
    def _request_never_reached_server(cls, exc: BaseException) -> bool:
        return cls._session_forgotten(exc) or isinstance(
            exc, (httpx.ConnectError, httpx.ConnectTimeout)
        )

    @staticmethod
    def _root_cause(exc: BaseException) -> BaseException:
        """Return a useful leaf from AnyIO/asyncio exception groups."""
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        return exc

    def _lifecycle_lock(self) -> asyncio.Lock:
        """Bind resources lazily to the first ASGI event loop that uses them."""
        current = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = current
            self._lock = asyncio.Lock()
        elif self._loop is not current:
            raise RuntimeError(
                f"MCP server {self._server_name!r} is bound to a different "
                "event loop; run the Django application with ASGI"
            )
        return self._lock

    def public_status(self) -> dict[str, str]:
        """Return a safe status snapshot suitable for the browser."""
        messages = {
            "not_loaded": "Connected company tools have not been loaded yet.",
            "loading": "Connecting to the company system…",
            "ready": "Connected company tools are available.",
            "unavailable": (
                "Connected company tools are unavailable. General assistant "
                "features still work."
            ),
        }
        return {
            "id": self._server_name,
            "status": self._status,
            "message": messages[self._status],
        }

    async def _keep_session(
        self,
        ready: asyncio.Future,
        closing: asyncio.Event,
    ) -> None:
        """Keep the SDK context manager alive until shutdown or reconnect."""
        try:
            async with self._client.session(self._server_name) as session:
                ready.set_result(session)
                await closing.wait()
        except BaseException as exc:
            if not ready.done():
                if isinstance(exc, asyncio.CancelledError):
                    exc = RuntimeError("MCP session was cancelled while opening")
                ready.set_exception(exc)
            elif not closing.is_set():
                self._status = "unavailable"
                log.warning(
                    "MCP server %s session ended (%s: %s)",
                    self._server_name,
                    type(exc).__name__,
                    exc,
                )
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def _close_session_locked(self) -> None:
        keeper = self._keeper
        closing = self._closing
        self._keeper = None
        self._closing = None
        self._session = None

        if keeper is None:
            return
        if closing is not None:
            closing.set()
        try:
            await asyncio.wait_for(keeper, SESSION_CLOSE_TIMEOUT)
        except asyncio.CancelledError:
            if not keeper.cancelled():
                raise
        except TimeoutError:
            log.warning("timed out closing MCP server %s session", self._server_name)
        except Exception:
            log.debug(
                "closing MCP server %s session failed",
                self._server_name,
                exc_info=True,
            )

    async def _open_session_locked(self):
        await self._close_session_locked()
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        closing = asyncio.Event()
        keeper = loop.create_task(
            self._keep_session(ready, closing),
            name=f"{self._server_name}-mcp-session",
        )
        self._closing = closing
        self._keeper = keeper
        try:
            session = await ready
        except BaseException:
            self._closing = None
            self._keeper = None
            if not keeper.done():
                keeper.cancel()
            try:
                await keeper
            except BaseException:
                pass
            raise
        self._session = session
        return session

    async def _get_session(self):
        lock = self._lifecycle_lock()
        if self._session is not None:
            return self._session
        async with lock:
            if self._session is None:
                await self._open_session_locked()
            return self._session

    async def _reopen_after(self, dead_session):
        lock = self._lifecycle_lock()
        async with lock:
            if self._session is dead_session or self._session is None:
                await self._open_session_locked()
            return self._session

    async def get_tools(self, *, required: bool = True):
        """Load tool schemas once; optionally keep the application available.

        ``required=False`` is intended for optional integrations during graph
        construction. It never hides cancellation, and a failed initialization
        remains retryable until the graph has been built successfully.
        """
        try:
            return await self._load_tools()
        except Exception as exc:
            self._status = "unavailable"
            if required:
                raise
            cause = self._root_cause(exc)
            log.warning(
                "MCP server %s is unavailable; starting without its tools (%s: %s)",
                self._server_name,
                type(cause).__name__,
                cause,
            )
            return []

    async def _load_tools(self):
        """Load and cache schemas, reconnecting once after a lost session."""
        lock = self._lifecycle_lock()
        if self._tools is not None:
            return self._tools

        async with lock:
            if self._tools is not None:
                return self._tools
            self._status = "loading"
            if self._session is None:
                await self._open_session_locked()

            try:
                tools = await load_mcp_tools(self)
            except Exception as exc:
                # Listing tools is read-only, so reconnecting and retrying once
                # cannot duplicate a mutation.
                if not self._session_lost(exc):
                    raise
                log.warning(
                    "MCP server %s lost while loading tools; reconnecting",
                    self._server_name,
                )
                await self._open_session_locked()
                tools = await load_mcp_tools(self)

            self._tools = tools
            self._status = "ready"
            return self._tools

    async def list_tools(self, cursor=None):
        self._lifecycle_lock()
        session = await self._get_session()
        return await session.list_tools(cursor=cursor)

    async def call_tool(self, name, arguments, **kwargs):
        self._lifecycle_lock()
        session = await self._get_session()
        try:
            return await session.call_tool(name, arguments, **kwargs)
        except Exception as exc:
            if not self._session_lost(exc):
                raise
            self._status = "unavailable"
            log.warning(
                "MCP server %s session lost (%s: %s); reconnecting",
                self._server_name,
                type(exc).__name__,
                exc,
            )
            session = await self._reopen_after(session)
            self._status = "ready"
            if not self._request_never_reached_server(exc):
                raise
            return await session.call_tool(name, arguments, **kwargs)

    async def close(self) -> None:
        """Close all resources and allow reuse on a fresh loop in tests."""
        lock = self._lifecycle_lock()
        try:
            async with lock:
                self._tools = None
                await self._close_session_locked()
        finally:
            self._lock = None
            self._loop = None
            self._status = "not_loaded"
