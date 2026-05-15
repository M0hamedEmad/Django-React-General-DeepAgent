"""Apply explicit agent, tool, and skill choices to one main-agent turn."""

from collections.abc import Mapping

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from deep_agent_app.utilities.composer import mention_prompts

from ..skills import resolve_skill


def tool_name(tool):
    if isinstance(tool, Mapping):
        function = tool.get("function")
        return tool.get("name") or (
            function.get("name") if isinstance(function, Mapping) else None
        )
    return getattr(tool, "name", None)


def with_instruction(system_message, instruction):
    if not instruction:
        return system_message
    if system_message is None:
        return SystemMessage(content=instruction)
    return system_message.model_copy(
        update={"content": f"{system_message.content}\n\n{instruction}"}
    )


class TurnSelectionMiddleware(AgentMiddleware):
    """Control optional search and run-scoped routing without graph mutation."""

    MAIN_TOOL_NAMES = frozenset(
        {
            "internet_search",
            "fetch_webpage_content",
            "ask_user",
            "present_ui",
            "present_report",
        }
    )

    def __init__(self, connected_subagent_name: str):
        self.connected_subagent_name = connected_subagent_name

    def prepare(self, request):
        context = request.runtime.context if request.runtime else None
        if context is None:
            return request

        mentions = set(context.mentions)
        mentioned_tools = {item_id for kind, item_id in mentions if kind == "tool"}
        selected_skills = [
            skill
            for kind, item_id in context.mentions
            if kind == "skill" and (skill := resolve_skill(item_id)) is not None
        ]
        mentioned_agent = any(
            kind == "agent" and item_id != "general" for kind, item_id in mentions
        )
        delegation_requested = (
            context.agent != "general"
            or mentioned_agent
            or bool(mentioned_tools - self.MAIN_TOOL_NAMES)
            or any(skill.requires_connection for skill in selected_skills)
        )
        web_search_enabled = (
            "web_search" in context.tools or "internet_search" in mentioned_tools
        )
        tools = []
        for tool in request.tools:
            name = tool_name(tool)
            if (
                name in ("internet_search", "fetch_webpage_content")
                and not web_search_enabled
            ):
                continue
            tools.append(tool)

        instructions = mention_prompts(context.mentions)
        if delegation_requested and not mentioned_agent:
            instructions.append(
                "The user selected the current company-system capability for this turn. "
                "Delegate the connected-system work to the "
                f"`{self.connected_subagent_name}` subagent before answering."
            )
        if not web_search_enabled:
            instructions.append("Web search is disabled for this turn.")
        return request.override(
            tools=tools,
            system_message=with_instruction(
                request.system_message,
                "\n".join(instructions),
            ),
        )

    def wrap_model_call(self, request, handler):
        return handler(self.prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self.prepare(request))
