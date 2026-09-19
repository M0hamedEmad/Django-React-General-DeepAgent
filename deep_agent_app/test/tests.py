"""Tests run without a model or an ERP.

`ChatApiTests` swap `chat.run_turn` for a generator that replays canned
events, so they check the API and the wire format. `InterruptTests` run the
real pump over a deep agent driven by a scripted model, so the pause/resume
path (questions, tool approvals) is exercised end to end."""

import asyncio
import inspect
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deep_agent_app import chat
from deep_agent_app.chat import history as chat_history
from deep_agent_app.chat import streaming as chat_streaming
from deep_agent_app.chat import usage as chat_usage
from deep_agent_app.runtime import RuntimeCapacityError, agent_runtime
from deep_agent_app.utilities import model_registry
from deep_agent_app.agent.llm import clients as llm_clients
from deep_agent_app.agent.llm import reasoning as reasoning_module
from deep_agent_app.models import Thread, UserWorkspace

TURN = [
    {"type": "thinking", "who": "main", "text": "hmm"},
    {"type": "token", "who": "main", "text": "Let me "},
    {"type": "token", "who": "main", "text": "check."},
    {
        "type": "tool_call",
        "who": "main",
        "id": "call_1",
        "name": "task",
        "args": {"name": "erp"},
    },
    {"type": "subagent", "id": "d1", "name": "erp", "status": "started"},
    {"type": "token", "who": "erp", "text": "querying"},
    {
        "type": "tool_call",
        "who": "erp",
        "id": "call_2",
        "name": "query",
        "args": {"q": "x"},
    },
    {
        "type": "tool_result",
        "who": "erp",
        "id": "call_2",
        "name": "query",
        "result": "{}",
        "error": None,
    },
    {"type": "subagent", "id": "d1", "name": "erp", "status": "completed"},
    {"type": "ping"},
    {
        "type": "tool_result",
        "who": "main",
        "id": "call_1",
        "name": "task",
        "result": "done",
        "error": "boom",
    },
    {"type": "token", "who": "main", "text": "Done."},
    {
        "type": "interrupt",
        "id": "i1",
        "value": {"kind": "question", "question": "Which?", "options": ["A"]},
    },
]


def replay(events):
    async def run_turn(
        thread_id,
        text=None,
        workspace_id=None,
        resume=None,
        options=None,
        message_id=None,
        checkpoint_config=None,
    ):
        for e in events:
            yield e

    return run_turn


def failing(
    thread_id,
    text=None,
    workspace_id=None,
    resume=None,
    options=None,
    message_id=None,
    checkpoint_config=None,
):
    async def run_turn():
        yield {"type": "token", "who": "main", "text": "Star"}
        raise RuntimeError("model went away")

    return run_turn()


async def read(response):
    """The raw SSE body and its JSON parts. Every stream must end in [DONE]."""
    body = b"".join([chunk async for chunk in response.streaming_content]).decode()
    assert body.endswith("data: [DONE]\n\n"), body[-200:]
    parts = [
        json.loads(line[len("data: ") :])
        for line in body.split("\n\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    return body, parts


class FakeToolModel(BaseChatModel):
    """Answers with the scripted messages in order; the last one repeats."""

    responses: list
    i: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Async API tests already run inside asgiref's executor thread. Give
        # the fake an actual async path instead of nesting another executor;
        # real provider models also implement this path directly.
        return self._generate(messages, stop, run_manager, **kwargs)

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake"


def tool_call(name, args, id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id}])


def fake_agent(responses, tools, **kwargs):
    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import InMemorySaver

    return create_deep_agent(
        model=FakeToolModel(responses=responses),
        tools=tools,
        checkpointer=InMemorySaver(),
        **kwargs,
    )


def dangerous(x: int) -> str:
    """Needs a person's approval."""
    return f"did {x}"


class CompanySkillTests(SimpleTestCase):
    def test_executive_brief_is_discoverable_and_scoped_to_main_agent(self):
        from deep_agent_app.utilities import composer
        from deep_agent_app.utilities.constants import SKILLS_ROOT
        from deep_agent_app.agent import (
            CONNECTED_SKILL_SOURCES,
            MAIN_SKILL_SOURCES,
        )

        brief = next(
            skill for skill in composer.skills() if skill["id"] == "executive-brief"
        )

        self.assertEqual(brief["path"], "/skills/general/executive-brief/SKILL.md")
        self.assertTrue(brief["description"].startswith("Turn company information"))
        self.assertIn(("/skills/general", "Company"), MAIN_SKILL_SOURCES)
        self.assertNotIn(
            ("/skills/general", "Company"),
            CONNECTED_SKILL_SOURCES,
        )

        skill_root = SKILLS_ROOT / "general/executive-brief"
        self.assertTrue((skill_root / "references/brief-template.md").is_file())
        evals = json.loads((skill_root / "evals/evals.json").read_text())
        self.assertEqual(evals["skill_name"], "executive-brief")
        self.assertEqual(len(evals["evals"]), 3)

    def test_project_planning_is_discoverable_with_its_resources(self):
        from deep_agent_app.utilities import composer
        from deep_agent_app.utilities.constants import SKILLS_ROOT

        project = next(
            skill for skill in composer.skills() if skill["id"] == "project-planning"
        )

        self.assertEqual(project["path"], "/skills/general/project-planning/SKILL.md")
        self.assertTrue(project["description"].startswith("Turn a company objective"))

        skill_root = SKILLS_ROOT / "general/project-planning"
        self.assertTrue((skill_root / "references/project-plan-template.md").is_file())
        evals = json.loads((skill_root / "evals/evals.json").read_text())
        self.assertEqual(evals["skill_name"], "project-planning")
        self.assertEqual(len(evals["evals"]), 3)


class PhaseZeroDelegationTests(SimpleTestCase):
    async def test_actual_builder_compiles_with_main_skills(self):
        from langgraph.checkpoint.memory import InMemorySaver

        from deep_agent_app.agent import agent as builder
        from deep_agent_app.agent.context import TurnContext

        model = FakeToolModel(responses=[AIMessage(content="ready")])
        with (
            patch.object(
                builder.PersistentMcpTools,
                "load_registered_tools",
                AsyncMock(return_value=[]),
            ),
            patch.object(builder, "build_llm", return_value=model),
            patch.object(llm_clients, "build_llm", return_value=model),
        ):
            graph = await builder.build_agent(InMemorySaver())
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="Hello")]},
                {"configurable": {"thread_id": "phase-zero-builder"}},
                context=TurnContext(
                    workspace_id="phase-zero-workspace",
                    thread_id="phase-zero-builder",
                ),
            )

        self.assertEqual(result["messages"][-1].content, "ready")

    async def test_bundled_skill_can_read_resources_and_present_report(self):
        from langchain_core.messages import ToolMessage
        from langgraph.checkpoint.memory import InMemorySaver

        from deep_agent_app.agent import agent as builder
        from deep_agent_app.agent.context import TurnContext

        model = FakeToolModel(
            responses=[
                tool_call(
                    "read_file",
                    {"file_path": "/skills/general/executive-brief/SKILL.md"},
                    "read-skill",
                ),
                tool_call(
                    "present_report",
                    {
                        "title": "Incident brief",
                        "blocks": [
                            {"type": "markdown", "content": "Errors rose to 7.8%."}
                        ],
                    },
                    "render-brief",
                ),
                AIMessage(content="The brief is ready."),
            ]
        )
        with (
            patch.object(
                builder.PersistentMcpTools,
                "load_registered_tools",
                AsyncMock(return_value=[]),
            ),
            patch.object(builder, "build_llm", return_value=model),
            patch.object(llm_clients, "build_llm", return_value=model),
        ):
            graph = await builder.build_agent(InMemorySaver())
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="@executive-brief make a brief")]},
                {"configurable": {"thread_id": "phase-zero-skill"}},
                context=TurnContext(
                    workspace_id="phase-zero-workspace",
                    thread_id="phase-zero-skill",
                    mentions=(("skill", "executive-brief"),),
                ),
            )

        tool_messages = [
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        self.assertIn("# Executive Brief", tool_messages[0].content)
        self.assertIn("Report 'Incident brief' is ready", tool_messages[1].content)
        self.assertEqual(result["messages"][-1].content, "The brief is ready.")

    async def test_project_planning_skill_can_read_its_reference(self):
        from langchain_core.messages import ToolMessage
        from langgraph.checkpoint.memory import InMemorySaver

        from deep_agent_app.agent import agent as builder
        from deep_agent_app.agent.context import TurnContext

        model = FakeToolModel(
            responses=[
                tool_call(
                    "read_file",
                    {"file_path": "/skills/general/project-planning/SKILL.md"},
                    "read-skill",
                ),
                tool_call(
                    "read_file",
                    {
                        "file_path": (
                            "/skills/general/project-planning/references/"
                            "project-plan-template.md"
                        )
                    },
                    "read-template",
                ),
                AIMessage(content="Proposed outline ready."),
            ]
        )
        with (
            patch.object(
                builder.PersistentMcpTools,
                "load_registered_tools",
                AsyncMock(return_value=[]),
            ),
            patch.object(builder, "build_llm", return_value=model),
            patch.object(llm_clients, "build_llm", return_value=model),
        ):
            graph = await builder.build_agent(InMemorySaver())
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="Draft a project outline")]},
                {"configurable": {"thread_id": "phase-zero-reference"}},
                context=TurnContext(
                    workspace_id="phase-zero-workspace",
                    thread_id="phase-zero-reference",
                    mentions=(("skill", "project-planning"),),
                ),
            )

        tool_messages = [
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        self.assertIn("# Project Planning", tool_messages[0].content)
        self.assertIn("Objective", tool_messages[1].content)
        self.assertEqual(result["messages"][-1].content, "Proposed outline ready.")

    async def test_selected_model_and_disabled_web_policy_reach_general_worker(self):
        from deepagents import create_deep_agent
        from langgraph.checkpoint.memory import InMemorySaver

        from deep_agent_app.agent.context import TurnContext
        from deep_agent_app.agent.budget import RunBudget, ToolCallBudgetMiddleware
        from deep_agent_app.agent.llm.routing import model_selector
        from deep_agent_app.agent.middleware.selection import TurnSelectionMiddleware

        web_calls = []

        async def internet_search(query: str) -> str:
            """Search public pages."""
            web_calls.append(query)
            return "network result"

        base = FakeToolModel(responses=[AIMessage(content="base model answered")])
        selected = FakeToolModel(
            responses=[
                tool_call(
                    "task",
                    {"description": "Look this up", "subagent_type": "general-purpose"},
                    "main-task",
                ),
                tool_call("internet_search", {"query": "private"}, "worker-web"),
                AIMessage(content="worker done"),
                AIMessage(content="main done"),
            ]
        )
        fallback = FakeToolModel(responses=[AIMessage(content="fallback")])
        graph = create_deep_agent(
            model=base,
            tools=[],
            subagents=[
                {
                    "name": "general-purpose",
                    "description": "General worker",
                    "system_prompt": "Do the delegated work.",
                    "model": base,
                    "tools": [internet_search],
                    "middleware": [
                        TurnSelectionMiddleware(None),
                        ToolCallBudgetMiddleware(),
                        model_selector,
                    ],
                }
            ],
            middleware=[
                TurnSelectionMiddleware(None),
                ToolCallBudgetMiddleware(),
                model_selector,
            ],
            context_schema=TurnContext,
            checkpointer=InMemorySaver(),
        )

        budget = RunBudget(8, 8)
        with patch.object(
            llm_clients,
            "build_llm",
            side_effect=lambda provider, _temperature: (
                selected if provider == "openai" else fallback
            ),
        ):
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="Research this")]},
                {"configurable": {"thread_id": "phase-zero-delegation"}},
                context=TurnContext(model="openai", tools=(), run_budget=budget),
            )

        self.assertEqual(base.i, 0)
        self.assertEqual(selected.i, 4)
        self.assertEqual(fallback.i, 0)
        self.assertEqual(web_calls, [])
        self.assertEqual(budget.model_calls, 4)
        self.assertEqual(result["messages"][-1].content, "main done")


class SubagentStreamingTests(SimpleTestCase):
    @staticmethod
    async def _channel(subagent):
        yield subagent

    async def test_normally_drained_subagent_always_emits_completed(self):
        subagent = SimpleNamespace(name="company", status="started")
        events = []

        async def drain(stream, who, emit):
            return None

        with patch.object(chat_streaming, "pump_agent", drain):
            await chat_streaming.pump_subagents(self._channel(subagent), events.append)

        self.assertEqual(
            [event["status"] for event in events], ["started", "completed"]
        )
        self.assertEqual(events[0]["id"], events[1]["id"])

    async def test_failed_subagent_emits_terminal_status_before_raising(self):
        subagent = SimpleNamespace(name="company", status="started")
        events = []

        async def fail(stream, who, emit):
            raise RuntimeError("subagent failed")

        with (
            patch.object(chat_streaming, "pump_agent", fail),
            self.assertRaisesRegex(RuntimeError, "subagent failed"),
        ):
            await chat_streaming.pump_subagents(self._channel(subagent), events.append)

        self.assertEqual([event["status"] for event in events], ["started", "failed"])
        self.assertEqual(events[0]["id"], events[1]["id"])


class AskUserBatchUnitTests(SimpleTestCase):
    def test_one_interrupt_collects_all_answers_and_returns_labeled_transcript(self):
        from deep_agent_app.agent import ask_user

        with patch(
            "deep_agent_app.agent.tools.ask_user.interrupt",
            return_value={"q1": "Blue", "q2": "Weekly"},
        ) as pause:
            result = ask_user(
                questions=[
                    {
                        "question": "What is your favorite color?",
                        "options": ["Blue", "Green"],
                    },
                    {
                        "question": "How often should the report run?",
                        "options": ["Daily", "Weekly"],
                    },
                ]
            )

        pause.assert_called_once_with(
            {
                "kind": "questions",
                "questions": [
                    {
                        "id": "q1",
                        "question": "What is your favorite color?",
                        "options": ["Blue", "Green"],
                    },
                    {
                        "id": "q2",
                        "question": "How often should the report run?",
                        "options": ["Daily", "Weekly"],
                    },
                ],
            }
        )
        self.assertEqual(
            result,
            "Q: What is your favorite color?\nA: Blue\n\n"
            "Q: How often should the report run?\nA: Weekly",
        )

    def test_legacy_single_question_is_still_resumable(self):
        from deep_agent_app.agent import ask_user

        with patch(
            "deep_agent_app.agent.tools.ask_user.interrupt", return_value="Blue"
        ):
            result = ask_user(question="Favorite color?", options=["Blue"])

        self.assertEqual(result, "Q: Favorite color?\nA: Blue")

    def test_unanswered_questions_are_explicitly_labeled_as_skipped(self):
        from deep_agent_app.agent import ask_user

        with patch(
            "deep_agent_app.agent.tools.ask_user.interrupt",
            return_value={"q1": "Blue", "q2": None},
        ):
            result = ask_user(
                questions=[
                    {"question": "Favorite color?"},
                    {"question": "Report frequency?"},
                ]
            )

        self.assertEqual(
            result,
            "Q: Favorite color?\nA: Blue\n\nQ: Report frequency?\nA: Skipped",
        )

    def test_leaked_markup_with_multiple_questions_becomes_one_tool_call(self):
        from langchain.agents.middleware import ModelResponse

        from deep_agent_app.agent import repair_ask_user_response

        leaked = """<ask_user>
          <question>Favorite color?</question>
          <options><item>Blue</item><item>Green</item></options>
          <question>Report frequency?</question>
          <options><item>Daily</item><item>Weekly</item></options>
        </ask_user>"""
        with self.assertLogs("deep_agent_app.agent", level="WARNING"):
            response = repair_ask_user_response(
                ModelResponse(result=[AIMessage(content=leaked)])
            )

        self.assertEqual(
            response.result[0].tool_calls[0]["args"],
            {
                "questions": [
                    {"question": "Favorite color?", "options": ["Blue", "Green"]},
                    {"question": "Report frequency?", "options": ["Daily", "Weekly"]},
                ]
            },
        )

    def test_batch_pauses_and_resumes_through_a_compiled_deep_agent(self):
        from deep_agent_app.agent import ask_user
        from langgraph.types import Command

        graph = fake_agent(
            [
                tool_call(
                    "ask_user",
                    {
                        "questions": [
                            {"question": "Color?", "options": ["Blue"]},
                            {"question": "Frequency?", "options": ["Weekly"]},
                        ]
                    },
                    "batch-call",
                ),
                AIMessage(content="done"),
            ],
            [ask_user],
        )
        config = {"configurable": {"thread_id": "compiled-batch"}}
        paused = graph.invoke(
            {"messages": [HumanMessage(content="Configure it")]}, config
        )
        pending = paused["__interrupt__"][0]

        completed = graph.invoke(
            Command(resume={pending.id: {"q1": "Blue", "q2": "Weekly"}}),
            config,
        )

        self.assertEqual(
            completed["messages"][-2].content,
            "Q: Color?\nA: Blue\n\nQ: Frequency?\nA: Weekly",
        )
        self.assertEqual(completed["messages"][-1].content, "done")


class ApiTestCase(TestCase):
    def setUp(self):
        workspace_migration_patcher = patch(
            "deep_agent_app.views.migrate_legacy_user_workspace"
        )
        self.workspace_migration = workspace_migration_patcher.start()
        self.addCleanup(workspace_migration_patcher.stop)
        # aforce_login does not check a password. Avoid spending most of the
        # test suite hashing two passwords before every API test.
        self.user = User.objects.create_user("mona")
        self.other = User.objects.create_user("omar")

    async def login(self, user=None):
        await self.async_client.aforce_login(user or self.user)

    async def post_chat(self, body):
        return await self.async_client.post(
            "/api/chat/", json.dumps(body), content_type="application/json"
        )

    async def messages(self, thread_id):
        return json.loads(
            (await self.async_client.get(f"/api/threads/{thread_id}/messages/")).content
        )["messages"]


class ChatApiTests(ApiTestCase):
    async def test_login_required(self):
        self.assertEqual(
            (await self.post_chat({"thread_id": "t1", "message": "hi"})).status_code,
            401,
        )
        self.assertEqual(
            (await self.async_client.get("/api/threads/")).status_code, 401
        )
        self.assertEqual((await self.async_client.get("/api/config/")).status_code, 401)

    async def test_chat_streams_ai_sdk_frames(self):
        await self.login()
        with patch.object(chat, "run_turn", replay(TURN)):
            response = await self.post_chat(
                {"thread_id": "t1", "message": "how many orders?"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "text/event-stream")
            self.assertEqual(response["x-vercel-ai-ui-message-stream"], "v1")
            body, parts = await read(response)

        self.assertIn(": ping\n\n", body)
        self.assertEqual(parts[0]["type"], "start")
        self.assertTrue(parts[0]["messageMetadata"]["created_at"])
        self.assertEqual(parts[-1], {"type": "finish"})
        self.assertEqual(
            [p["type"] for p in parts[1:-1]],
            [
                "reasoning-start",
                "reasoning-delta",
                "reasoning-end",
                "text-start",
                "text-delta",
                "text-delta",
                "text-end",
                "tool-input-available",
                "data-subagent",
                "reasoning-start",
                "reasoning-delta",
                "reasoning-end",  # subagent text is reasoning
                "tool-input-available",
                "tool-output-available",
                "data-subagent",
                "tool-output-error",
                "text-start",
                "text-delta",
                "text-end",
                "data-interrupt",
            ],
        )
        text_deltas = [p for p in parts if p["type"] == "text-delta"]
        self.assertEqual(text_deltas[0]["id"], text_deltas[1]["id"])
        self.assertNotEqual(text_deltas[0]["id"], text_deltas[2]["id"])
        self.assertEqual("".join(p["delta"] for p in text_deltas), "Let me check.Done.")
        tool_in = next(p for p in parts if p["type"] == "tool-input-available")
        self.assertEqual(
            tool_in,
            {
                "type": "tool-input-available",
                "toolCallId": "call_1",
                "toolName": "task",
                "input": {"name": "erp"},
            },
        )
        self.assertEqual(
            next(p for p in parts if p["type"] == "tool-output-error")["errorText"],
            "boom",
        )
        chips = [p for p in parts if p["type"] == "data-subagent"]
        self.assertEqual(
            chips[0],
            {
                "type": "data-subagent",
                "id": "d1",
                "data": {"name": "erp", "status": "started"},
            },
        )
        # Same id: the UI replaces the "started" chip with this one in place.
        self.assertEqual(
            chips[1],
            {
                "type": "data-subagent",
                "id": "d1",
                "data": {"name": "erp", "status": "completed"},
            },
        )
        interrupt = next(p for p in parts if p["type"] == "data-interrupt")
        self.assertEqual(
            interrupt,
            {
                "type": "data-interrupt",
                "id": "i1",
                "data": {"id": "i1", "value": TURN[-1]["value"]},
            },
        )

        thread = await Thread.objects.aget(id="t1")
        workspace = await UserWorkspace.objects.aget(user=self.user)
        self.assertEqual(thread.user_id, self.user.id)
        self.assertEqual(len(workspace.id.hex), 32)
        self.assertEqual(thread.title, "how many orders?")
        self.assertFalse(chat.is_turn_running("t1"))

    async def test_accepts_ai_sdk_request_shape_and_options(self):
        await self.login()
        seen = []

        async def run_turn(
            thread_id,
            text=None,
            workspace_id=None,
            resume=None,
            options=None,
            message_id=None,
            checkpoint_config=None,
        ):
            seen.append((thread_id, text, resume, options))
            yield {"type": "token", "who": "main", "text": "ok"}

        with patch.object(chat, "run_turn", run_turn):
            response = await self.post_chat(
                {
                    "id": "abc123",
                    "messages": [
                        {
                            "id": "m1",
                            "role": "user",
                            "parts": [{"type": "text", "text": "first"}],
                        },
                        {
                            "id": "m2",
                            "role": "assistant",
                            "parts": [{"type": "text", "text": "reply"}],
                        },
                        {
                            "id": "m3",
                            "role": "user",
                            "parts": [
                                {"type": "text", "text": "second "},
                                {"type": "text", "text": "part"},
                            ],
                        },
                    ],
                    "options": {"model": "ollama", "thinking": True, "junk": 1},
                }
            )
            await read(response)
        self.assertEqual(
            seen,
            [
                (
                    "abc123",
                    "second part",
                    None,
                    {
                        "model": "ollama",
                        "agent": "general",
                        "tools": ["web_search"],
                        "thinking": "high",
                        "plan": False,
                    },
                )
            ],
        )

    async def test_browser_message_id_and_options_are_persisted(self):
        await self.login()
        seen = []

        async def run_turn(
            thread_id,
            text=None,
            workspace_id=None,
            resume=None,
            options=None,
            message_id=None,
            checkpoint_config=None,
        ):
            seen.append((message_id, checkpoint_config))
            yield {"type": "token", "who": "main", "text": "ok"}

        options = {
            "model": "ollama",
            "agent": "general",
            "tools": ["web_search"],
            "thinking": "medium",
            "plan": True,
        }
        with patch.object(chat, "run_turn", run_turn):
            response = await self.post_chat(
                {
                    "thread_id": "saved-options",
                    "message": "stock report",
                    "message_id": "browser-user-1",
                    "options": options,
                }
            )
            await read(response)

        self.assertEqual(seen, [("browser-user-1", None)])
        thread = await Thread.objects.aget(id="saved-options")
        normalized_options = options
        self.assertEqual(thread.options, normalized_options)
        loaded = json.loads(
            (await self.async_client.get("/api/threads/saved-options/")).content
        )
        self.assertEqual(loaded["options"], normalized_options)

    async def test_edit_and_regenerate_branch_before_the_user_message(self):
        await self.login()
        await Thread.objects.acreate(id="branch-actions", user=self.user)
        checkpoint = {
            "configurable": {
                "thread_id": "branch-actions",
                "checkpoint_id": "before-user",
            }
        }
        branches = []
        runs = []

        async def branch_before_message(thread_id, message_id):
            branches.append((thread_id, message_id))
            return checkpoint, "original question"

        async def run_turn(
            thread_id,
            text=None,
            workspace_id=None,
            resume=None,
            options=None,
            message_id=None,
            checkpoint_config=None,
        ):
            runs.append((text, message_id, checkpoint_config))
            yield {"type": "token", "who": "main", "text": "new answer"}

        with (
            patch.object(chat, "branch_before_message", branch_before_message),
            patch.object(chat, "run_turn", run_turn),
        ):
            await read(
                await self.post_chat(
                    {
                        "thread_id": "branch-actions",
                        "message": "edited question",
                        "action": "edit",
                        "target_message_id": "user-1",
                    }
                )
            )
            await read(
                await self.post_chat(
                    {
                        "thread_id": "branch-actions",
                        "action": "regenerate",
                        "target_message_id": "user-1",
                    }
                )
            )

        self.assertEqual(
            branches,
            [
                ("branch-actions", "user-1"),
                ("branch-actions", "user-1"),
            ],
        )
        self.assertEqual(
            runs,
            [
                ("edited question", "user-1", checkpoint),
                ("original question", "user-1", checkpoint),
            ],
        )

    async def test_delete_message_rewinds_and_returns_the_transcript(self):
        await self.login()
        thread = await Thread.objects.acreate(id="delete-message", user=self.user)
        transcript = [
            {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "keep"}]}
        ]
        deleted = []

        async def delete_message(thread_id, message_id):
            deleted.append((thread_id, message_id))
            return transcript

        with patch.object(chat, "delete_message", delete_message):
            response = await self.async_client.delete(
                f"/api/threads/{thread.id}/messages/u2/"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(deleted, [(thread.id, "u2")])
        self.assertEqual(json.loads(response.content)["messages"], transcript)

    async def test_whitespace_only_blocks_are_not_streamed(self):
        """A model that emits only newlines between tool calls has said
        nothing: no block opens, so the UI has no empty fold to show. The
        whitespace before a block's first visible character stays with it."""
        await self.login()
        events = [
            {"type": "thinking", "who": "main", "text": "\n"},
            {"type": "token", "who": "main", "text": "  "},
            {
                "type": "tool_call",
                "who": "main",
                "id": "c1",
                "name": "query",
                "args": {},
            },
            {"type": "thinking", "who": "main", "text": "\n "},
            {"type": "thinking", "who": "main", "text": "real"},
            {"type": "token", "who": "main", "text": "ok"},
        ]
        with patch.object(chat, "run_turn", replay(events)):
            _, parts = await read(
                await self.post_chat({"thread_id": "ws", "message": "hi"})
            )
        self.assertEqual(
            [p["type"] for p in parts],
            [
                "start",
                "tool-input-available",
                "reasoning-start",
                "reasoning-delta",
                "reasoning-end",
                "text-start",
                "text-delta",
                "text-end",
                "finish",
            ],
        )
        self.assertEqual(
            next(p for p in parts if p["type"] == "reasoning-delta")["delta"], "\n real"
        )

    async def test_mentions_ride_with_the_options(self):
        from deep_agent_app.utilities.constants import CONNECTED_SYSTEM_ENABLED

        await self.login()
        seen = []

        async def run_turn(
            thread_id,
            text=None,
            workspace_id=None,
            resume=None,
            options=None,
            message_id=None,
            checkpoint_config=None,
        ):
            seen.append(options)
            yield {"type": "token", "who": "main", "text": "ok"}

        with patch.object(chat, "run_turn", run_turn):
            await read(
                await self.post_chat(
                    {
                        "thread_id": "m1",
                        "message": "@executive-brief review these notes with @connected",
                        "options": {"model": "ollama"},
                        "mentions": [
                            {"kind": "skill", "id": "executive-brief"},
                            {"kind": "agent", "id": "connected", "label": "dropped"},
                            {"kind": "nope", "id": "x"},
                            "junk",
                        ],
                    }
                )
            )
        self.assertEqual(
            seen,
            [
                {
                    "model": "ollama",
                    "agent": "general",
                    "tools": ["web_search"],
                    "thinking": "instant",
                    "plan": False,
                    "mentions": [
                        {"kind": "skill", "id": "executive-brief"},
                    ]
                    + (
                        [{"kind": "agent", "id": "connected"}]
                        if CONNECTED_SYSTEM_ENABLED
                        else []
                    ),
                }
            ],
        )

    async def test_slash_command_is_validated_and_stays_transient(self):
        await self.login()
        seen = []

        async def run_turn(
            thread_id,
            text=None,
            workspace_id=None,
            resume=None,
            options=None,
            message_id=None,
            checkpoint_config=None,
        ):
            seen.append((text, options))
            yield {"type": "token", "who": "main", "text": "ok"}

        with patch.object(chat, "run_turn", run_turn):
            response = await self.post_chat(
                {
                    "thread_id": "slash-report",
                    "message": "/report sales this month",
                    "command": "report",
                }
            )
            await read(response)

        self.assertEqual(seen[0][0], "/report sales this month")
        self.assertEqual(
            seen[0][1]["command"],
            {
                "id": "report",
                "prompt": "Use present_report to create a workspace report.",
            },
        )
        thread = await Thread.objects.aget(id="slash-report")
        self.assertNotIn("command", thread.options)

        rejected = await self.post_chat(
            {
                "thread_id": "bad-slash",
                "message": "/made-up report",
                "command": "made-up",
            }
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(await Thread.objects.filter(id="bad-slash").aexists())

    async def test_plan_updates_replace_one_ai_sdk_data_part(self):
        from deep_agent_app.views import ai_sdk_frames

        first = [
            {"content": "Find the invoices", "status": "in_progress"},
            {"content": "Summarize overdue totals", "status": "pending"},
        ]
        second = [
            {"content": "Find the invoices", "status": "completed"},
            {"content": "Summarize overdue totals", "status": "in_progress"},
        ]
        events = [
            {
                "type": "tool_call",
                "who": "main",
                "id": "p1",
                "name": "write_todos",
                "args": {"todos": first},
            },
            {
                "type": "tool_result",
                "who": "main",
                "id": "p1",
                "name": "write_todos",
                "result": "updated",
                "error": None,
            },
            {
                "type": "tool_call",
                "who": "main",
                "id": "p2",
                "name": "write_todos",
                "args": {"todos": second},
            },
            {
                "type": "tool_result",
                "who": "main",
                "id": "p2",
                "name": "write_todos",
                "result": "updated",
                "error": None,
            },
        ]
        with patch.object(chat, "run_turn", replay(events)):
            body = "".join([chunk async for chunk in ai_sdk_frames("plan", "do it")])
        parts = [
            json.loads(line[len("data: ") :])
            for line in body.split("\n\n")
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        plans = [part for part in parts if part["type"] == "data-plan"]
        self.assertEqual(
            [part["data"]["todos"] for part in plans],
            [first, second, second],
        )
        self.assertEqual(
            [part["data"]["lifecycle"] for part in plans],
            ["running", "running", "finished"],
        )
        self.assertEqual(plans[0]["id"], plans[1]["id"])
        self.assertFalse(any(part["type"].startswith("tool-") for part in parts))

    async def test_bad_plan_arguments_do_not_break_the_stream(self):
        from deep_agent_app.views import ai_sdk_frames

        events = [
            {
                "type": "tool_call",
                "who": "main",
                "id": "p1",
                "name": "write_todos",
                "args": "bad",
            },
        ]
        with patch.object(chat, "run_turn", replay(events)):
            body = "".join([chunk async for chunk in ai_sdk_frames("plan", "do it")])

        self.assertIn('"type": "data-plan"', body)
        self.assertIn('"todos": []', body)
        self.assertIn("data: [DONE]", body)

    def test_checkpoint_history_keeps_only_the_latest_plan(self):
        first = chat_history.plan_part(
            {"args": {"todos": [{"content": "Find invoices", "status": "in_progress"}]}}
        )
        latest = chat_history.plan_part(
            {"args": {"todos": [{"content": "Find invoices", "status": "completed"}]}}
        )
        parts = [first, {"type": "text", "text": "Working"}]
        chat_history.merge_assistant_parts(parts, [latest])
        plans = [part for part in parts if part["type"] == "data-plan"]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["data"]["todos"][0]["status"], "completed")
        self.assertEqual(plans[0]["data"]["lifecycle"], "finished")

    async def test_resume_answers_an_interrupt(self):
        await self.login()
        seen = []

        async def run_turn(
            thread_id,
            text=None,
            workspace_id=None,
            resume=None,
            options=None,
            message_id=None,
            checkpoint_config=None,
        ):
            seen.append((thread_id, text, resume))
            yield {"type": "token", "who": "main", "text": "ok"}

        with patch.object(chat, "run_turn", run_turn):
            # The UI echoes the answer as a message and sends the value as resume.
            await read(
                await self.post_chat(
                    {
                        "thread_id": "r1",
                        "message": "Approve",
                        "resume": {"decisions": [{"type": "approve"}]},
                    }
                )
            )
            # Or sends resume alone.
            await read(await self.post_chat({"thread_id": "r1", "resume": "A"}))
        self.assertEqual(
            seen,
            [("r1", "Approve", {"decisions": [{"type": "approve"}]}), ("r1", "A", "A")][
                :1
            ]
            + [("r1", "", "A")],
        )

    async def test_bad_requests(self):
        await self.login()
        self.assertEqual(
            (
                await self.async_client.post(
                    "/api/chat/", "nope", content_type="application/json"
                )
            ).status_code,
            400,
        )
        self.assertEqual((await self.post_chat({"thread_id": "t1"})).status_code, 400)
        self.assertEqual((await self.post_chat({"message": "hi"})).status_code, 400)

    async def test_cannot_use_another_users_thread(self):
        await Thread.objects.acreate(id="theirs", user=self.other)
        await self.login()
        self.assertEqual(
            (
                await self.post_chat({"thread_id": "theirs", "message": "hi"})
            ).status_code,
            404,
        )
        self.assertEqual(
            (await self.async_client.get("/api/threads/theirs/")).status_code, 404
        )
        self.assertEqual(
            (await self.async_client.get("/api/threads/theirs/messages/")).status_code,
            404,
        )

    async def test_second_turn_on_busy_thread_is_rejected(self):
        await self.login()
        self.assertTrue(chat.try_start_turn("busy"))
        try:
            response = await self.post_chat({"thread_id": "busy", "message": "again"})
        finally:
            chat.finish_turn("busy")
        self.assertEqual(response.status_code, 409)

    async def test_capacity_rejection_is_retryable_and_creates_no_thread(self):
        await self.login()
        with patch.object(
            chat,
            "reserve_chat_turn",
            side_effect=RuntimeCapacityError("retry shortly"),
        ):
            response = await self.post_chat(
                {"thread_id": "at-capacity", "message": "hello"}
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "5")
        self.assertFalse(await Thread.objects.filter(id="at-capacity").aexists())

    async def test_turn_failure_becomes_error_frame(self):
        await self.login()
        with patch.object(chat, "run_turn", failing):
            body, parts = await read(
                await self.post_chat({"thread_id": "t2", "message": "hi"})
            )
        self.assertEqual(
            [p["type"] for p in parts],
            ["start", "text-start", "text-delta", "text-end", "error"],
        )
        self.assertEqual(
            parts[-1]["errorText"],
            "The assistant could not complete this request. Please try again.",
        )
        self.assertFalse(chat.is_turn_running("t2"))

    async def test_usage_is_sent_as_a_data_part(self):
        from deep_agent_app.views import ai_sdk_frames

        usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "calls": 2,
            "unreported_calls": 0,
            "models": [],
        }
        with patch.object(
            chat, "run_turn", replay([{"type": "usage", "usage": usage}])
        ):
            body = "".join([chunk async for chunk in ai_sdk_frames("tokens", "hi")])
        parts = [
            json.loads(line[len("data: ") :])
            for line in body.split("\n\n")
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        self.assertEqual(
            [part["type"] for part in parts], ["start", "data-usage", "finish"]
        )
        self.assertEqual(parts[1]["data"], usage)

    async def test_thread_list_and_create(self):
        await self.login()
        created = await self.async_client.post(
            "/api/threads/",
            json.dumps({"title": "Q3 stock"}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        await Thread.objects.acreate(user=self.other, title="not mine")

        listed = json.loads((await self.async_client.get("/api/threads/")).content)[
            "threads"
        ]
        self.assertEqual([t["title"] for t in listed], ["Q3 stock"])
        self.assertEqual(listed[0]["id"], json.loads(created.content)["id"])

    async def test_messages_endpoint_returns_ui_messages(self):
        await self.login()
        thread = await Thread.objects.acreate(user=self.user, title="t")
        transcript = [
            {"id": "h1", "role": "user", "parts": [{"type": "text", "text": "hi"}]},
            {
                "id": "a1",
                "role": "assistant",
                "parts": [{"type": "text", "text": "hello"}],
            },
        ]

        async def history(thread_id):
            return transcript

        with patch.object(chat, "get_history", history):
            data = json.loads(
                (
                    await self.async_client.get(f"/api/threads/{thread.id}/messages/")
                ).content
            )
        self.assertEqual(data["thread"]["id"], thread.id)
        self.assertEqual(data["messages"], transcript)

    async def test_delete_thread(self):
        await self.login()
        thread = await Thread.objects.acreate(user=self.user)
        workspace = await UserWorkspace.objects.acreate(user=self.user)
        deleted = []

        async def delete_thread(thread_id):
            deleted.append(thread_id)

        with (
            patch.object(chat, "delete_checkpoint_history", delete_thread),
            patch(
                "deep_agent_app.views.delete_conversation_workspace"
            ) as delete_workspace,
        ):
            response = await self.async_client.delete(f"/api/threads/{thread.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(deleted, [thread.id])
        delete_workspace.assert_called_once_with(workspace.id.hex, thread.id)
        self.assertFalse(await Thread.objects.filter(id=thread.id).aexists())

    async def test_config(self):
        from deep_agent_app.utilities.constants import CONNECTED_SYSTEM_ENABLED

        await self.login()
        data = json.loads((await self.async_client.get("/api/config/")).content)
        self.assertEqual(data["user"], {"username": "mona"})
        model_ids = [m["id"] for m in data["models"]]
        self.assertEqual(
            (data["default_model"], data["models"][0]),
            ("auto", {"id": "auto", "label": "Auto"}),
        )
        self.assertIn("ollama", model_ids)
        expected_agents = (
            ["general", "connected"] if CONNECTED_SYSTEM_ENABLED else ["general"]
        )
        self.assertEqual([a["id"] for a in data["agents"]], expected_agents)
        self.assertIn("web_search", [t["id"] for t in data["tools"]])
        self.assertNotIn("connected", [t["id"] for t in data["tools"]])
        # Slash commands come from data/commands.json …
        commands = {c["id"]: c for c in data["commands"]}
        self.assertEqual(commands["brief"]["placement"], "bar")
        self.assertEqual(commands["risk-review"]["placement"], "hero")
        self.assertTrue(all(c["prompt"] and c["label"] for c in commands.values()))
        # … and @-mentions from data/mentions.json plus the skills on disk.
        by_kind = {}
        for m in data["mentions"]:
            by_kind.setdefault(m["kind"], []).append(m["id"])
        self.assertEqual(
            by_kind.get("agent", []), ["connected"] if CONNECTED_SYSTEM_ENABLED else []
        )
        self.assertIn("internet_search", by_kind["tool"])
        self.assertIn("executive-brief", by_kind["skill"])
        brief = next(m for m in data["mentions"] if m["id"] == "executive-brief")
        self.assertEqual(brief["path"], "/skills/general/executive-brief/SKILL.md")
        self.assertTrue(brief["description"].startswith("Turn company information"))

    async def test_chat_page(self):
        response = await self.async_client.get("/chat/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts/login/?next=/chat/")
        response = await self.async_client.get("/chat/" + "b" * 32)
        self.assertEqual(
            response["Location"], "/accounts/login/?next=/chat/" + "b" * 32
        )
        self.assertEqual(
            (await self.async_client.get("/accounts/login/")).status_code, 200
        )
        await self.login()
        response = await self.async_client.get("/chat/")
        self.assertEqual(response.status_code, 200)
        # Hashed names from Vite's manifest, so a fix is never stuck behind a cached bundle.
        entry = json.loads(Path(finders.find("chat/manifest.json")).read_text())[
            "src/main.tsx"
        ]
        self.assertRegex(entry["file"], r"^index-[\w-]+\.js$")
        self.assertIn(f"/static/chat/{entry['file']}".encode(), response.content)
        for css in entry["css"]:
            self.assertIn(f"/static/chat/{css}".encode(), response.content)
        self.assertIn("csrftoken", response.cookies)
        # A thread's own address is the same page; the app reads the id from the URL.
        self.assertEqual(
            (await self.async_client.get("/chat/" + "a" * 32)).status_code, 200
        )
        self.assertEqual(
            (await self.async_client.get("/chat/" + "a" * 32 + "/")).status_code, 200
        )
        self.assertEqual(
            (await self.async_client.get("/chat/not-a-thread")).status_code, 404
        )


class HealthProbeTests(TestCase):
    def test_liveness_is_small_and_public(self):
        response = self.client.get("/health/live/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_checks_required_dependencies(self):
        response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

        with patch("deep_agent_app.health.PROVIDERS", {}):
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})


class CheckpointBranchTests(SimpleTestCase):
    async def test_branch_point_follows_only_the_active_parent_chain(self):
        u1 = HumanMessage(content="first", id="u1")
        u2 = HumanMessage(content="second", id="u2")
        configs = {
            name: {"configurable": {"thread_id": "branch", "checkpoint_id": name}}
            for name in ("empty", "u1", "answer1", "u2", "answer2")
        }
        states = {}

        def snapshot(name, messages, parent=None):
            state = SimpleNamespace(
                values={"messages": messages},
                config=configs[name],
                parent_config=configs[parent] if parent else None,
            )
            states[name] = state
            return state

        snapshot("empty", [])
        snapshot("u1", [u1], "empty")
        snapshot("answer1", [u1, AIMessage(content="one", id="a1")], "u1")
        snapshot("u2", [u1, AIMessage(content="one", id="a1"), u2], "answer1")
        latest = snapshot(
            "answer2",
            [
                u1,
                AIMessage(content="one", id="a1"),
                u2,
                AIMessage(content="two", id="a2"),
            ],
            "u2",
        )

        class Graph:
            async def aget_state(self, requested):
                checkpoint_id = requested["configurable"].get("checkpoint_id")
                return states[checkpoint_id] if checkpoint_id else latest

        with patch.object(agent_runtime, "get_agent", return_value=Graph()):
            checkpoint, text = await chat.branch_before_message("branch", "u2")

        self.assertEqual(checkpoint, configs["answer1"])
        self.assertEqual(text, "second")

    async def test_delete_forks_checkpoint_without_running_ai(self):
        checkpoint = {
            "configurable": {"thread_id": "branch", "checkpoint_id": "before-u2"}
        }
        calls = []

        class Graph:
            async def aupdate_state(self, config, values, as_node=None):
                calls.append((config, values, as_node))

        async def branch_before_message(thread_id, message_id):
            return checkpoint, "second"

        async def history(thread_id):
            return [{"id": "u1", "role": "user", "parts": []}]

        with (
            patch.object(agent_runtime, "get_agent", return_value=Graph()),
            patch(
                "deep_agent_app.chat.history.branch_before_message",
                branch_before_message,
            ),
            patch("deep_agent_app.chat.history.get_history", history),
        ):
            transcript = await chat.delete_message("branch", "u2")

        self.assertEqual(calls, [(checkpoint, {}, "__copy__")])
        self.assertEqual(transcript[0]["id"], "u1")

    async def test_delete_removes_selected_message_with_real_checkpoints(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, MessagesState, StateGraph

        replies = iter(("a1", "a2"))

        async def answer(state):
            message_id = next(replies)
            return {"messages": [AIMessage(content=message_id, id=message_id)]}

        builder = StateGraph(MessagesState)
        builder.add_node("answer", answer)
        builder.add_edge(START, "answer")
        builder.add_edge("answer", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        run_config = chat_history.graph_config("real-delete")
        await graph.ainvoke(
            {"messages": [HumanMessage(content="first", id="u1")]}, run_config
        )
        await graph.ainvoke(
            {"messages": [HumanMessage(content="second", id="u2")]}, run_config
        )

        with patch.object(agent_runtime, "get_agent", return_value=graph):
            await chat.delete_message("real-delete", "u2")

        state = await graph.aget_state(run_config)
        self.assertEqual(
            [(message.type, message.id) for message in state.values["messages"]],
            [("human", "u1"), ("ai", "a1")],
        )


class MessageTimestampTests(SimpleTestCase):
    def test_assistant_timestamp_is_checkpointed_and_exposed_to_the_ui(self):
        from langchain.agents.middleware import ModelResponse
        from deep_agent_app.agent import timestamp_model_response

        response = timestamp_model_response(
            ModelResponse(result=[AIMessage(content="answer", id="a1")])
        )
        message = response.result[0]
        created_at = message.response_metadata["created_at"]

        self.assertTrue(created_at.endswith("+00:00"))
        self.assertEqual(
            chat_history.ui_message(
                message, "assistant", [{"type": "text", "text": "answer"}]
            )["metadata"],
            {"created_at": created_at},
        )


class SlashCommandTests(SimpleTestCase):
    def test_command_resolves_from_structured_id_or_visible_text(self):
        from deep_agent_app.utilities import composer

        self.assertEqual(
            composer.resolve_command("report")["prompt"],
            "Use present_report to create a workspace report.",
        )
        self.assertEqual(
            composer.resolve_command(None, "/report sales this month")["id"],
            "report",
        )
        self.assertIsNone(composer.resolve_command(None, "/not-configured hello"))
        with self.assertRaisesRegex(ValueError, "unknown command"):
            composer.resolve_command("not-configured")

    def test_command_meaning_is_added_without_mutating_the_base_prompt(self):
        from deep_agent_app.agent import TurnContext, command_system_message
        from langchain_core.messages import SystemMessage

        base = SystemMessage(content="Base ERP instructions")
        selected = command_system_message(
            base,
            TurnContext(
                command_id="report",
                command_prompt="Use present_report to create a workspace report.",
            ),
        )

        self.assertEqual(base.content, "Base ERP instructions")
        self.assertIn("Base ERP instructions", selected.content)
        self.assertIn("/report", selected.content)
        self.assertIn("present_report", selected.content)


class InterruptTests(ApiTestCase):
    """The real pump over a scripted model: a turn pauses at interrupt() and
    the next request resumes it. No error frame anywhere — the stream reports
    a paused tool the same way as a failed one, and that must not leak."""

    async def test_question_pauses_and_resumes(self):
        from deep_agent_app.agent import ask_user

        agent = fake_agent(
            [
                tool_call(
                    "ask_user", {"question": "Which?", "options": ["A", "B"]}, "c1"
                ),
                AIMessage(content="You chose A"),
            ],
            [ask_user],
        )
        await self.login()
        with patch.object(agent_runtime, "get_agent", AsyncMock(return_value=agent)):
            body, parts = await read(
                await self.post_chat({"thread_id": "q1", "message": "help me"})
            )
            self.assertEqual(
                [p["type"] for p in parts],
                [
                    "start",
                    "tool-input-available",
                    "data-usage",
                    "data-interrupt",
                    "finish",
                ],
            )
            interrupt = next(part for part in parts if part["type"] == "data-interrupt")
            self.assertEqual(
                interrupt["data"]["value"],
                {
                    "kind": "questions",
                    "questions": [
                        {"id": "q1", "question": "Which?", "options": ["A", "B"]}
                    ],
                },
            )
            self.assertEqual(interrupt["id"], interrupt["data"]["id"])
            self.assertFalse(chat.is_turn_running("q1"))

            # A reload mid-question still shows the question, on the paused tool call.
            last = (await self.messages("q1"))[-1]
            self.assertEqual(last["role"], "assistant")
            self.assertEqual(
                [p["type"] for p in last["parts"]], ["tool-ask_user", "data-interrupt"]
            )
            self.assertEqual(last["parts"][0]["state"], "input-available")
            self.assertEqual(
                last["parts"][1]["data"]["value"]["questions"][0]["question"], "Which?"
            )

            body, parts = await read(
                await self.post_chat({"thread_id": "q1", "message": "A", "resume": "A"})
            )
            self.assertEqual(
                [p["type"] for p in parts],
                [
                    "start",
                    "tool-input-available",
                    "tool-output-available",
                    "text-start",
                    "text-delta",
                    "text-end",
                    "data-usage",
                    "finish",
                ],
            )
            self.assertEqual(
                parts[2],
                {
                    "type": "tool-output-available",
                    "toolCallId": "c1",
                    "output": "Q: Which?\nA: A",
                },
            )
            self.assertEqual(parts[4]["delta"], "You chose A")

            messages = await self.messages("q1")
            self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
            self.assertEqual(
                messages[0]["parts"], [{"type": "text", "text": "help me"}]
            )
            self.assertEqual(
                messages[1]["parts"],
                [
                    {
                        "type": "tool-ask_user",
                        "toolCallId": "c1",
                        "input": {"question": "Which?", "options": ["A", "B"]},
                        "state": "output-available",
                        "output": "Q: Which?\nA: A",
                    },
                    {"type": "text", "text": "You chose A"},
                ],
            )

    async def test_question_batch_resumes_once_with_labeled_answers(self):
        from deep_agent_app.agent import ask_user

        questions = [
            {"question": "What is your favorite color?", "options": ["Blue", "Green"]},
            {
                "question": "How often should the report run?",
                "options": ["Daily", "Weekly"],
            },
        ]
        agent = fake_agent(
            [
                tool_call("ask_user", {"questions": questions}, "batch-call"),
                AIMessage(content="The report will be blue and weekly."),
            ],
            [ask_user],
        )
        await self.login()
        with patch.object(agent_runtime, "get_agent", AsyncMock(return_value=agent)):
            _, paused = await read(
                await self.post_chat(
                    {"thread_id": "batch-q", "message": "Configure my report"}
                )
            )
            interrupt_part = next(
                part for part in paused if part["type"] == "data-interrupt"
            )
            interrupt_id = interrupt_part["id"]
            self.assertEqual(
                interrupt_part["data"]["value"],
                {
                    "kind": "questions",
                    "questions": [
                        {"id": "q1", **questions[0]},
                        {"id": "q2", **questions[1]},
                    ],
                },
            )

            _, resumed = await read(
                await self.post_chat(
                    {
                        "thread_id": "batch-q",
                        "message": (
                            "Q: What is your favorite color?\nA: Blue\n\n"
                            "Q: How often should the report run?\nA: Weekly"
                        ),
                        "resume": {interrupt_id: {"q1": "Blue", "q2": "Weekly"}},
                    }
                )
            )
            output = next(
                part for part in resumed if part["type"] == "tool-output-available"
            )
            self.assertEqual(
                output["output"],
                "Q: What is your favorite color?\nA: Blue\n\n"
                "Q: How often should the report run?\nA: Weekly",
            )
            self.assertEqual(
                next(part for part in resumed if part["type"] == "text-delta")["delta"],
                "The report will be blue and weekly.",
            )

    def test_multiple_pending_questions_can_resume_one_at_a_time_by_id(self):
        """A single answer map is unambiguous even with parallel interrupts."""
        import operator
        from typing import Annotated, TypedDict

        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import Command, interrupt

        class State(TypedDict):
            answers: Annotated[list[str], operator.add]

        def question(label):
            def ask(state):
                answer = interrupt(label)
                return {"answers": [f"{label}:{answer}"]}

            return ask

        graph = (
            StateGraph(State)
            .add_node("first", question("First"))
            .add_node("second", question("Second"))
            .add_edge(START, "first")
            .add_edge(START, "second")
            .add_edge("first", END)
            .add_edge("second", END)
            .compile(checkpointer=InMemorySaver())
        )
        config = {"configurable": {"thread_id": "parallel-questions"}}

        paused = graph.invoke({"answers": []}, config)
        first, second = paused["__interrupt__"]
        still_paused = graph.invoke(Command(resume={first.id: "A"}), config)
        self.assertEqual(still_paused["answers"], [f"{first.value}:A"])
        self.assertEqual([i.id for i in still_paused["__interrupt__"]], [second.id])

        completed = graph.invoke(Command(resume={second.id: "B"}), config)
        self.assertCountEqual(
            completed["answers"], [f"{first.value}:A", f"{second.value}:B"]
        )

    async def test_tool_approval_pauses_and_resumes(self):
        agent = fake_agent(
            [tool_call("dangerous", {"x": 1}, "c2"), AIMessage(content="done")],
            [dangerous],
            interrupt_on={"dangerous": True},
        )
        await self.login()
        with patch.object(agent_runtime, "get_agent", AsyncMock(return_value=agent)):
            body, parts = await read(
                await self.post_chat({"thread_id": "a1", "message": "go"})
            )
            self.assertEqual(
                [p["type"] for p in parts],
                ["start", "data-usage", "data-interrupt", "finish"],
            )
            interrupt = next(part for part in parts if part["type"] == "data-interrupt")
            request = interrupt["data"]["value"]["action_requests"][0]
            self.assertEqual(
                (request["name"], request["args"]), ("dangerous", {"x": 1})
            )
            self.assertIn(
                "approve",
                interrupt["data"]["value"]["review_configs"][0]["allowed_decisions"],
            )

            body, parts = await read(
                await self.post_chat(
                    {"thread_id": "a1", "resume": {"decisions": [{"type": "approve"}]}}
                )
            )
            self.assertEqual(
                [p["type"] for p in parts],
                [
                    "start",
                    "tool-input-available",
                    "tool-output-available",
                    "text-start",
                    "text-delta",
                    "text-end",
                    "data-usage",
                    "finish",
                ],
            )
            self.assertEqual(parts[2]["output"], "did 1")

    async def test_question_inside_a_subagent(self):
        from deep_agent_app.agent import ask_user

        erp = {
            "name": "erp",
            "description": "erp",
            "system_prompt": "x",
            "tools": [ask_user],
            "model": FakeToolModel(
                responses=[
                    tool_call(
                        "ask_user", {"question": "Customer?", "options": ["Acme"]}, "c3"
                    ),
                    AIMessage(content="sub done"),
                ]
            ),
        }
        agent = fake_agent(
            [
                tool_call(
                    "task", {"description": "look it up", "subagent_type": "erp"}, "c4"
                ),
                AIMessage(content="main done"),
            ],
            [],
            subagents=[erp],
        )
        await self.login()
        with patch.object(agent_runtime, "get_agent", AsyncMock(return_value=agent)):
            body, parts = await read(
                await self.post_chat({"thread_id": "s1", "message": "hi"})
            )
            types = [p["type"] for p in parts]
            self.assertNotIn("error", types)
            self.assertNotIn("tool-output-error", types)
            self.assertEqual(types[-2:], ["data-interrupt", "finish"])
            self.assertEqual(
                [p["data"]["status"] for p in parts if p["type"] == "data-subagent"],
                ["started", "interrupted"],
            )
            self.assertEqual(
                parts[-2]["data"]["value"]["questions"][0]["question"],
                "Customer?",
            )

            body, parts = await read(
                await self.post_chat({"thread_id": "s1", "resume": "Acme"})
            )
            types = [p["type"] for p in parts]
            self.assertNotIn("error", types)
            self.assertEqual(types[-1], "finish")
            self.assertEqual(
                "".join(p["delta"] for p in parts if p["type"] == "text-delta"),
                "main done",
            )
            task = next(
                p
                for p in parts
                if p["type"] == "tool-output-available" and p["toolCallId"] == "c4"
            )
            self.assertEqual(task["output"], "sub done")


class EventLoopGuardTests(TestCase):
    """Under WSGI (manage.py runserver) each request gets its own event loop
    and the loop-bound singletons break on the second turn. The guard turns
    the cryptic langgraph error into one that names the fix."""

    async def test_wrong_event_loop_is_explained(self):
        from deep_agent_app.runtime import AgentRuntime

        runtime = AgentRuntime()
        other = asyncio.new_event_loop()
        try:
            runtime._loop = other
            with self.assertRaisesRegex(RuntimeError, "uvicorn"):
                await runtime.get_saver()
            with self.assertRaisesRegex(RuntimeError, "uvicorn"):
                await runtime.get_agent()
        finally:
            other.close()

    async def test_same_loop_passes(self):
        from deep_agent_app.runtime import AgentRuntime

        runtime = AgentRuntime()
        runtime._graph = object()
        self.assertIsNotNone(await runtime.get_agent())


class TokenUsageTests(TestCase):
    def test_all_calls_and_usage_details_are_aggregated(self):
        usage = chat_usage.token_usage(
            [
                {
                    "provider": "openai",
                    "model": "model-a",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                        "input_token_details": {"cache_read": 4},
                    },
                },
                {
                    "provider": "openai",
                    "model": "model-a",
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 2,
                        "total_tokens": 22,
                        "input_token_details": {"cache_read": 6},
                        "output_token_details": {"reasoning": 1},
                    },
                },
                # A provider response without usage is visible, never counted as zero.
                {"provider": "openai", "model": "model-b", "usage": None},
            ]
        )

        self.assertEqual(
            (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]),
            (30, 7, 37),
        )
        self.assertEqual(usage["input_token_details"]["cache_read"], 10)
        self.assertEqual(usage["output_token_details"]["reasoning"], 1)
        self.assertEqual((usage["calls"], usage["unreported_calls"]), (3, 1))
        by_model = {item["model"]: item for item in usage["models"]}
        self.assertEqual(
            (by_model["model-a"]["calls"], by_model["model-a"]["total_tokens"]), (2, 37)
        )
        self.assertEqual(
            (by_model["model-b"]["calls"], by_model["model-b"]["unreported_calls"]),
            (1, 1),
        )

    def test_selected_provider_id_is_kept_for_billing(self):
        usage = chat_usage.token_usage(
            [
                {
                    "provider_id": "groq",
                    "provider": "openai",
                    "model": "gpt-oss-120b",
                    "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
                }
            ]
        )

        self.assertEqual(usage["models"][0]["provider"], "groq")
        self.assertEqual(usage["models"][0]["model_provider"], "openai")

    async def test_completed_message_emits_provider_usage(self):
        from langchain_core.language_models.chat_model_stream import (
            AsyncChatModelStream,
        )

        message = AsyncChatModelStream(message_id="m1")
        message.dispatch(
            {
                "event": "message-start",
                "id": "m1",
                "role": "assistant",
                "metadata": {"provider": "openai", "model": "model-a"},
            }
        )
        message.dispatch(
            {
                "event": "message-finish",
                "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            }
        )

        async def messages():
            yield message

        events = []
        await chat_streaming.pump_messages(messages(), "erp", events.append)
        self.assertEqual(
            [event["type"] for event in events], ["_usage_start", "_usage_end"]
        )
        self.assertEqual(events[-1]["who"], "erp")
        self.assertEqual(events[-1]["model"], "model-a")
        self.assertEqual(events[-1]["provider"], "openai")
        self.assertEqual(events[-1]["usage"]["total_tokens"], 15)


class ModelSelectionTests(TestCase):
    def test_textual_ask_user_markup_is_recovered_as_a_tool_call(self):
        from langchain.agents.middleware import ModelResponse

        from deep_agent_app.agent import repair_ask_user_response

        leaked = """<ask_user>
          <question>How should I determine your top 10 items?</question>
          <options>
            <item>By total revenue (sales amount)]<]minimax[>[</item>]<]minimax[>[
            <item>By quantity sold]<]minimax[>[</item>]<]minimax[>[
            <item>By number of invoices (frequency)]<]minimax[>[</item>
          </options>
        </ask_user>"""
        with self.assertLogs("deep_agent_app.agent", level="WARNING"):
            response = repair_ask_user_response(
                ModelResponse(result=[AIMessage(content=leaked)])
            )

        message = response.result[0]
        self.assertEqual(message.content, "")
        self.assertEqual(len(message.tool_calls), 1)
        self.assertEqual(message.tool_calls[0]["name"], "ask_user")
        self.assertEqual(
            message.tool_calls[0]["args"],
            {
                "question": "How should I determine your top 10 items?",
                "options": [
                    "By total revenue (sales amount)",
                    "By quantity sold",
                    "By number of invoices (frequency)",
                ],
            },
        )

    async def test_textual_ask_user_markup_is_never_streamed_as_chat_text(self):
        async def chunks():
            for chunk in (
                "<ask_",
                "user><question>Which customer?</question>",
                "<options><item>Acme</item></options></ask_user>",
            ):
                yield chunk

        events = []
        await chat_streaming.pump_deltas(chunks(), "main", "token", events.append)
        self.assertEqual(events, [])

    async def test_normal_text_still_streams_when_marker_prefix_is_split(self):
        async def chunks():
            for chunk in ("Use <ask_", "another thing, then continue."):
                yield chunk

        events = []
        await chat_streaming.pump_deltas(chunks(), "main", "token", events.append)
        self.assertEqual(
            "".join(event["text"] for event in events),
            "Use <ask_another thing, then continue.",
        )

    def test_missing_model_uses_auto(self):
        from deep_agent_app.agent import AUTO_MODEL, validate_model_choice

        self.assertEqual(validate_model_choice(None), AUTO_MODEL)
        self.assertEqual(validate_model_choice(""), AUTO_MODEL)

    def test_provider_registry_excludes_incomplete_and_reserved_entries(self):
        from deep_agent_app.agent import provider_registry

        providers = provider_registry(
            {
                "good": {"model": "openai/model-a", "api_key": "key"},
                "native": {
                    "model_provider": "google_genai",
                    "model": "gemini-2.5-flash",
                    "api_key": "key",
                },
                "no-key": {"model": "openai/model-b"},
                "no-model": {"api_key": "key"},
                "bad-provider": {
                    "model_provider": 1,
                    "model": "model-d",
                    "api_key": "key",
                },
                "bad-family": {
                    "provider_family": "",
                    "model": "model-e",
                    "api_key": "key",
                },
                "bad-url": {
                    "base_url": "localhost:9000",
                    "model": "model-f",
                    "api_key": "key",
                },
                "bad-timeout": {"timeout": -1, "model": "model-g", "api_key": "key"},
                "bad-temperature": {
                    "temperature": "cold",
                    "model": "model-j",
                    "api_key": "key",
                },
                "bad-stream-usage": {
                    "stream_usage": "yes",
                    "model": "model-h",
                    "api_key": "key",
                },
                "bad-thinking": {
                    "thinking": "high",
                    "model": "model-i",
                    "api_key": "key",
                },
                "auto": {"model": "openai/model-c", "api_key": "key"},
            }
        )
        self.assertEqual(list(providers), ["good", "native"])
        with self.assertRaises(TypeError):
            providers["good"]["model"] = "changed"

    def test_provider_family_prefers_configuration_then_id_then_hostname(self):
        from types import MappingProxyType

        from deep_agent_app.agent.llm.provider_profiles import provider_family

        providers = MappingProxyType(
            {
                "alias": MappingProxyType(
                    {
                        "model": "model-a",
                        "api_key": "key",
                        "base_url": "https://company-proxy.example/v1",
                        "provider_family": "groq_gateway",
                    }
                ),
                "openrouter": MappingProxyType(
                    {
                        "model": "model-b",
                        "api_key": "key",
                        "base_url": "https://company-proxy.example/v1",
                    }
                ),
                "legacy": MappingProxyType(
                    {
                        "model": "model-c",
                        "api_key": "key",
                        "base_url": "https://api.groq.com/openai/v1",
                    }
                ),
                "gemini": MappingProxyType(
                    {
                        "model_provider": "google_genai",
                        "model": "model-d",
                        "api_key": "key",
                        "base_url": "https://api.groq.com/openai/v1",
                    }
                ),
            }
        )
        with patch.object(model_registry, "PROVIDERS", providers):
            self.assertEqual(provider_family("alias"), "groq_gateway")
            self.assertEqual(provider_family("openrouter"), "openrouter_gateway")
            self.assertEqual(provider_family("legacy"), "groq_gateway")
            self.assertEqual(provider_family("gemini"), "google_genai")

    def test_auto_and_explicit_default_share_the_cached_client(self):
        from deep_agent_app.agent import (
            AUTO_MODEL,
            DEFAULT_PROVIDER,
            build_llm,
            resolve_provider,
        )

        self.assertEqual(resolve_provider(AUTO_MODEL), DEFAULT_PROVIDER)
        self.assertIs(build_llm(AUTO_MODEL, 0.7), build_llm(DEFAULT_PROVIDER, 0.7))

    def test_thinking_effort_normalizes_legacy_booleans(self):
        from deep_agent_app.agent import validate_thinking_effort

        self.assertEqual(validate_thinking_effort(None), "instant")
        self.assertEqual(validate_thinking_effort(False), "instant")
        self.assertEqual(validate_thinking_effort(True), "high")
        for effort in ("instant", "medium", "high", "max"):
            self.assertEqual(validate_thinking_effort(effort), effort)
        with self.assertRaisesMessage(
            ValueError, "thinking must be instant, medium, high, or max"
        ):
            validate_thinking_effort("turbo")

    def test_plan_mode_requires_a_boolean(self):
        from deep_agent_app.agent import validate_plan_mode

        self.assertFalse(validate_plan_mode(None))
        self.assertFalse(validate_plan_mode(False))
        self.assertTrue(validate_plan_mode(True))
        with self.assertRaisesMessage(ValueError, "plan must be true or false"):
            validate_plan_mode("true")

    async def test_plan_middleware_is_run_scoped(self):
        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app.agent import PlanModeMiddleware, TurnContext

        model = FakeToolModel(responses=[AIMessage(content="ok")])
        middleware = PlanModeMiddleware()
        plan_tool = middleware.tools[0]
        seen = {}

        async def handler(request):
            context = request.runtime.context
            seen[context.plan] = {
                "tools": [getattr(tool, "name", None) for tool in request.tools],
                "prompt": request.system_message.content
                if request.system_message
                else "",
            }
            return ModelResponse(result=[AIMessage(content="ok")])

        def request(plan):
            return ModelRequest(
                model=model,
                messages=[],
                tools=[plan_tool],
                runtime=Runtime(context=TurnContext(plan=plan)),
            )

        await asyncio.gather(
            middleware.awrap_model_call(request(False), handler),
            middleware.awrap_model_call(request(True), handler),
        )
        self.assertEqual(seen[False]["tools"], [])
        self.assertNotIn("Plan mode", seen[False]["prompt"])
        self.assertEqual(seen[True]["tools"], ["write_todos"])
        self.assertIn("Plan mode", str(seen[True]["prompt"]))

    async def test_plan_tool_returns_a_langgraph_state_update(self):
        from types import SimpleNamespace

        from deep_agent_app.agent import PlanModeMiddleware

        todos = [
            {"content": "Inspect invoices", "status": "completed"},
            {"content": "Prepare summary", "status": "in_progress"},
        ]
        command = (
            await PlanModeMiddleware()
            .tools[0]
            .coroutine(
                runtime=SimpleNamespace(tool_call_id="plan-1"),
                todos=todos,
            )
        )
        self.assertEqual(command.update["todos"], todos)
        self.assertEqual(command.update["messages"][0].tool_call_id, "plan-1")

    def test_native_google_provider_uses_google_integration(self):
        from types import MappingProxyType

        providers = MappingProxyType(
            {
                "gemini": {
                    "model_provider": "google_genai",
                    "model": "gemini-3.6-flash",
                    "api_key": "test-key",
                }
            }
        )
        llm_clients._build_llm.cache_clear()
        reasoning_module.thinking_model_settings.cache_clear()
        try:
            with patch.object(model_registry, "PROVIDERS", providers):
                model = llm_clients.build_llm("gemini", 0.2)
                thinking = dict(reasoning_module.thinking_model_settings("gemini"))
        finally:
            llm_clients._build_llm.cache_clear()
            reasoning_module.thinking_model_settings.cache_clear()

        self.assertEqual(type(model).__name__, "ChatGoogleGenerativeAI")
        self.assertEqual(model.model, "gemini-3.6-flash")
        self.assertEqual(model.temperature, 0.2)
        self.assertEqual(
            thinking,
            {"thinking_level": "high", "include_thoughts": True},
        )

    def test_thinking_effort_uses_gateway_specific_parameters(self):
        from types import MappingProxyType

        providers = MappingProxyType(
            {
                "ollama": MappingProxyType(
                    {
                        "model": "thinking-model",
                        "api_key": "test-key",
                        "base_url": "https://ollama.com/v1",
                        "thinking": True,
                    }
                ),
                "openrouter": MappingProxyType(
                    {
                        "model": "vendor/thinking-model",
                        "api_key": "test-key",
                        "base_url": "https://openrouter.ai/api/v1",
                        "thinking": True,
                    }
                ),
                "groq": MappingProxyType(
                    {
                        "model": "openai/gpt-oss-120b",
                        "api_key": "test-key",
                        "base_url": "https://api.groq.com/openai/v1",
                        "thinking": True,
                    }
                ),
                "nvidia": MappingProxyType(
                    {
                        "model": "deepseek-ai/deepseek-v4-flash-0731",
                        "api_key": "test-key",
                        "base_url": "https://integrate.api.nvidia.com/v1",
                        "thinking": True,
                    }
                ),
            }
        )
        reasoning_module.thinking_model_settings.cache_clear()
        try:
            with patch.object(model_registry, "PROVIDERS", providers):
                ollama = dict(reasoning_module.thinking_model_settings("ollama"))
                openrouter = dict(
                    reasoning_module.thinking_model_settings("openrouter")
                )
                groq = dict(reasoning_module.thinking_model_settings("groq"))
                nvidia = dict(reasoning_module.thinking_model_settings("nvidia"))
        finally:
            reasoning_module.thinking_model_settings.cache_clear()

        self.assertEqual(ollama, {"reasoning_effort": "high"})
        self.assertEqual(
            openrouter,
            {"extra_body": {"reasoning": {"effort": "high", "exclude": False}}},
        )
        self.assertEqual(
            groq,
            {
                "reasoning_effort": "high",
                "extra_body": {"include_reasoning": True},
            },
        )
        self.assertEqual(
            nvidia,
            {
                "extra_body": {
                    "chat_template_kwargs": {
                        "thinking": True,
                        "reasoning_effort": "high",
                    }
                }
            },
        )

    def test_instant_and_max_map_to_each_provider_capability(self):
        from types import MappingProxyType

        providers = MappingProxyType(
            {
                "ollama": MappingProxyType(
                    {
                        "model": "thinking-model",
                        "api_key": "test-key",
                        "base_url": "https://ollama.com/v1",
                        "thinking": True,
                    }
                ),
                "openrouter": MappingProxyType(
                    {
                        "model": "vendor/thinking-model",
                        "api_key": "test-key",
                        "base_url": "https://openrouter.ai/api/v1",
                        "thinking": True,
                    }
                ),
                "groq": MappingProxyType(
                    {
                        "model": "openai/gpt-oss-120b",
                        "api_key": "test-key",
                        "base_url": "https://api.groq.com/openai/v1",
                        "thinking": True,
                    }
                ),
                "nvidia": MappingProxyType(
                    {
                        "model": "deepseek-ai/deepseek-v4-flash-0731",
                        "api_key": "test-key",
                        "base_url": "https://integrate.api.nvidia.com/v1",
                        "thinking": True,
                    }
                ),
                "gemini": MappingProxyType(
                    {
                        "model_provider": "google_genai",
                        "model": "gemini-3.6-flash",
                        "api_key": "test-key",
                    }
                ),
            }
        )
        reasoning_module.thinking_model_settings.cache_clear()
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                self.assertLogs("deep_agent_app.agent", level="INFO"),
            ):
                values = {
                    provider: {
                        effort: dict(
                            reasoning_module.thinking_model_settings(provider, effort)
                        )
                        for effort in ("instant", "medium", "max")
                    }
                    for provider in providers
                }
        finally:
            reasoning_module.thinking_model_settings.cache_clear()

        self.assertEqual(values["ollama"]["instant"], {"reasoning_effort": "none"})
        self.assertEqual(values["ollama"]["max"], {"reasoning_effort": "high"})
        self.assertEqual(
            values["openrouter"]["instant"],
            {"extra_body": {"reasoning": {"effort": "none", "exclude": False}}},
        )
        self.assertEqual(
            values["openrouter"]["max"],
            {"extra_body": {"reasoning": {"effort": "max", "exclude": False}}},
        )
        # This Groq GPT-OSS model always reasons: omit settings for Instant,
        # and map the unsupported Max choice to its strongest High level.
        self.assertEqual(values["groq"]["instant"], {})
        self.assertEqual(
            values["groq"]["max"],
            {
                "reasoning_effort": "high",
                "extra_body": {"include_reasoning": True},
            },
        )
        self.assertEqual(
            values["nvidia"]["instant"],
            {"extra_body": {"chat_template_kwargs": {"thinking": False}}},
        )
        self.assertEqual(
            values["nvidia"]["medium"],
            {"extra_body": {"chat_template_kwargs": {"thinking": True}}},
        )
        self.assertEqual(
            values["nvidia"]["max"],
            {
                "extra_body": {
                    "chat_template_kwargs": {
                        "thinking": True,
                        "reasoning_effort": "max",
                    }
                }
            },
        )
        self.assertEqual(
            values["gemini"]["instant"],
            {"thinking_level": "minimal", "include_thoughts": False},
        )
        self.assertEqual(
            values["gemini"]["max"],
            {"thinking_level": "high", "include_thoughts": True},
        )

    async def test_gateway_reasoning_reaches_langgraph_v3_protocol(self):
        from langchain_core.language_models._compat_bridge import achunks_to_events
        from langchain_core.messages import AIMessageChunk

        from deep_agent_app.agent import GatewayChatOpenAI

        model = GatewayChatOpenAI(
            model="test-model",
            api_key="test-key",
            base_url="https://gateway.invalid/v1",
        )
        raw_chunks = [
            {
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "reasoning": "consider "},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"reasoning_content": "carefully"},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "2"},
                        "finish_reason": "stop",
                    }
                ],
            },
        ]

        async def chunks():
            for raw in raw_chunks:
                yield model._convert_chunk_to_generation_chunk(raw, AIMessageChunk, {})

        events = [event async for event in achunks_to_events(chunks())]
        deltas = [
            event["delta"]
            for event in events
            if event.get("event") == "content-block-delta"
        ]
        self.assertEqual(
            deltas,
            [
                {"type": "reasoning-delta", "reasoning": "consider "},
                {"type": "reasoning-delta", "reasoning": "carefully"},
                {"type": "text-delta", "text": "2"},
            ],
        )

    async def test_config_api_exposes_auto_and_only_usable_providers(self):
        from types import SimpleNamespace

        from deep_agent_app.agent import PROVIDERS
        from deep_agent_app.views import ConfigView

        response = await ConfigView().get(
            SimpleNamespace(user=SimpleNamespace(username="mona"))
        )
        data = json.loads(response.content)
        self.assertEqual(data["default_model"], "auto")
        self.assertEqual(data["models"][0], {"id": "auto", "label": "Auto"})
        self.assertEqual(
            [item["id"] for item in data["models"][1:4]],
            ["flash", "main", "frontier"],
        )
        self.assertEqual([item["id"] for item in data["models"][4:]], list(PROVIDERS))

    async def test_chat_api_rejects_unknown_model_before_database_work(self):
        from django.test import RequestFactory

        from deep_agent_app.views import ChatView

        request = RequestFactory().post(
            "/api/chat/",
            json.dumps(
                {
                    "thread_id": "bad-model",
                    "message": "hi",
                    "options": {"model": "not-configured"},
                }
            ),
            content_type="application/json",
        )
        response = await ChatView().post(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content), {"error": "unknown or unavailable model"}
        )

    async def test_chat_api_rejects_unknown_thinking_effort(self):
        from django.test import RequestFactory

        from deep_agent_app.views import ChatView

        request = RequestFactory().post(
            "/api/chat/",
            json.dumps(
                {
                    "thread_id": "bad-thinking",
                    "message": "hi",
                    "options": {"thinking": "true"},
                }
            ),
            content_type="application/json",
        )
        response = await ChatView().post(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content),
            {"error": "thinking must be instant, medium, high, or max"},
        )

    async def test_chat_api_rejects_non_boolean_plan(self):
        from django.test import RequestFactory

        from deep_agent_app.views import ChatView

        request = RequestFactory().post(
            "/api/chat/",
            json.dumps(
                {
                    "thread_id": "bad-plan",
                    "message": "hi",
                    "options": {"plan": "yes"},
                }
            ),
            content_type="application/json",
        )
        response = await ChatView().post(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.content), {"error": "plan must be true or false"}
        )

    async def test_concurrent_turn_contexts_select_independent_models(self):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app import agent as agent_module

        default = FakeToolModel(responses=[AIMessage(content="default")])
        custom = FakeToolModel(responses=[AIMessage(content="custom")])
        providers = MappingProxyType(
            {
                agent_module.DEFAULT_PROVIDER: MappingProxyType(
                    {"model": "default-model", "api_key": "test-key"}
                ),
                "custom": MappingProxyType(
                    {"model": "custom-model", "api_key": "test-key"}
                ),
            }
        )
        selected = {
            (agent_module.DEFAULT_PROVIDER, 0.0): default,
            ("custom", 0.0): custom,
        }
        seen = []

        async def handler(request):
            await asyncio.sleep(0)
            seen.append(request.model)
            return ModelResponse(result=[AIMessage(content="ok")])

        def request(model):
            return ModelRequest(
                model=default,
                messages=[],
                runtime=Runtime(context=agent_module.TurnContext(model=model)),
            )

        with (
            patch.object(model_registry, "PROVIDERS", providers),
            patch.object(
                llm_clients,
                "_build_llm",
                side_effect=lambda provider, temperature: selected[
                    (provider, temperature)
                ],
            ),
        ):
            await asyncio.gather(
                agent_module.model_selector.awrap_model_call(request("auto"), handler),
                agent_module.model_selector.awrap_model_call(
                    request("custom"), handler
                ),
            )
        self.assertCountEqual(seen, [default, custom])

    async def test_selected_model_is_wired_to_every_agent_call(self):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app import agent as agent_module

        base = FakeToolModel(responses=[AIMessage(content="base")])
        selected_model = FakeToolModel(responses=[AIMessage(content="selected")])
        providers = MappingProxyType(
            {
                "custom": MappingProxyType(
                    {"model": "custom-model", "api_key": "test-key"}
                )
            }
        )
        selected = {("custom", 0.0): selected_model}
        seen = []

        async def handler(request):
            seen.append(request.model)
            return ModelResponse(result=[AIMessage(content="ok")])

        def request():
            return ModelRequest(
                model=base,
                messages=[],
                runtime=Runtime(context=agent_module.TurnContext(model="custom")),
            )

        with (
            patch.object(model_registry, "PROVIDERS", providers),
            patch.object(
                llm_clients,
                "_build_llm",
                side_effect=lambda provider, temperature: selected[
                    (provider, temperature)
                ],
            ),
        ):
            await agent_module.model_selector.awrap_model_call(request(), handler)
            await agent_module.model_selector.awrap_model_call(request(), handler)
        self.assertEqual(seen, [selected_model, selected_model])

    async def test_thinking_is_applied_to_every_agent_call(self):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app import agent as agent_module

        base = FakeToolModel(responses=[AIMessage(content="base")])
        selected_model = FakeToolModel(responses=[AIMessage(content="selected")])
        providers = MappingProxyType(
            {
                "groq": MappingProxyType(
                    {
                        "model": "openai/gpt-oss-120b",
                        "api_key": "test-key",
                        "thinking": MappingProxyType({"reasoning_effort": "medium"}),
                    }
                )
            }
        )
        selected = {("groq", 0.0): selected_model}
        seen = []

        async def handler(request):
            seen.append((request.model, request.model_settings))
            return ModelResponse(result=[AIMessage(content="ok")])

        def request():
            return ModelRequest(
                model=base,
                messages=[],
                runtime=Runtime(
                    context=agent_module.TurnContext(model="groq", thinking="medium")
                ),
            )

        reasoning_module.thinking_model_settings.cache_clear()
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                patch.object(
                    llm_clients,
                    "_build_llm",
                    side_effect=lambda provider, temperature: selected[
                        (provider, temperature)
                    ],
                ),
            ):
                await agent_module.model_selector.awrap_model_call(request(), handler)
                await agent_module.model_selector.awrap_model_call(request(), handler)
        finally:
            reasoning_module.thinking_model_settings.cache_clear()

        self.assertEqual([item[0] for item in seen], [selected_model, selected_model])
        self.assertEqual(
            [item[1] for item in seen],
            [{"reasoning_effort": "medium"}, {"reasoning_effort": "medium"}],
        )

    async def test_concurrent_thinking_efforts_do_not_affect_each_other(self):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app import agent as agent_module

        model = FakeToolModel(responses=[AIMessage(content="ok")])
        providers = MappingProxyType(
            {
                "custom": MappingProxyType(
                    {
                        "model": "model-a",
                        "api_key": "test-key",
                        "thinking": MappingProxyType({"reasoning_effort": "medium"}),
                    }
                )
            }
        )
        seen = []

        async def handler(request):
            await asyncio.sleep(0)
            seen.append(request.model_settings["reasoning_effort"])
            return ModelResponse(result=[AIMessage(content="ok")])

        def request(effort):
            return ModelRequest(
                model=model,
                messages=[],
                runtime=Runtime(
                    context=agent_module.TurnContext(model="custom", thinking=effort)
                ),
            )

        reasoning_module.thinking_model_settings.cache_clear()
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                patch.object(llm_clients, "_build_llm", return_value=model),
            ):
                await asyncio.gather(
                    agent_module.model_selector.awrap_model_call(
                        request("medium"), handler
                    ),
                    agent_module.model_selector.awrap_model_call(
                        request("max"), handler
                    ),
                )
        finally:
            reasoning_module.thinking_model_settings.cache_clear()

        self.assertCountEqual(seen, ["medium", "max"])

    async def test_rejected_thinking_parameter_retries_normal_call(self):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app import agent as agent_module

        model = FakeToolModel(responses=[AIMessage(content="ok")])
        providers = MappingProxyType(
            {
                "custom": MappingProxyType(
                    {
                        "model": "model-a",
                        "api_key": "test-key",
                        "thinking": MappingProxyType({"reasoning_effort": "medium"}),
                    }
                )
            }
        )
        seen = []

        async def handler(request):
            seen.append(request.model_settings)
            if len(seen) == 1:
                raise ValueError("reasoning_effort is unsupported for this model")
            return ModelResponse(result=[AIMessage(content="ok")])

        request = ModelRequest(
            model=model,
            messages=[],
            runtime=Runtime(
                context=agent_module.TurnContext(model="custom", thinking="medium")
            ),
        )
        reasoning_module.thinking_model_settings.cache_clear()
        reasoning_module.REJECTED_THINKING_MODELS.discard(
            ("custom", "model-a", "medium")
        )
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                patch.object(llm_clients, "_build_llm", return_value=model),
                self.assertLogs("deep_agent_app.agent", level="WARNING"),
            ):
                await agent_module.model_selector.awrap_model_call(request, handler)
                # The process remembers the capability failure. A later turn
                # goes directly to the normal model instead of paying for
                # another rejected provider request.
                await agent_module.model_selector.awrap_model_call(request, handler)
        finally:
            reasoning_module.thinking_model_settings.cache_clear()
            reasoning_module.REJECTED_THINKING_MODELS.discard(
                ("custom", "model-a", "medium")
            )

        self.assertEqual(seen, [{"reasoning_effort": "medium"}, {}, {}])

    async def test_empty_provider_completion_retries_once_with_visible_answer_instruction(
        self,
    ):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app.agent.context import TurnContext
        from deep_agent_app.agent.llm.routing import model_selector

        model = FakeToolModel(responses=[AIMessage(content="unused")])
        providers = MappingProxyType(
            {"custom": MappingProxyType({"model": "model-a", "api_key": "test-key"})}
        )
        seen = []

        async def handler(request):
            seen.append(
                request.system_message.content if request.system_message else ""
            )
            return ModelResponse(
                result=[
                    AIMessage(content="" if len(seen) == 1 else "The plan is ready.")
                ]
            )

        request = ModelRequest(
            model=model,
            messages=[],
            runtime=Runtime(context=TurnContext(model="custom")),
        )
        with (
            patch.object(model_registry, "PROVIDERS", providers),
            patch.object(llm_clients, "_build_llm", return_value=model),
            self.assertLogs("deep_agent_app.agent.llm.routing", level="WARNING"),
        ):
            response = await model_selector.awrap_model_call(request, handler)

        self.assertEqual(response.result[0].content, "The plan is ready.")
        self.assertEqual(len(seen), 2)
        self.assertIn("Do not return an empty message", seen[1])

    async def test_two_empty_provider_completions_raise_instead_of_ending_silently(
        self,
    ):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app.agent.context import TurnContext
        from deep_agent_app.agent.llm.routing import model_selector

        model = FakeToolModel(responses=[AIMessage(content="unused")])
        providers = MappingProxyType(
            {"custom": MappingProxyType({"model": "model-a", "api_key": "test-key"})}
        )
        calls = []

        async def handler(request):
            calls.append(request)
            return ModelResponse(result=[AIMessage(content="")])

        request = ModelRequest(
            model=model,
            messages=[],
            runtime=Runtime(context=TurnContext(model="custom")),
        )
        with (
            patch.object(model_registry, "PROVIDERS", providers),
            patch.object(llm_clients, "_build_llm", return_value=model),
            self.assertLogs("deep_agent_app.agent.llm.routing", level="WARNING"),
        ):
            with self.assertRaisesRegex(RuntimeError, "empty response twice"):
                await model_selector.awrap_model_call(request, handler)
        self.assertEqual(len(calls), 2)

    async def test_empty_completion_retry_removes_optional_thinking_setting(self):
        from types import MappingProxyType

        from langchain.agents.middleware import ModelRequest, ModelResponse
        from langgraph.runtime import Runtime

        from deep_agent_app.agent.context import TurnContext
        from deep_agent_app.agent.llm.routing import model_selector

        model = FakeToolModel(responses=[AIMessage(content="unused")])
        providers = MappingProxyType(
            {
                "ollama": MappingProxyType(
                    {
                        "model": "model-a",
                        "api_key": "test-key",
                        "base_url": "https://ollama.com/v1",
                        "thinking": True,
                    }
                )
            }
        )
        settings = []

        async def handler(request):
            settings.append(request.model_settings)
            return ModelResponse(
                result=[AIMessage(content="" if len(settings) == 1 else "Recovered")]
            )

        request = ModelRequest(
            model=model,
            messages=[],
            runtime=Runtime(context=TurnContext(model="ollama", thinking="instant")),
        )
        reasoning_module.thinking_model_settings.cache_clear()
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                patch.object(llm_clients, "_build_llm", return_value=model),
                self.assertLogs("deep_agent_app.agent.llm.routing", level="WARNING"),
            ):
                response = await model_selector.awrap_model_call(request, handler)
        finally:
            reasoning_module.thinking_model_settings.cache_clear()

        self.assertEqual(response.result[0].content, "Recovered")
        self.assertEqual(settings, [{"reasoning_effort": "none"}, {}])

    async def test_tool_call_with_empty_text_is_not_retried(self):
        from langchain.agents.middleware import ModelResponse

        from deep_agent_app.agent.llm.routing import is_empty_model_response

        response = ModelResponse(
            result=[
                tool_call("read_file", {"file_path": "/skills/x/SKILL.md"}, "call-1")
            ]
        )
        self.assertFalse(is_empty_model_response(response))

    async def test_run_turn_passes_model_as_langgraph_context(self):
        from types import MappingProxyType, SimpleNamespace

        from deep_agent_app.agent import TurnContext
        from deep_agent_app.agent.budget import RunBudget

        class EmptyChannel:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        class EmptyStream:
            def __init__(self):
                self.messages = EmptyChannel()
                self.tool_calls = EmptyChannel()
                self.subagents = EmptyChannel()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        class Agent:
            def __init__(self):
                self.call = None

            async def astream_events(self, turn_input, run_config, **kwargs):
                self.call = (turn_input, run_config, kwargs)
                return EmptyStream()

            async def aget_state(self, run_config):
                return SimpleNamespace(interrupts=[])

        fake = Agent()
        providers = MappingProxyType(
            {
                "custom": MappingProxyType(
                    {"model": "custom-model", "api_key": "test-key"}
                )
            }
        )
        with (
            patch.object(model_registry, "PROVIDERS", providers),
            patch.object(agent_runtime, "get_agent", AsyncMock(return_value=fake)),
        ):
            events = [
                event
                async for event in chat.run_turn(
                    "ctx",
                    "/report sales",
                    workspace_id="workspace-1",
                    options={
                        "model": "custom",
                        "thinking": True,
                        "plan": True,
                        "command": {
                            "id": "report",
                            "prompt": "Use present_report to create a workspace report.",
                        },
                    },
                )
            ]

        self.assertEqual(events, [])
        self.assertEqual(fake.call[1]["configurable"]["ui_options"]["model"], "custom")
        context = fake.call[2]["context"]
        self.assertIsInstance(context.run_budget, RunBudget)
        self.assertEqual(
            context,
            TurnContext(
                workspace_id="workspace-1",
                thread_id="ctx",
                model="custom",
                thinking="high",
                plan=True,
                command_id="report",
                command_prompt="Use present_report to create a workspace report.",
                run_budget=context.run_budget,
            ),
        )
        self.assertEqual(fake.call[2]["version"], "v3")


class ServerTests(TestCase):
    """The project can only run under ASGI. Both doors to WSGI are shut:
    `manage.py runserver` starts uvicorn, and config.wsgi refuses to load."""

    def test_runserver_starts_uvicorn(self):
        from django.core.management import call_command, get_commands

        self.assertEqual(get_commands()["runserver"], "deep_agent_app")
        with patch("uvicorn.run") as run:
            call_command("runserver", "0.0.0.0:9000", "--noreload", stdout=StringIO())
        run.assert_called_once()
        app, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(
            (app, kwargs["host"], kwargs["port"], kwargs["reload"]),
            ("config.asgi:application", "0.0.0.0", 9000, False),
        )

    def test_wsgi_is_refused(self):
        import importlib

        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            importlib.import_module("config.wsgi")


class PersistentMcpToolsTests(TestCase):
    """One MCP session for the process; reconnect when it breaks; resend a
    call only when the ERP provably never received it."""

    def make(self, session_factory):
        from contextlib import asynccontextmanager

        from deep_agent_app.agent import PersistentMcpTools

        erp = PersistentMcpTools(
            server_name="erp",
            transport="http",
            url="http://erp.invalid/mcp",
            headers={},
            timeout=30,
            sse_read_timeout=300,
        )
        opened = []

        @asynccontextmanager
        async def fake_session(server_name):
            session = session_factory()
            opened.append(session)
            yield session

        erp._client = SimpleNamespace(session=fake_session)
        return erp, opened

    async def test_one_session_for_many_calls(self):
        class Session:
            calls = []

            async def call_tool(self, name, arguments, **kwargs):
                self.calls.append((name, arguments))
                return {"ok": name}

            async def list_tools(self, cursor=None):
                return "tools"

        erp, opened = self.make(Session)
        self.assertEqual(await erp.list_tools(), "tools")
        for i in range(3):
            self.assertEqual(await erp.call_tool("query", {"i": i}), {"ok": "query"})
        self.assertEqual(len(opened), 1)
        self.assertEqual(len(Session.calls), 3)

    async def test_forgotten_session_is_reopened_and_the_call_resent(self):
        from mcp.shared.exceptions import McpError
        from mcp.types import ErrorData

        class Session:
            def __init__(self):
                self.calls = 0

            async def call_tool(self, name, arguments, **kwargs):
                self.calls += 1
                if (
                    len(opened) == 1
                ):  # the first session: the server restarted and forgot it
                    raise McpError(ErrorData(code=32600, message="Session terminated"))
                return "done"

        erp, opened = self.make(Session)
        self.assertEqual(await erp.call_tool("get_context", {}), "done")
        self.assertEqual(len(opened), 2)
        self.assertEqual([s.calls for s in opened], [1, 1])

    async def test_broken_transport_reconnects_but_does_not_resend(self):
        import anyio

        class Session:
            async def call_tool(self, name, arguments, **kwargs):
                if len(opened) == 1:
                    raise anyio.ClosedResourceError  # the call may have reached the ERP
                return "done"

        erp, opened = self.make(Session)
        with self.assertRaises(anyio.ClosedResourceError):
            await erp.call_tool("stage_changes", {"ops": []})
        self.assertEqual(len(opened), 2)  # reconnected, ready for the next call
        self.assertEqual(await erp.call_tool("query", {}), "done")
        self.assertEqual(len(opened), 2)

    async def test_close_and_reopen(self):
        class Session:
            async def call_tool(self, name, arguments, **kwargs):
                return "done"

        erp, opened = self.make(Session)
        await erp.call_tool("query", {})
        await erp.close()
        self.assertIsNone(erp._session)
        self.assertTrue(opened[0] is not None and erp._keeper is None)
        self.assertEqual(await erp.call_tool("query", {}), "done")
        self.assertEqual(len(opened), 2)
        await erp.close()

    async def test_other_errors_are_not_retried(self):
        class Session:
            async def call_tool(self, name, arguments, **kwargs):
                raise ValueError("bad arguments")

        erp, opened = self.make(Session)
        with self.assertRaises(ValueError):
            await erp.call_tool("query", {})
        self.assertEqual(len(opened), 1)


class StreamApiContractTests(TestCase):
    """chat.py leans on APIs langgraph marks experimental. If a version bump
    moves them, fail here instead of in a user's chat."""

    def test_v3_event_stream_projections(self):
        from langchain_core.language_models.chat_model_stream import (
            AsyncChatModelStream,
        )
        from langchain.agents._subagent_transformer import AsyncSubagentRunStream
        from langgraph.prebuilt._tool_call_stream import ToolCallStream
        from langgraph.pregel import Pregel

        version = inspect.signature(Pregel.astream_events).parameters["version"]
        self.assertIn("v3", str(version.annotation))
        for attr in (
            "tool_call_id",
            "tool_name",
            "input",
            "output",
            "error",
            "output_deltas",
        ):
            self.assertTrue(
                hasattr(ToolCallStream, attr)
                or attr in inspect.getsource(ToolCallStream.__init__),
                attr,
            )
        self.assertTrue(hasattr(AsyncSubagentRunStream, "name"))
        self.assertTrue(hasattr(AsyncChatModelStream, "output"))

    def test_stream_usage_is_requested_from_the_provider(self):
        from deep_agent_app.agent import AUTO_MODEL, build_llm

        self.assertTrue(build_llm(AUTO_MODEL, 0).stream_usage)

    def test_mcp_read_timeout_is_overridden(self):
        from langchain_mcp_adapters.sessions import (
            DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT,
        )

        from deep_agent_app.utilities.constants import DEEP_AGENT

        # The library default would cut off a long connected-system call.
        self.assertEqual(DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT.total_seconds(), 300)
        self.assertGreater(
            next(
                (
                    server.get("sse_read_timeout", 3600)
                    for server in DEEP_AGENT.get("mcp_servers", {}).values()
                ),
                3600,
            ),
            300,
        )

    def test_summarization_middleware_is_off(self):
        from deepagents import create_deep_agent

        from deep_agent_app import agent  # registers the harness profile

        graph = create_deep_agent(
            model=agent.build_llm(agent.AUTO_MODEL, 0), tools=[], subagents=[]
        )
        self.assertFalse(
            [n for n in graph.nodes if "Summarization" in n], list(graph.nodes)
        )
