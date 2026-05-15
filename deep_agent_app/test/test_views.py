"""Fast view-layer tests with no database, model, or MCP access."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from django.test import RequestFactory, SimpleTestCase

from deep_agent_app import chat
from deep_agent_app.runtime import RuntimeBusyError, agent_runtime
from deep_agent_app.views import ChatView, RuntimeView, ai_sdk_frames


class ChatViewUnitTests(SimpleTestCase):
    def test_chat_view_parses_ai_sdk_input_into_one_turn(self):
        request = RequestFactory().post(
            "/api/chat/",
            json.dumps(
                {
                    "id": "thread-1",
                    "messages": [
                        {
                            "id": "message-1",
                            "role": "user",
                            "parts": [
                                {"type": "text", "text": "show "},
                                {"type": "text", "text": "sales"},
                            ],
                        }
                    ],
                    "options": {"thinking": "medium", "plan": True},
                }
            ),
            content_type="application/json",
        )

        turn = ChatView._parse_turn(request)

        self.assertEqual((turn.thread_id, turn.text), ("thread-1", "show sales"))
        self.assertEqual(turn.message_id, "message-1")
        self.assertEqual(turn.options["thinking"], "medium")
        self.assertTrue(turn.options["plan"])

    def test_chat_view_rejects_non_object_json(self):
        request = RequestFactory().post(
            "/api/chat/",
            "[]",
            content_type="application/json",
        )

        with self.assertRaisesRegex(ValueError, "body must be a JSON object"):
            ChatView._parse_turn(request)

    async def test_ai_sdk_stream_owns_protocol_state_and_releases_turn(self):
        async def run_turn(*args, **kwargs):
            yield {"type": "token", "who": "main", "text": "Hello"}
            yield {
                "type": "tool_call",
                "who": "main",
                "id": "plan-1",
                "name": "write_todos",
                "args": {"todos": [{"content": "Check", "status": "pending"}]},
            }

        finish_turn = Mock()
        with (
            patch.object(chat, "run_turn", run_turn),
            patch.object(chat, "finish_turn", finish_turn),
        ):
            body = "".join(
                [chunk async for chunk in ai_sdk_frames("thread-1", "hello")]
            )

        parts = [
            json.loads(line.removeprefix("data: "))
            for line in body.split("\n\n")
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        self.assertEqual(
            [part["type"] for part in parts],
            [
                "start",
                "text-start",
                "text-delta",
                "text-end",
                "data-plan",
                "data-plan",
                "finish",
            ],
        )
        plans = [part for part in parts if part["type"] == "data-plan"]
        self.assertEqual(
            [part["data"]["lifecycle"] for part in plans],
            ["running", "finished"],
        )
        self.assertTrue(body.endswith("data: [DONE]\n\n"))
        finish_turn.assert_called_once_with("thread-1")

    async def test_plan_lifecycle_reflects_interrupt_and_failure(self):
        plan = {
            "type": "tool_call",
            "who": "main",
            "id": "plan-1",
            "name": "write_todos",
            "args": {"todos": [{"content": "Check", "status": "in_progress"}]},
        }

        async def interrupted_turn(*args, **kwargs):
            yield plan
            yield {"type": "interrupt", "id": "question-1", "value": {}}

        async def failed_turn(*args, **kwargs):
            yield plan
            raise RuntimeError("provider failed")

        lifecycles = []
        for turn in (interrupted_turn, failed_turn):
            with patch.object(chat, "run_turn", turn):
                body = "".join(
                    [chunk async for chunk in ai_sdk_frames("thread-1", "hello")]
                )
            parts = [
                json.loads(line.removeprefix("data: "))
                for line in body.split("\n\n")
                if line.startswith("data: ") and line != "data: [DONE]"
            ]
            lifecycles.append(
                [
                    part["data"]["lifecycle"]
                    for part in parts
                    if part["type"] == "data-plan"
                ]
            )

        self.assertEqual(lifecycles[0], ["running", "interrupted"])
        self.assertEqual(lifecycles[1], ["running", "failed"])


class RuntimeViewUnitTests(SimpleTestCase):
    async def test_all_users_can_read_safe_runtime_status(self):
        request = SimpleNamespace(user=SimpleNamespace(username="mona", is_staff=False))
        status = {
            "agent": {"status": "ready"},
            "integrations": [
                {
                    "id": "erp",
                    "status": "unavailable",
                    "message": "Connected company tools are unavailable.",
                }
            ],
        }
        with patch.object(agent_runtime, "public_status", return_value=status):
            response = await RuntimeView().get(request)

        data = json.loads(response.content)
        self.assertEqual(data["integrations"][0]["status"], "unavailable")
        self.assertFalse(data["can_reload"])

    async def test_only_staff_can_reload_the_shared_runtime(self):
        reload_agent = AsyncMock()
        with patch.object(agent_runtime, "reload_agent", reload_agent):
            response = await RuntimeView().post(
                SimpleNamespace(user=SimpleNamespace(is_staff=False))
            )

        self.assertEqual(response.status_code, 403)
        reload_agent.assert_not_awaited()

    async def test_busy_runtime_returns_conflict(self):
        request = SimpleNamespace(user=SimpleNamespace(is_staff=True))
        with patch.object(
            agent_runtime,
            "reload_agent",
            AsyncMock(side_effect=RuntimeBusyError("wait for running chats")),
        ):
            response = await RuntimeView().post(request)

        self.assertEqual(response.status_code, 409)
        self.assertIn("wait for running chats", response.content.decode())
