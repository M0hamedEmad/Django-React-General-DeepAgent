"""Opt-in conversation compaction tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.state import StateBackend
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deep_agent_app.agent.budget import (
    ACTIVE_RUN_BUDGET,
    RunBudget,
    RunBudgetExceeded,
)
from deep_agent_app.agent.context import TurnContext
from deep_agent_app.agent.middleware import compaction


class CompactionPolicyTests(SimpleTestCase):
    def test_enabled_requires_real_boolean(self):
        with (
            patch.object(compaction, "CONTEXT_COMPACTION", {"enabled": "false"}),
            self.assertRaisesRegex(ImproperlyConfigured, "must be a boolean"),
        ):
            compaction.compaction_policy()

    def test_disabled_policy_does_not_require_provider_windows(self):
        with patch.object(compaction, "CONTEXT_COMPACTION", {"enabled": False}):
            self.assertIsNone(compaction.compaction_policy())

    def test_enabled_policy_requires_verified_window_for_every_model(self):
        policy = {
            "enabled": True,
            "trigger_tokens": 100,
            "reserve_tokens": 20,
            "keep_messages": 2,
        }
        with (
            patch.object(compaction, "CONTEXT_COMPACTION", policy),
            patch.object(
                compaction,
                "PROVIDERS",
                {"one": {"max_input_tokens": 120}, "two": {}},
            ),
            self.assertRaisesRegex(ImproperlyConfigured, "provider 'two'"),
        ):
            compaction.compaction_policy()

        with (
            patch.object(compaction, "CONTEXT_COMPACTION", policy),
            patch.object(
                compaction,
                "PROVIDERS",
                {"one": {"max_input_tokens": 120}},
            ),
        ):
            self.assertEqual(compaction.compaction_policy(), (100, 2))

    async def test_summary_call_counts_against_the_turn_limit(self):
        model = FakeListChatModel(responses=["summary"])
        summary_model = compaction.BudgetedSummaryModel(model, "summary-provider")
        budget = RunBudget(1, 2)
        token = ACTIVE_RUN_BUDGET.set(budget)
        try:
            self.assertEqual(
                (await summary_model.ainvoke("summarize")).content,
                "summary",
            )
            with self.assertRaises(RunBudgetExceeded):
                await summary_model.ainvoke("summarize again")
        finally:
            ACTIVE_RUN_BUDGET.reset(token)
        self.assertEqual(budget.model_calls, 1)

    def test_opt_in_middleware_uses_explicit_threshold(self):
        model = FakeListChatModel(responses=["summary"])
        with (
            patch.object(
                compaction,
                "CONTEXT_COMPACTION",
                {
                    "enabled": True,
                    "trigger_tokens": 100,
                    "reserve_tokens": 20,
                    "keep_messages": 2,
                },
            ),
            patch.object(
                compaction,
                "PROVIDERS",
                {"one": {"max_input_tokens": 120}},
            ),
            patch.object(compaction, "MODEL_ROLES", {"flash": "one"}),
        ):
            middleware = compaction.make_compaction_middleware(model, StateBackend())
        self.assertEqual(middleware.name, "SummarizationMiddleware")
        self.assertEqual(middleware._lc_helper.trigger, ("tokens", 100))
        self.assertEqual(middleware.model._provider_id, "one")
        self.assertIn(
            "pending or unknown operation outcomes",
            middleware._lc_helper.summary_prompt,
        )

    async def test_compaction_offloads_old_messages_and_preserves_raw_state(self):
        model = FakeListChatModel(responses=["Summary of the old exchange."])
        raw_messages = [
            HumanMessage(content="First decision: use the approved source."),
            AIMessage(content="Acknowledged."),
            HumanMessage(content="Second decision: use USD."),
            AIMessage(content="Acknowledged."),
            HumanMessage(content="Now prepare the final answer."),
        ]
        seen = []

        async def handler(request):
            seen.extend(request.messages)
            return ModelResponse(result=[AIMessage(content="Final answer")])

        with TemporaryDirectory() as directory:
            middleware = compaction.SummarizationMiddleware(
                model=compaction.BudgetedSummaryModel(model, "summary-provider"),
                backend=FilesystemBackend(root_dir=directory),
                trigger=("tokens", 1),
                keep=("messages", 2),
            )
            request = ModelRequest(
                model=model,
                messages=raw_messages,
                runtime=Runtime(context=TurnContext()),
            )
            response = await middleware.awrap_model_call(request, handler)

        self.assertEqual(response.model_response.result[0].content, "Final answer")
        self.assertEqual(len(raw_messages), 5)
        self.assertLess(len(seen), len(raw_messages))
        self.assertIn("Summary of the old exchange", seen[0].content)
        self.assertIn("/conversation_history/", seen[0].content)
        self.assertIn("_summarization_event", response.command.update)

    async def test_compaction_offload_stays_inside_authenticated_workspace(self):
        from deep_agent_app.agent.backend import (
            ScopedFilesystemBackend,
            WorkspaceContextMiddleware,
        )

        model = FakeListChatModel(responses=["Scoped summary."])
        messages = [
            HumanMessage(content="Keep this decision."),
            AIMessage(content="Acknowledged."),
            HumanMessage(content="Prepare the result."),
        ]

        async def handler(_request):
            return ModelResponse(result=[AIMessage(content="Final answer")])

        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspaces"
            backend = ScopedFilesystemBackend(root)
            middleware = compaction.SummarizationMiddleware(
                model=compaction.BudgetedSummaryModel(model, "summary-provider"),
                backend=backend,
                trigger=("tokens", 1),
                keep=("messages", 1),
            )
            request = ModelRequest(
                model=model,
                messages=messages,
                runtime=Runtime(
                    context=TurnContext(
                        workspace_id="workspace-a",
                        thread_id="thread-a",
                    )
                ),
            )
            await WorkspaceContextMiddleware().awrap_model_call(
                request,
                lambda scoped_request: middleware.awrap_model_call(
                    scoped_request,
                    handler,
                ),
            )

            history = root / "workspace-a" / "thread-a" / "conversation_history"
            self.assertTrue(any(history.glob("*.md")))
            self.assertFalse((root / "workspace-a" / "thread-b").exists())
            self.assertFalse((root / "workspace-b").exists())

    async def test_compaction_event_survives_checkpointed_graph_turn(self):
        from deepagents import create_deep_agent
        from langgraph.checkpoint.memory import InMemorySaver

        from deep_agent_app.chat.streaming import pump_agent
        from deep_agent_app.test.tests import FakeToolModel

        agent_model = FakeToolModel(responses=[AIMessage(content="Final answer")])
        summary_model = FakeListChatModel(
            responses=["Use USD and the approved source."]
        )
        backend = StateBackend()
        middleware = compaction.SummarizationMiddleware(
            model=compaction.BudgetedSummaryModel(summary_model, "summary-provider"),
            backend=backend,
            trigger=("tokens", 1),
            keep=("messages", 2),
        )
        graph = create_deep_agent(
            model=agent_model,
            tools=[],
            subagents=[],
            middleware=[middleware],
            backend=backend,
            checkpointer=InMemorySaver(),
            context_schema=TurnContext,
        )
        config = {"configurable": {"thread_id": "compaction-test"}}
        raw_messages = [
            HumanMessage(content="Use the approved source."),
            AIMessage(content="Understood."),
            HumanMessage(content="Use USD."),
            AIMessage(content="Understood."),
            HumanMessage(content="Give the answer."),
        ]
        budget = RunBudget(4, 4, filter_internal_model_text=True)
        events = []
        token = ACTIVE_RUN_BUDGET.set(budget)
        try:
            stream = await graph.astream_events(
                {"messages": raw_messages},
                config,
                version="v3",
                context=TurnContext(run_budget=budget),
            )
            async with stream:
                await pump_agent(stream, "main", events.append)
        finally:
            ACTIVE_RUN_BUDGET.reset(token)

        state = await graph.aget_state(config)
        self.assertEqual(state.values["messages"][-1].content, "Final answer")
        self.assertEqual(len(state.values["messages"]), 6)
        self.assertIn("_summarization_event", state.values)
        self.assertEqual(budget.model_calls, 1)
        visible_text = "".join(
            event["text"] for event in events if event["type"] == "token"
        )
        self.assertEqual(visible_text, "Final answer")
        self.assertEqual(
            len([event for event in events if event["type"] == "_usage_end"]),
            2,
        )
        summary_usage = next(
            event
            for event in events
            if event["type"] == "_usage_end" and event["provider_id"]
        )
        self.assertEqual(summary_usage["provider_id"], "summary-provider")
