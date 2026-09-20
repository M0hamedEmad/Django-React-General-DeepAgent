"""Composition root for the shared main Deep Agent graph."""

import logging
import time

from deepagents import HarnessProfile, create_deep_agent, register_harness_profile

from deep_agent_app.utilities.constants import CONTEXT_COMPACTION

from .backend import WorkspaceContextMiddleware
from .budget import ToolCallBudgetMiddleware
from .context import TurnContext
from .integrations import PersistentMcpTools
from .llm.clients import build_llm
from .llm.routing import model_selector
from .middleware.ask_user_recovery import recover_ask_user_markup
from .middleware.compaction import make_compaction_middleware
from .middleware.planning import PlanModeMiddleware
from .middleware.selection import TurnSelectionMiddleware
from .prompts import GENERAL_AGENT_PROMPT, GENERAL_SUBAGENT_PROMPT
from .skills import build_agent_backend, main_skill_sources, skill_catalog
from .subagent import CONNECTED_SUBAGENT_NAME, build_subagent, get_subagents
from .tools.ask_user import ask_user
from .tools.files import present_file
from .tools.present_ui import present_ui
from .tools.reports import present_report
from .tools.search import internet_search, fetch_webpage_content

log = logging.getLogger(__name__)

# Compaction is opt-in until the selected model windows and production behavior
# have been verified.
if CONTEXT_COMPACTION.get("enabled") is not True:
    register_harness_profile(
        "openai",
        HarnessProfile(excluded_middleware=frozenset({"SummarizationMiddleware"})),
    )


async def build_agent(checkpointer):
    """Initialize integrations once and compile the production graph."""
    started = time.perf_counter()
    # Fail before opening network integrations if repository skills are bad.
    skill_catalog()

    # The connected system is an optional capability. Its outage must not take
    # down general chat, planning, presentations, or web search for the process.
    connected_tools = await PersistentMcpTools.load_registered_tools()

    model = build_llm("main", 0.0)
    summary_model = (
        build_llm("flash", 0.0) if CONTEXT_COMPACTION.get("enabled") is True else model
    )
    backend = build_agent_backend()
    connected_agents = get_subagents(model=model, mcp_tools=connected_tools)
    for subagent in connected_agents:
        compaction = make_compaction_middleware(summary_model, backend)
        if compaction is not None:
            subagent["middleware"].append(compaction)

    main_tools = [
        internet_search,
        fetch_webpage_content,
        ask_user,
        present_file,
        present_ui,
        present_report,
    ]
    general_middleware = [
        WorkspaceContextMiddleware(),
        TurnSelectionMiddleware(None),
        ToolCallBudgetMiddleware(),
        recover_ask_user_markup,
        model_selector,
    ]
    compaction = make_compaction_middleware(summary_model, backend)
    if compaction is not None:
        general_middleware.append(compaction)
    agents = [
        build_subagent(
            name="general-purpose",
            description="A delegated worker for general research and analysis.",
            system_prompt=GENERAL_SUBAGENT_PROMPT,
            model=model,
            tools=main_tools,
            middleware=general_middleware,
            skills=main_skill_sources(),
        ),
        *connected_agents,
    ]
    middleware = [
        WorkspaceContextMiddleware(),
        PlanModeMiddleware(),
        TurnSelectionMiddleware(CONNECTED_SUBAGENT_NAME if connected_agents else None),
        ToolCallBudgetMiddleware(),
        recover_ask_user_markup,
        model_selector,
    ]
    compaction = make_compaction_middleware(summary_model, backend)
    if compaction is not None:
        middleware.append(compaction)
    main_agent = create_deep_agent(
        model=model,
        system_prompt=GENERAL_AGENT_PROMPT,
        subagents=agents,
        tools=main_tools,
        middleware=middleware,
        backend=backend,
        checkpointer=checkpointer,
        context_schema=TurnContext,
        # interrupt_on={"internet_search": True},
        skills=main_skill_sources(),
    )
    log.info("built deep agent in %.3f seconds", time.perf_counter() - started)
    return main_agent
