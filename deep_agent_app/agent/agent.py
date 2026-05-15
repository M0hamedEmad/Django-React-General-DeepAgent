"""Composition root for the shared main Deep Agent graph."""

import logging
import time

from deepagents import HarnessProfile, create_deep_agent, register_harness_profile
from deepagents.middleware.filesystem import FilesystemPermission

from .context import TurnContext
from .integrations import PersistentMcpTools
from .llm.clients import build_llm
from .llm.routing import model_selector
from .middleware.ask_user_recovery import recover_ask_user_markup
from .middleware.planning import PlanModeMiddleware
from .middleware.selection import TurnSelectionMiddleware
from .prompts import GENERAL_AGENT_PROMPT
from .skills import build_agent_backend, skill_catalog
from .subagent import CONNECTED_SUBAGENT_NAME, get_subagents
from .tools.ask_user import ask_user
from .tools.present_ui import present_ui
from .tools.reports import present_report
from .tools.search import internet_search, fetch_webpage_content

log = logging.getLogger(__name__)

# Deep Agents otherwise rewrites old messages during compaction, invalidating
# provider prompt caches. This application enables summarization later as an
# explicit feature rather than paying that cost implicitly.
register_harness_profile(
    "openai",
    HarnessProfile(excluded_middleware=frozenset({"SummarizationMiddleware"})),
)


async def build_agent(checkpointer):
    """Initialize integrations once and compile the process-shared graph."""
    started = time.perf_counter()
    # Fail before opening network integrations if repository skills are bad.
    skill_catalog()

    # The connected system is an optional capability. Its outage must not take
    # down general chat, planning, presentations, or web search for the process.
    connected_tools = await PersistentMcpTools.load_registered_tools()

    model = build_llm("auto", 0.0)
    agents = get_subagents(model=model, mcp_tools=connected_tools)
    middleware = [PlanModeMiddleware()]
    if agents:
        middleware.append(TurnSelectionMiddleware(CONNECTED_SUBAGENT_NAME))
    middleware.extend([recover_ask_user_markup, model_selector])
    main_agent = create_deep_agent(
        model=model,
        system_prompt=GENERAL_AGENT_PROMPT,
        subagents=agents,
        tools=[
            internet_search,
            fetch_webpage_content,
            ask_user,
            present_ui,
            present_report,
        ],
        middleware=middleware,
        backend=build_agent_backend(),
        checkpointer=checkpointer,
        context_schema=TurnContext,
        permissions=[
            FilesystemPermission(
                operations=["write"],
                paths=["/skills", "/skills/**"],
                mode="deny",
            )
        ],
        # interrupt_on={"internet_search": True},
        # skills=main_skill_sources(),
    )
    log.info("built deep agent in %.3f seconds", time.perf_counter() - started)
    return main_agent
