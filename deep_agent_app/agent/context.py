"""Validated, immutable choices attached to one LangGraph run."""

from dataclasses import dataclass

from deep_agent_app.utilities.model_registry import AUTO_MODEL
from deep_agent_app.utilities.validation import AgentChoice, ReasoningEffort


@dataclass(frozen=True)
class TurnContext:
    model: str = AUTO_MODEL
    agent: AgentChoice = "general"
    tools: tuple[str, ...] = ("web_search",)
    mentions: tuple[tuple[str, str], ...] = ()
    thinking: ReasoningEffort = "instant"
    plan: bool = False
    command_id: str | None = None
    command_prompt: str | None = None
