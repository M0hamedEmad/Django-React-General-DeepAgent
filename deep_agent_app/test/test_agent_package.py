"""Structural tests for the agent package. No provider or MCP I/O."""

import asyncio
from builtins import ExceptionGroup
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from deep_agent_app.chat import streaming as chat_streaming
from deep_agent_app.runtime import agent_runtime


class AgentPackageTests(SimpleTestCase):
    def test_present_ui_schema_keeps_qualitative_values_out_of_charts(self):
        from deep_agent_app.agent.tools.present_ui import present_ui

        schema = present_ui.args_schema.model_json_schema()
        values = schema["$defs"]["Series"]["properties"]["values"]
        value_types = {item["type"] for item in values["items"]["anyOf"]}

        self.assertEqual(value_types, {"number", "null"})
        self.assertIn("qualitative text", values["description"])
        self.assertIn(
            "exactly one compact chat block",
            schema["properties"]["block"]["description"].lower(),
        )
        self.assertEqual(schema["required"], ["block"])
        self.assertNotIn("blocks", schema["properties"])
        self.assertNotIn("placement", schema["properties"])
        block_schema = schema["properties"]["block"]
        self.assertEqual(block_schema["discriminator"]["propertyName"], "type")
        self.assertIn("oneOf", block_schema)
        self.assertNotIn("anyOf", block_schema)

    def test_present_ui_repairs_named_variant_wrapper(self):
        from deep_agent_app.agent.tools.present_ui import PresentUiInput, present_ui

        malformed = {
            "block": {
                "table": {
                    "columns": ["Category", "Risk"],
                    "rows": [["Consumer", "Medium"]],
                }
            }
        }

        parsed = PresentUiInput.model_validate(malformed)

        self.assertEqual(parsed.block.type, "table")
        self.assertEqual(parsed.block.columns, ["Category", "Risk"])
        self.assertIn("Displayed in chat", present_ui.invoke(malformed))

    def test_present_ui_returns_one_concise_validation_error(self):
        from deep_agent_app.agent.tools.present_ui import present_ui

        result = present_ui.invoke(
            {"block": {"type": "table", "columns": ["Customer"]}}
        )

        self.assertIn("tables require columns and rows", result)
        self.assertNotIn("validation errors", result)
        self.assertNotIn("pydantic.dev", result)

    def test_present_report_accepts_multiple_charts_and_status(self):
        from pydantic import TypeAdapter

        from deep_agent_app.agent.tools.present_ui import Block
        from deep_agent_app.agent.tools.reports import present_report

        blocks = TypeAdapter(list[Block]).validate_python(
            [
                {
                    "type": "section",
                    "title": "Performance",
                    "description": "Current operating results.",
                },
                {
                    "type": "chart",
                    "kind": "bar",
                    "title": "Revenue",
                    "labels": ["Jan", "Feb"],
                    "series": [{"name": "Revenue", "values": [10, 12]}],
                },
                {
                    "type": "chart",
                    "kind": "pie",
                    "title": "Mix",
                    "labels": ["Products", "Services"],
                    "series": [{"name": "Share", "values": [70, 30]}],
                },
                {
                    "type": "status",
                    "tone": "warning",
                    "title": "Needs attention",
                    "message": "Two invoices are overdue.",
                },
                {
                    "type": "links",
                    "title": "Sources",
                    "items": [{"label": "Example", "url": "https://example.com"}],
                },
            ]
        )

        self.assertEqual(
            [block.type for block in blocks],
            ["section", "chart", "chart", "status", "links"],
        )
        result = present_report.invoke(
            {
                "title": "Operations",
                "subtitle": "September 2026",
                "blocks": blocks,
            }
        )
        self.assertIn("Report 'Operations' is ready", result)

    def test_present_report_schema_is_canonical_and_repairs_named_wrapper(self):
        from deep_agent_app.agent.tools.reports import (
            PresentReportInput,
            present_report,
        )

        schema = present_report.args_schema.model_json_schema()
        self.assertEqual(schema["required"], ["title", "blocks"])
        self.assertIn("subtitle", schema["properties"])
        self.assertEqual(schema["properties"]["blocks"]["maxItems"], 20)
        self.assertEqual(
            set(schema["properties"]["blocks"]["items"]["discriminator"]["mapping"]),
            {"section", "markdown", "kpis", "chart", "table", "status", "links"},
        )

        parsed = PresentReportInput.model_validate(
            {
                "title": "Sales",
                "blocks": [
                    {
                        "table": {
                            "title": "Leaders",
                            "columns": ["Customer", "Revenue"],
                            "rows": [["Acme", 1200]],
                        }
                    }
                ],
            }
        )
        self.assertEqual(parsed.blocks[0].type, "table")

    def test_present_report_returns_one_concise_validation_error(self):
        from deep_agent_app.agent.tools.reports import present_report

        result = present_report.invoke(
            {
                "title": "Sales",
                "blocks": [{"type": "markdown", "text": "legacy field"}],
            }
        )

        self.assertIn("Invalid present_report data", result)
        self.assertNotIn("validation errors", result)
        self.assertNotIn("pydantic.dev", result)

    def test_present_ui_rejects_report_sized_blocks(self):
        from deep_agent_app.agent.tools.present_ui import ChartBlock, present_ui

        labels = [f"Category {index}" for index in range(21)]
        block = ChartBlock(
            type="chart",
            kind="bar",
            labels=labels,
            series=[{"name": "Demand", "values": list(range(21))}],
        )

        result = present_ui.invoke({"block": block})
        self.assertIn("Invalid present_ui block", result)

    def test_present_ui_rejects_misaligned_chart_and_table_data(self):
        from pydantic import ValidationError

        from deep_agent_app.agent.tools.present_ui import ChartBlock, TableBlock

        with self.assertRaisesRegex(ValidationError, "one value per label"):
            ChartBlock(
                type="chart",
                kind="line",
                labels=["Jan", "Feb"],
                series=[{"name": "Revenue", "values": [10]}],
            )
        with self.assertRaisesRegex(ValidationError, "one value per column"):
            TableBlock(
                type="table",
                columns=["Customer", "Revenue"],
                rows=[["Acme"]],
            )

    def test_company_system_is_permanent_not_an_optional_tool(self):
        from deep_agent_app.utilities.constants import AGENT_UI
        from deep_agent_app.utilities.validation import validate_tool_choices

        self.assertEqual(
            [choice["id"] for choice in AGENT_UI["tools"]],
            ["web_search"],
        )
        self.assertEqual(validate_tool_choices(None), ["web_search"])
        with self.assertRaisesRegex(ValueError, "unknown tool"):
            validate_tool_choices(["erp"])
        with self.assertRaisesRegex(ValueError, "unknown tool"):
            validate_tool_choices(["unknown"])

    def test_public_interface_remains_stable(self):
        from deep_agent_app import agent

        for name in (
            "AUTO_MODEL",
            "TurnContext",
            "build_agent",
            "model_choices",
            "parse_ask_user_markup",
            "resolve_provider",
            "validate_model_choice",
            "validate_plan_mode",
            "validate_thinking_effort",
        ):
            self.assertTrue(hasattr(agent, name), name)

    def test_main_and_connected_skill_sources_are_separate(self):
        from deep_agent_app.agent.skills import (
            connected_skill_sources,
            main_skill_sources,
        )

        self.assertIn(("/skills/general", "Company"), main_skill_sources())
        self.assertEqual(connected_skill_sources(), ())

    def test_duplicate_skill_names_are_rejected(self):
        from deep_agent_app.agent import skills

        with TemporaryDirectory() as directory:
            root = Path(directory)
            for group in ("general", "sales"):
                skill_dir = root / group / "duplicate"
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(
                    "---\nname: duplicate\ndescription: test skill\n---\n"
                )
            with (
                patch.object(skills, "SKILLS_ROOT", root),
                self.assertRaises(ImproperlyConfigured),
            ):
                skills.skill_catalog(
                    (("/skills/general", "Company"), ("/skills/sales", "Sales"))
                )

    def test_skill_name_must_match_its_directory(self):
        from deep_agent_app.agent import skills

        with TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "general" / "wrong-directory"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: actual-name\ndescription: Test skill.\n---\n",
                encoding="utf-8",
            )
            with (
                patch.object(skills, "SKILLS_ROOT", root),
                self.assertRaisesRegex(ImproperlyConfigured, "must match directory"),
            ):
                skills.skill_catalog((("/skills/general", "Company"),))

    def test_app_and_deep_agents_discover_the_same_skills(self):
        from deepagents.middleware.skills import SkillsMiddleware

        from deep_agent_app.agent import skills

        catalog = skills.skill_catalog()
        middleware = SkillsMiddleware(
            backend=skills.build_agent_backend(),
            sources=skills.main_skill_sources(),
        )
        loaded = middleware.before_agent({}, None, {})

        self.assertEqual(
            {item.name: item.virtual_path for item in catalog},
            {item["name"]: item["path"] for item in loaded["skills_metadata"]},
        )
        self.assertIs(skills.skill_catalog(), catalog)

    async def test_main_composition_uses_registered_subagents(self):
        from deep_agent_app.agent import agent as builder

        erp_tools = [Mock(name="erp_tool")]
        subagent = Mock(name="company_subagent")
        graph = Mock(name="graph")
        with (
            patch.object(
                builder.PersistentMcpTools,
                "load_registered_tools",
                AsyncMock(return_value=erp_tools),
            ) as get_tools,
            patch.object(
                builder,
                "get_subagents",
                return_value=[subagent],
            ) as make_subagents,
            patch.object(builder, "build_llm", return_value=Mock(name="model")),
            patch.object(
                builder, "build_agent_backend", return_value=Mock(name="backend")
            ),
            patch.object(builder, "create_deep_agent", return_value=graph) as create,
        ):
            result = await builder.build_agent(Mock(name="checkpointer"))

        self.assertIs(result, graph)
        get_tools.assert_awaited_once_with()
        make_subagents.assert_called_once()
        self.assertIs(make_subagents.call_args.kwargs["mcp_tools"], erp_tools)
        self.assertEqual(create.call_args.kwargs["subagents"], [subagent])
        self.assertEqual(
            [
                getattr(tool, "name", None) or tool.__name__
                for tool in create.call_args.kwargs["tools"]
            ],
            [
                "internet_search",
                "fetch_webpage_content",
                "ask_user",
                "present_ui",
                "present_report",
            ],
        )
        self.assertNotIn("interrupt_on", create.call_args.kwargs)
        permissions = create.call_args.kwargs["permissions"]
        self.assertEqual(len(permissions), 1)
        self.assertEqual(permissions[0].operations, ["write"])
        self.assertEqual(permissions[0].paths, ["/skills", "/skills/**"])
        self.assertEqual(permissions[0].mode, "deny")

    def test_company_subagent_is_plain_definition_with_injected_tools(self):
        from deep_agent_app.agent import subagent

        tool = Mock(name="erp_tool")
        model = Mock(name="model")
        with (
            patch.object(subagent, "CONNECTED_SYSTEM_ENABLED", True),
            patch.object(
                subagent,
                "connected_skill_sources",
                return_value=(("/skills/sales", "Sales"),),
            ),
            patch.object(
                subagent,
                "build_subagent",
                wraps=subagent.build_subagent,
            ) as factory,
        ):
            definitions = subagent.get_subagents(
                model=model,
                mcp_tools=[tool],
            )
            definition = definitions[0]

        factory.assert_called_once()
        self.assertEqual(definition["name"], subagent.CONNECTED_SUBAGENT_NAME)
        self.assertIn("delegated company tasks", definition["description"])
        self.assertIs(definition["system_prompt"], subagent.SUBAGENT_PROMPT)
        self.assertIs(definition["model"], model)
        self.assertIs(definition["tools"][0], tool)
        self.assertEqual(
            definition["middleware"],
            [subagent.recover_ask_user_markup, subagent.model_selector],
        )
        self.assertEqual(definition["skills"], [("/skills/sales", "Sales")])
        self.assertNotIn("interrupt_on", definition)

    def test_disabled_mcp_hides_connected_subagent(self):
        from deep_agent_app.agent import subagent

        with patch.object(subagent, "CONNECTED_SYSTEM_ENABLED", False):
            self.assertEqual(
                subagent.get_subagents(model="auto", mcp_tools=[]),
                [],
            )
            self.assertEqual(subagent.composer_subagents(), [])

    def test_composer_subagents_are_derived_from_registered_definitions(self):
        from deep_agent_app.agent import subagent

        definitions = [
            {
                "name": "research_worker",
                "description": "Research company questions.",
                "tools": [Mock(name="research_tool")],
            }
        ]
        with patch.object(subagent, "get_subagents", return_value=definitions):
            metadata = subagent.composer_subagents()

        self.assertEqual(
            metadata,
            [
                {
                    "id": "research_worker",
                    "target": "research_worker",
                    "label": "Research Worker",
                    "description": "Research company questions.",
                }
            ],
        )

    async def test_mcp_tools_initialize_once(self):
        from deep_agent_app.agent.integrations import persistent_mcp_tools

        session = Mock(name="session")
        loader = AsyncMock(return_value=[Mock(name="tool")])
        integration = persistent_mcp_tools.PersistentMcpTools(
            server_name="erp",
            transport="http",
            url="http://erp.invalid/mcp",
            headers={},
            timeout=30,
            sse_read_timeout=300,
        )
        integration._session = session
        with patch.object(persistent_mcp_tools, "load_mcp_tools", loader):
            first = await integration.get_tools()
            second = await integration.get_tools()

        self.assertIs(first, second)
        loader.assert_awaited_once_with(integration)

    async def test_registered_subclasses_are_loaded_automatically(self):
        from weakref import WeakSet

        from deep_agent_app.agent.integrations.persistent_mcp_tools import (
            PersistentMcpTools,
        )

        class FutureMcp(PersistentMcpTools):
            pass

        with patch.object(PersistentMcpTools, "_instances", WeakSet()):
            first = PersistentMcpTools(
                server_name="documents",
                transport="http",
                url="http://documents.invalid/mcp",
                headers={},
                timeout=30,
                sse_read_timeout=300,
            )
            second = FutureMcp(
                server_name="crm",
                transport="http",
                url="http://crm.invalid/mcp",
                headers={},
                timeout=30,
                sse_read_timeout=300,
            )
            with (
                patch.object(first, "get_tools", AsyncMock(return_value=["doc"])),
                patch.object(second, "get_tools", AsyncMock(return_value=["crm"])),
            ):
                tools = await PersistentMcpTools.load_registered_tools()

            self.assertEqual(tools, ["crm", "doc"])
            self.assertEqual(
                [item["id"] for item in PersistentMcpTools.registered_statuses()],
                ["crm", "documents"],
            )

    async def test_optional_mcp_failure_returns_no_tools_and_logs_warning(self):
        from deep_agent_app.agent.integrations import persistent_mcp_tools

        integration = persistent_mcp_tools.PersistentMcpTools(
            server_name="erp",
            transport="http",
            url="http://erp.invalid/mcp",
            headers={},
            timeout=30,
            sse_read_timeout=300,
        )
        failure = ExceptionGroup(
            "connection failed",
            [httpx.ConnectError("All connection attempts failed")],
        )
        with (
            patch.object(
                integration,
                "_load_tools",
                AsyncMock(side_effect=failure),
            ),
            self.assertLogs(persistent_mcp_tools.log, level="WARNING") as logs,
        ):
            tools = await integration.get_tools(required=False)

        self.assertEqual(tools, [])
        self.assertIn("starting without its tools", logs.output[0])
        self.assertIn("ConnectError: All connection attempts failed", logs.output[0])
        self.assertEqual(integration.public_status()["status"], "unavailable")

    async def test_required_mcp_failure_is_not_hidden(self):
        from deep_agent_app.agent.integrations import persistent_mcp_tools

        integration = persistent_mcp_tools.PersistentMcpTools(
            server_name="erp",
            transport="http",
            url="http://erp.invalid/mcp",
            headers={},
            timeout=30,
            sse_read_timeout=300,
        )
        failure = httpx.ConnectError("All connection attempts failed")
        with patch.object(
            integration,
            "_load_tools",
            AsyncMock(side_effect=failure),
        ):
            with self.assertRaises(httpx.ConnectError):
                await integration.get_tools()

    def test_mcp_runtime_rejects_a_different_event_loop(self):
        from deep_agent_app.agent.integrations.persistent_mcp_tools import (
            PersistentMcpTools,
        )

        integration = PersistentMcpTools(
            server_name="erp",
            transport="http",
            url="http://erp.invalid/mcp",
            headers={},
            timeout=30,
            sse_read_timeout=300,
        )

        async def bind_to_current_loop():
            integration._lifecycle_lock()

        asyncio.run(bind_to_current_loop())
        with self.assertRaisesRegex(RuntimeError, "different event loop"):
            asyncio.run(bind_to_current_loop())

    def test_repeated_model_selection_reuses_cached_client(self):
        from deep_agent_app.utilities import model_registry
        from deep_agent_app.agent.llm import clients

        providers = MappingProxyType(
            {
                "test": MappingProxyType(
                    {
                        "model_provider": "test_provider",
                        "model": "test-model",
                        "api_key": "test-key",
                    }
                )
            }
        )
        client = Mock(name="client")
        clients._build_llm.cache_clear()
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                patch.object(
                    clients, "init_chat_model", return_value=client
                ) as initialize,
            ):
                first = clients.build_llm("test", 0.7)
                second = clients.build_llm("test", 0.7)
        finally:
            clients._build_llm.cache_clear()

        self.assertIs(first, second)
        initialize.assert_called_once()

    def test_provider_temperature_is_the_factory_default(self):
        from deep_agent_app.utilities import model_registry
        from deep_agent_app.agent.llm import clients

        providers = MappingProxyType(
            {
                "test": MappingProxyType(
                    {
                        "model_provider": "test_provider",
                        "model": "test-model",
                        "api_key": "test-key",
                        "temperature": 0.35,
                    }
                )
            }
        )
        client = Mock(name="client")
        clients._build_llm.cache_clear()
        try:
            with (
                patch.object(model_registry, "PROVIDERS", providers),
                patch.object(
                    clients, "init_chat_model", return_value=client
                ) as initialize,
            ):
                self.assertIs(clients.build_llm("test"), client)
        finally:
            clients._build_llm.cache_clear()

        self.assertEqual(initialize.call_args.kwargs["temperature"], 0.35)

    def test_model_and_reasoning_caches_are_bounded(self):
        from deep_agent_app.agent.llm import clients, reasoning

        self.assertEqual(
            clients._build_llm.cache_parameters()["maxsize"],
            clients.MODEL_CLIENT_CACHE_SIZE,
        )
        self.assertEqual(
            reasoning.thinking_model_settings.cache_parameters()["maxsize"],
            reasoning.THINKING_SETTINGS_CACHE_SIZE,
        )

    def test_reasoning_profile_does_not_build_another_model_client(self):
        from deep_agent_app.agent.llm import reasoning

        model = SimpleNamespace(
            profile={
                "reasoning_output": True,
                "reasoning_effort_levels": ["low", "high"],
            }
        )

        self.assertEqual(
            reasoning.model_reasoning_profile(model),
            (True, ("low", "high")),
        )

    async def test_search_client_is_closed_and_forgotten(self):
        from deep_agent_app.agent.tools import search

        client = Mock(close=AsyncMock())
        with patch.object(search, "_client", client):
            await search.close_search()
            self.assertIsNone(search._client)

        client.close.assert_awaited_once_with()

    def test_runtime_turn_reservation_is_atomic_and_idempotent(self):
        from deep_agent_app.runtime import AgentRuntime

        runtime = AgentRuntime()
        self.assertTrue(runtime.try_start_turn("thread-1"))
        self.assertFalse(runtime.try_start_turn("thread-1"))
        self.assertTrue(runtime.is_turn_running("thread-1"))
        runtime.finish_turn("thread-1")
        runtime.finish_turn("thread-1")
        self.assertFalse(runtime.is_turn_running("thread-1"))

    def test_runtime_enforces_chat_capacity_without_cross_thread_mutation(self):
        from deep_agent_app.runtime import (
            AgentRuntime,
            RuntimeCapacityError,
            ThreadBusyError,
        )

        runtime = AgentRuntime()
        with patch("deep_agent_app.runtime.MAX_CONCURRENT_RUNS", 1):
            runtime.reserve_chat_turn("thread-1")
            with self.assertRaises(ThreadBusyError):
                runtime.reserve_chat_turn("thread-1")
            with self.assertRaises(RuntimeCapacityError):
                runtime.reserve_chat_turn("thread-2")

            runtime.finish_turn("thread-1")
            runtime.reserve_chat_turn("thread-2")

        self.assertTrue(runtime.is_turn_running("thread-2"))

    async def test_runtime_reload_reconnects_mcp_and_replaces_graph(self):
        from deep_agent_app.agent.integrations import PersistentMcpTools
        from deep_agent_app.runtime import AgentRuntime

        runtime = AgentRuntime()
        runtime._loop = asyncio.get_running_loop()
        runtime._build_lock = asyncio.Lock()
        runtime._saver = Mock(name="saver")
        old_graph = Mock(name="old_graph")
        new_graph = Mock(name="new_graph")
        runtime._graph = old_graph

        with (
            patch.object(
                PersistentMcpTools,
                "close_registered",
                AsyncMock(),
            ) as close,
            patch(
                "deep_agent_app.agent.agent.build_agent",
                AsyncMock(return_value=new_graph),
            ) as build,
        ):
            result = await runtime.reload_agent()

        self.assertIs(result, new_graph)
        self.assertIs(runtime._graph, new_graph)
        close.assert_awaited_once_with()
        build.assert_awaited_once_with(runtime._saver)

    async def test_runtime_reload_is_rejected_while_a_turn_runs(self):
        from deep_agent_app.runtime import AgentRuntime, RuntimeBusyError

        runtime = AgentRuntime()
        runtime._loop = asyncio.get_running_loop()
        runtime._build_lock = asyncio.Lock()
        runtime._running_threads.add("thread-1")

        with self.assertRaisesRegex(RuntimeBusyError, "running chats"):
            await runtime.reload_agent()

    async def test_invalid_options_do_not_initialize_agent(self):
        from deep_agent_app import chat

        with patch.object(agent_runtime, "get_agent", AsyncMock()) as get_agent:
            for options in ({"plan": "yes"}, [], {"model": "missing-provider"}):
                with self.assertRaises(ValueError):
                    await anext(chat.run_turn("invalid", "hello", options=options))
            get_agent.assert_not_awaited()

    async def test_tool_display_is_bounded_but_fully_drained(self):
        consumed = []

        async def deltas():
            for index in range(10):
                consumed.append(index)
                yield "x" * 100

        async def calls():
            yield SimpleNamespace(
                tool_call_id="tool-1",
                tool_name="report",
                input={},
                output_deltas=deltas(),
                error=None,
                output="full result",
            )

        events = []
        with patch("deep_agent_app.chat.streaming.TOOL_OUTPUT_LIMIT", 150):
            await chat_streaming.pump_tool_calls(calls(), "main", events.append)
        self.assertEqual(len(consumed), 10)
        self.assertEqual(events[-1]["result"], "x" * 150)

    async def test_async_event_emission_applies_backpressure(self):
        queue = asyncio.Queue(maxsize=1)
        await queue.put("first")

        blocked = asyncio.create_task(chat_streaming.emit_event(queue.put, "second"))
        await asyncio.sleep(0)
        self.assertFalse(blocked.done())

        self.assertEqual(await queue.get(), "first")
        await blocked
        self.assertEqual(await queue.get(), "second")

    async def test_closing_turn_waits_for_stream_cleanup(self):
        from deep_agent_app import chat

        never = asyncio.Event()
        stream_closed = asyncio.Event()

        async def text():
            yield "hello"

        async def empty():
            if False:
                yield None

        async def forever():
            await never.wait()
            if False:
                yield None

        class Message:
            def __init__(self):
                self.text = text()
                self.reasoning = empty()
                self.output = asyncio.get_running_loop().create_future()

        class Stream:
            def __init__(self):
                self.messages = empty()
                self.tool_calls = forever()
                self.subagents = forever()

            async def __aenter__(self):
                self.messages = self.message_channel()
                return self

            async def __aexit__(self, *_exc):
                stream_closed.set()

            async def message_channel(self):
                yield Message()

        class Agent:
            async def astream_events(self, *_args, **_kwargs):
                return Stream()

        with (
            patch.object(agent_runtime, "get_agent", AsyncMock(return_value=Agent())),
            self.assertLogs("deep_agent_app.chat", level="INFO") as logs,
        ):
            turn = chat.run_turn("disconnect", "hello")
            event = await asyncio.wait_for(anext(turn), 1)
            self.assertEqual(event["text"], "hello")
            await asyncio.wait_for(turn.aclose(), 1)

        self.assertTrue(stream_closed.is_set())
        self.assertTrue(
            any(
                "status=cancelled" in line and "unreported=1" in line
                for line in logs.output
            )
        )

    def test_main_capabilities_are_filtered_per_turn(self):
        from langchain.agents.middleware import ModelRequest
        from langgraph.runtime import Runtime

        from deep_agent_app.agent.context import TurnContext
        from deep_agent_app.agent.middleware.selection import (
            TurnSelectionMiddleware,
        )
        from deep_agent_app.agent.subagent import CONNECTED_SUBAGENT_NAME

        middleware = TurnSelectionMiddleware(CONNECTED_SUBAGENT_NAME)

        def prepare(context):
            request = ModelRequest(
                model=Mock(),
                messages=[],
                tools=[
                    {"name": "internet_search"},
                    {"name": "task"},
                    {"name": "present_ui"},
                    {"name": "present_report"},
                ],
                runtime=Runtime(context=context),
            )
            return middleware.prepare(request)

        disabled = prepare(TurnContext(tools=()))
        self.assertEqual(
            [tool["name"] for tool in disabled.tools],
            ["task", "present_ui", "present_report"],
        )

        selected_connected = prepare(TurnContext(agent="connected", tools=()))
        self.assertEqual(
            [tool["name"] for tool in selected_connected.tools],
            ["task", "present_ui", "present_report"],
        )
        self.assertIn(
            CONNECTED_SUBAGENT_NAME,
            selected_connected.system_message.content,
        )

        mentioned_tool = prepare(TurnContext(tools=(), mentions=(("tool", "query"),)))
        self.assertIn("task", [tool["name"] for tool in mentioned_tool.tools])

        mentioned_search = prepare(
            TurnContext(tools=(), mentions=(("tool", "internet_search"),))
        )
        self.assertIn(
            "internet_search",
            [tool["name"] for tool in mentioned_search.tools],
        )

        selected_general_skill = prepare(
            TurnContext(tools=(), mentions=(("skill", "executive-brief"),))
        )
        self.assertIn(
            "/skills/general/executive-brief/SKILL.md",
            selected_general_skill.system_message.content,
        )
        self.assertNotIn(
            CONNECTED_SUBAGENT_NAME,
            selected_general_skill.system_message.content,
        )

    def test_composer_tools_come_only_from_mentions_json(self):
        from deep_agent_app.utilities import composer

        composer._mention_catalog.cache_clear()
        configured = (
            {
                "kind": "tool",
                "id": "configured_lookup",
                "label": "Configured lookup",
                "agents": ["connected"],
                "description": "Look up configured company data.",
            },
        )
        subagents = (
            {
                "id": "connected",
                "target": "connected_system",
                "label": "Connected systems",
                "description": "Connected worker.",
                "tools": ["must_not_be_discovered"],
            },
        )
        with (
            patch.object(composer, "_configured_mentions", return_value=configured),
            patch(
                "deep_agent_app.agent.subagent.composer_subagents",
                return_value=subagents,
            ),
        ):
            items = composer.mentions()
        composer._mention_catalog.cache_clear()

        by_key = {(item["kind"], item["id"]): item for item in items}
        self.assertNotIn(("tool", "must_not_be_discovered"), by_key)
        self.assertEqual(
            by_key[("tool", "configured_lookup")]["owners"],
            [{"id": "connected", "label": "Connected systems"}],
        )
        self.assertEqual(
            by_key[("tool", "configured_lookup")]["description"],
            "Look up configured company data.",
        )

    def test_mentions_json_description_drives_prompt_and_can_exclude_any_kind(self):
        from deep_agent_app.utilities import composer

        overrides = (
            {
                "kind": "tool",
                "id": "internet_search",
                "exclude": True,
            },
            {
                "kind": "tool",
                "id": "ask_user",
                "label": "Clarify",
                "agents": ["general"],
                "description": "Ask for all missing details in one batch.",
            },
            {"kind": "agent", "id": "connected", "exclude": True},
            {"kind": "skill", "id": "executive-brief", "exclude": True},
        )
        composer._mention_catalog.cache_clear()
        with patch.object(composer, "_configured_mentions", return_value=overrides):
            items = composer.mentions()
            prompts = composer.mention_prompts((("tool", "ask_user"),))
        composer._mention_catalog.cache_clear()

        keys = {(item["kind"], item["id"]) for item in items}
        self.assertNotIn(("tool", "internet_search"), keys)
        self.assertNotIn(("agent", "connected"), keys)
        self.assertNotIn(("skill", "executive-brief"), keys)
        ask_user = next(item for item in items if item["id"] == "ask_user")
        self.assertEqual(ask_user["label"], "Clarify")
        self.assertEqual(
            ask_user["owners"], [{"id": "general", "label": "General agent"}]
        )
        self.assertIn("Ask for all missing details in one batch.", prompts[0])

    def test_mention_prompts_preserve_user_order_and_ignore_unknown_values(self):
        from deep_agent_app.utilities import composer

        prompts = composer.mention_prompts(
            (
                ("tool", "internet_search"),
                ("unknown", "bad"),
                ("agent", "connected"),
            )
        )

        self.assertIn("`internet_search` tool", prompts[0])
        self.assertEqual(len(prompts), 1)

    async def test_asgi_lifespan_closes_the_agent_runtime(self):
        from deep_agent_app.asgi import AgentLifespanApplication
        from deep_agent_app import asgi

        delegated = AsyncMock()
        shutdown = AsyncMock()
        application = AgentLifespanApplication(delegated)
        messages = iter(
            [
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        with patch.object(asgi.agent_runtime, "shutdown", shutdown):
            await application({"type": "lifespan"}, receive, send)

        delegated.assert_not_awaited()
        shutdown.assert_awaited_once_with()
        self.assertEqual(
            sent,
            [
                {"type": "lifespan.startup.complete"},
                {"type": "lifespan.shutdown.complete"},
            ],
        )
