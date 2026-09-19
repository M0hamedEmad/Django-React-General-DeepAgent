"""Shared, per-turn limits for the main agent and delegated workers."""

import asyncio
from dataclasses import dataclass, field
from contextvars import ContextVar
from threading import Lock

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

PRESENTATION_VALIDATION_LIMIT = 3


class RunBudgetExceeded(RuntimeError):
    """A turn reached an explicit execution limit."""


ACTIVE_RUN_BUDGET: ContextVar["RunBudget | None"] = ContextVar(
    "deep_agent_active_run_budget", default=None
)


@dataclass(slots=True)
class RunBudget:
    max_model_calls: int
    max_tool_calls: int
    filter_internal_model_text: bool = False
    model_calls: int = 0
    tool_calls: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)
    _internal_message_providers: dict[str, str] = field(
        default_factory=dict, repr=False
    )
    _presentation_validation_failures: dict[str, int] = field(
        default_factory=dict, repr=False
    )
    _active_summaries: int = field(default=0, repr=False)
    _summaries_idle: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def __post_init__(self) -> None:
        self._summaries_idle.set()

    def consume_model_call(self) -> None:
        with self._lock:
            if self.model_calls >= self.max_model_calls:
                raise RunBudgetExceeded("model-call limit reached")
            self.model_calls += 1

    def consume_tool_call(self) -> None:
        with self._lock:
            if self.tool_calls >= self.max_tool_calls:
                raise RunBudgetExceeded("tool-call limit reached")
            self.tool_calls += 1

    def note_presentation_validation_failure(self, tool_name: str) -> None:
        with self._lock:
            failures = self._presentation_validation_failures.get(tool_name, 0) + 1
            self._presentation_validation_failures[tool_name] = failures
            if failures >= PRESENTATION_VALIDATION_LIMIT:
                raise RunBudgetExceeded(f"{tool_name} validation retry limit reached")

    def start_summary(self) -> None:
        with self._lock:
            self._active_summaries += 1
            self._summaries_idle.clear()

    def finish_summary(self) -> None:
        with self._lock:
            self._active_summaries -= 1
            if self._active_summaries == 0:
                self._summaries_idle.set()

    def mark_internal_message(self, message_id: str, provider_id: str) -> None:
        with self._lock:
            self._internal_message_providers[message_id] = provider_id

    def is_internal_message(self, message_id: str | None) -> bool:
        with self._lock:
            return (
                message_id is not None
                and message_id in self._internal_message_providers
            )

    def internal_message_provider(self, message_id: str | None) -> str | None:
        with self._lock:
            return self._internal_message_providers.get(message_id)

    async def wait_for_summaries(self) -> None:
        await self._summaries_idle.wait()


class ToolCallBudgetMiddleware(AgentMiddleware):
    """Count attempts, including failures and delegated tool calls."""

    @staticmethod
    def _consume(request) -> RunBudget | None:
        context = request.runtime.context if request.runtime else None
        if context is not None and context.run_budget is not None:
            context.run_budget.consume_tool_call()
            return context.run_budget
        return None

    @staticmethod
    def _check_presentation_validation(request, result, budget) -> None:
        if budget is None or not isinstance(result, ToolMessage):
            return
        name = request.tool_call["name"]
        if name not in {"present_report", "present_ui"}:
            return
        if isinstance(result.content, str) and result.content.startswith(
            f"Invalid {name} "
        ):
            budget.note_presentation_validation_failure(name)

    def wrap_tool_call(self, request, handler):
        budget = self._consume(request)
        result = handler(request)
        self._check_presentation_validation(request, result, budget)
        return result

    async def awrap_tool_call(self, request, handler):
        budget = self._consume(request)
        result = await handler(request)
        self._check_presentation_validation(request, result, budget)
        return result
