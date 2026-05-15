"""Run-scoped planning without rebuilding the graph."""

from collections.abc import Mapping

from langchain.agents.middleware import TodoListMiddleware

PLAN_MODE_PROMPT = """## Plan mode

The user explicitly enabled Plan mode for this turn.

- For work that needs tools or several meaningful steps, call `write_todos` before any other tool. Keep the plan short, concrete, and ordered.
- Keep exactly one current plan. Update it as work progresses: complete finished steps, put the current step in progress, and revise future steps when results change the approach.
- Do not mark a step completed until its work and checks are actually complete.
- The plan tracks execution; it is not the final answer. After completing the plan, give the user the requested result.
- For a direct conversational answer that requires no tools or multi-step work, answer normally without manufacturing a plan.
"""


def tool_name(tool):
    if isinstance(tool, Mapping):
        function = tool.get("function")
        return tool.get("name") or (
            function.get("name") if isinstance(function, Mapping) else None
        )
    return getattr(tool, "name", None)


class PlanModeMiddleware(TodoListMiddleware):
    def __init__(self):
        super().__init__(system_prompt=PLAN_MODE_PROMPT)

    @staticmethod
    def enabled(request):
        context = request.runtime.context if request.runtime else None
        return bool(context and context.plan)

    @staticmethod
    def without_plan_tool(request):
        return request.override(
            tools=[tool for tool in request.tools if tool_name(tool) != "write_todos"]
        )

    def wrap_model_call(self, request, handler):
        if self.enabled(request):
            return super().wrap_model_call(request, handler)
        return handler(self.without_plan_tool(request))

    async def awrap_model_call(self, request, handler):
        if self.enabled(request):
            return await super().awrap_model_call(request, handler)
        return await handler(self.without_plan_tool(request))
