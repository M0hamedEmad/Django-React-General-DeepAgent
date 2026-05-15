"""Concrete subagent definitions registered by the main Deep Agent."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from deep_agent_app.utilities.constants import CONNECTED_SYSTEM_ENABLED

from .llm.routing import model_selector
from .middleware.ask_user_recovery import recover_ask_user_markup
from .prompts import SUBAGENT_PROMPT
from .skills import SkillSource, connected_skill_sources
from .tools.ask_user import ask_user

SubagentTool = BaseTool | Callable[..., Any] | dict[str, Any]
CONNECTED_SUBAGENT_NAME = "connected_system"
CONNECTED_SUBAGENT_MENTION_ID = "connected"
CONNECTED_SUBAGENT_DESCRIPTION = (
    "A focused worker for delegated company tasks that need connected "
    "systems, tools, skills, or multi-step analysis."
)
SUBAGENT_MENTION_ALIASES = {CONNECTED_SUBAGENT_NAME: CONNECTED_SUBAGENT_MENTION_ID}


def build_subagent(
    *,
    name: str,
    description: str,
    system_prompt: str,
    model: str | BaseChatModel,
    tools: Sequence[SubagentTool],
    middleware: Sequence[AgentMiddleware],
    skills: Sequence[SkillSource],
):
    """Build one fully specified raw Deep Agents definition."""
    # Deep Agents supports labelled SkillSource tuples even though its current
    # SubAgent TypedDict still narrows this field to list[str].
    return {
        "name": name,
        "description": description,
        "system_prompt": system_prompt,
        "model": model,
        "tools": list(tools),
        "middleware": list(middleware),
        "skills": list(skills),
    }


def get_subagents(
    *,
    model: str | BaseChatModel,
    mcp_tools: Sequence[SubagentTool],
):
    if not CONNECTED_SYSTEM_ENABLED:
        return []

    company_subagent = build_subagent(
        name=CONNECTED_SUBAGENT_NAME,
        description=CONNECTED_SUBAGENT_DESCRIPTION,
        system_prompt=SUBAGENT_PROMPT,
        model=model,
        tools=[*mcp_tools, ask_user],
        middleware=[recover_ask_user_markup, model_selector],
        skills=connected_skill_sources(),
    )
    return [company_subagent]


def composer_subagents():
    """Derive composer metadata from the real registered definitions.

    The placeholder model is metadata only; no client, graph, or network
    resource is built while loading the composer configuration.
    """
    definitions = get_subagents(model="auto", mcp_tools=())
    return [
        {
            "id": SUBAGENT_MENTION_ALIASES.get(item["name"], item["name"]),
            "target": item["name"],
            "label": item["name"].replace("_", " ").title(),
            "description": item["description"],
        }
        for item in definitions
    ]
