"""Apply explicit agent, tool, and skill choices to one main-agent turn."""

from collections.abc import Mapping

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage, ToolMessage

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
            "present_file",
            "present_ui",
            "present_report",
        }
    )
    WEB_TOOL_NAMES = frozenset({"internet_search", "fetch_webpage_content"})

    def __init__(self, connected_subagent_name: str | None):
        self.connected_subagent_name = connected_subagent_name

    @staticmethod
    def web_search_enabled(context):
        if context is None:
            return True
        mentioned_tools = {
            item_id for kind, item_id in context.mentions if kind == "tool"
        }
        return "web_search" in context.tools or bool(
            mentioned_tools & TurnSelectionMiddleware.WEB_TOOL_NAMES
        )

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
        web_search_enabled = self.web_search_enabled(context)
        tools = []
        for tool in request.tools:
            name = tool_name(tool)
            if name in self.WEB_TOOL_NAMES and not web_search_enabled:
                continue
            tools.append(tool)

        instructions = mention_prompts(context.mentions)
        if (
            self.connected_subagent_name
            and delegation_requested
            and not mentioned_agent
        ):
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

    def _blocked_tool_message(self, request):
        context = request.runtime.context if request.runtime else None
        name = request.tool_call["name"]
        if name in self.WEB_TOOL_NAMES and not self.web_search_enabled(context):
            return ToolMessage(
                content="Web search is disabled for this turn.",
                name=name,
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return None

    def wrap_tool_call(self, request, handler):
        blocked = self._blocked_tool_message(request)
        return blocked if blocked is not None else handler(request)

    async def awrap_tool_call(self, request, handler):
        blocked = self._blocked_tool_message(request)
        return blocked if blocked is not None else await handler(request)
