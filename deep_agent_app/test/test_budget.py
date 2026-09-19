"""Shared model/tool execution budget tests."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime

from deep_agent_app.agent.budget import (
    PRESENTATION_VALIDATION_LIMIT,
    RunBudget,
    RunBudgetExceeded,
    ToolCallBudgetMiddleware,
)
from deep_agent_app.agent.context import TurnContext
from deep_agent_app.agent.llm.routing import model_selector


class RunBudgetTests(SimpleTestCase):
    def test_model_and_tool_limits_are_independent_and_fail_closed(self):
        budget = RunBudget(max_model_calls=1, max_tool_calls=2)
        budget.consume_model_call()
        budget.consume_tool_call()
        budget.consume_tool_call()
        with self.assertRaisesRegex(RunBudgetExceeded, "model-call"):
            budget.consume_model_call()
        with self.assertRaisesRegex(RunBudgetExceeded, "tool-call"):
            budget.consume_tool_call()
        self.assertEqual((budget.model_calls, budget.tool_calls), (1, 2))

    async def test_tool_middleware_counts_actual_attempts(self):
        budget = RunBudget(2, 1)
        request = SimpleNamespace(
            runtime=Runtime(context=TurnContext(run_budget=budget))
        )
        middleware = ToolCallBudgetMiddleware()
        seen = []

        async def handler(_request):
            seen.append("called")
            return "ok"

        self.assertEqual(await middleware.awrap_tool_call(request, handler), "ok")
        with self.assertRaises(RunBudgetExceeded):
            await middleware.awrap_tool_call(request, handler)
        self.assertEqual(seen, ["called"])

    async def test_presentation_validation_failures_stop_at_three(self):
        budget = RunBudget(8, 8)
        request = SimpleNamespace(
            runtime=Runtime(context=TurnContext(run_budget=budget)),
            tool_call={"name": "present_ui"},
        )
        middleware = ToolCallBudgetMiddleware()

        async def handler(_request):
            return ToolMessage(
                content="Invalid present_ui block. Correct the arguments.",
                tool_call_id="bad-ui",
            )

        for _ in range(PRESENTATION_VALIDATION_LIMIT - 1):
            await middleware.awrap_tool_call(request, handler)
        with self.assertRaisesRegex(RunBudgetExceeded, "present_ui validation"):
            await middleware.awrap_tool_call(request, handler)
        self.assertEqual(budget.tool_calls, PRESENTATION_VALIDATION_LIMIT)

    async def test_empty_response_retry_consumes_another_model_attempt(self):
        model = FakeListChatModel(responses=["unused"])
        budget = RunBudget(1, 2)
        request = ModelRequest(
            model=model,
            messages=[],
            runtime=Runtime(context=TurnContext(run_budget=budget)),
        )
        calls = []

        async def handler(_request):
            calls.append(1)
            return ModelResponse(result=[AIMessage(content="")])

        with (
            patch(
                "deep_agent_app.agent.llm.routing.clients.build_llm",
                return_value=model,
            ),
            patch(
                "deep_agent_app.agent.llm.routing.reasoning.thinking_model_settings",
                return_value={},
            ),
            self.assertLogs("deep_agent_app.agent.llm.routing", level="WARNING"),
            self.assertRaises(RunBudgetExceeded),
        ):
            await model_selector.awrap_model_call(request, handler)
        self.assertEqual((len(calls), budget.model_calls), (1, 1))
