"""Validated, immutable choices attached to one LangGraph run."""

from dataclasses import dataclass

from pydantic import SkipValidation

from deep_agent_app.utilities.model_registry import AUTO_MODEL
from deep_agent_app.utilities.validation import AgentChoice, ReasoningEffort

from .budget import RunBudget


@dataclass(frozen=True)
class TurnContext:
    workspace_id: str = ""
    thread_id: str = ""
    model: str = AUTO_MODEL
    agent: AgentChoice = "general"
    tools: tuple[str, ...] = ("web_search",)
    mentions: tuple[tuple[str, str], ...] = ()
    thinking: ReasoningEffort = "instant"
    plan: bool = False
    command_id: str | None = None
    command_prompt: str | None = None
    run_budget: SkipValidation[RunBudget | None] = None
