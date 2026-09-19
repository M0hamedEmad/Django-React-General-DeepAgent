"""Orchestrate one checkpointed, streaming agent turn."""

import asyncio
import logging
import warnings
from datetime import datetime, timezone
from uuid import uuid4

from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from deep_agent_app.agent.context import TurnContext
from deep_agent_app.runtime import agent_runtime
from deep_agent_app.utilities.constants import (
    RUN_TIMEOUT_SECONDS,
    SSE_HEARTBEAT_SECONDS,
    STREAM_EVENT_BUFFER_SIZE,
)
from deep_agent_app.utilities.validation import resolve_provider, validated_options

from .history import graph_config
from .streaming import pump_agent
from .usage import token_usage

# This experimental API is pinned and guarded by StreamApiContractTests.
warnings.filterwarnings(
    "ignore",
    category=LangChainBetaWarning,
    message=".*v3 streaming.*",
)

log = logging.getLogger(__name__)
_STREAM_END = object()


def _safe_mentions(options):
    mentions = options.get("mentions", ())
    if not isinstance(mentions, (list, tuple)):
        return ()
    return tuple(
        (mention["kind"], mention["id"])
        for mention in mentions
        if isinstance(mention, dict)
        and isinstance(mention.get("kind"), str)
        and isinstance(mention.get("id"), str)
    )


def _turn_options(raw_options):
    """Keep validated choices plus the two validated message-scoped fields."""
    normalized = validated_options(raw_options)
    options = dict(normalized)
    for key in ("mentions", "command"):
        if key in raw_options:
            options[key] = raw_options[key]
    return options


async def run_turn(
    thread_id: str,
    text=None,
    *,
    workspace_id: str | None = None,
    resume=None,
    options=None,
    message_id: str | None = None,
    checkpoint_config=None,
):
    """Run one agent turn and yield protocol-neutral event dictionaries.

    ``text`` starts a turn. ``resume`` continues a checkpoint interrupted by a
    question or approval. Composer options become immutable LangGraph context,
    so changing a model or mode does not rebuild the shared graph.

    Closing this generator cancels the pump and exits the graph stream context,
    which aborts the in-process turn when the browser disconnects.
    """
    raw_options = {} if options is None else options
    options = _turn_options(raw_options)
    if workspace_id is None:
        raise ValueError("workspace_id is required for an agent turn")
    command = options.get("command")
    command = command if isinstance(command, dict) else {}
    turn_context = TurnContext(
        workspace_id=workspace_id,
        thread_id=thread_id,
        model=options["model"],
        agent=options["agent"],
        tools=tuple(options["tools"]),
        mentions=_safe_mentions(options),
        thinking=options["thinking"],
        plan=options["plan"],
        command_id=command.get("id"),
        command_prompt=command.get("prompt"),
    )
    selected_provider = resolve_provider(options["model"])
    run_config = graph_config(thread_id, checkpoint_config)
    run_config["configurable"]["ui_options"] = options
    turn_id = uuid4().hex
    log.info(
        "thread %s turn %s provider %s",
        thread_id,
        turn_id,
        selected_provider,
    )

    if resume is not None:
        turn_input = Command(resume=resume)
    else:
        selected_mentions = _safe_mentions(options)
        message_metadata = {"created_at": datetime.now(timezone.utc).isoformat()}
        if selected_mentions:
            message_metadata["mentions"] = [
                {"kind": kind, "id": identifier}
                for kind, identifier in selected_mentions
            ]
        if isinstance(command.get("id"), str):
            message_metadata["command"] = command["id"]
        turn_input = {
            "messages": [
                HumanMessage(
                    content=text,
                    id=message_id or uuid4().hex,
                    response_metadata=message_metadata,
                )
            ]
        }

    agent = await agent_runtime.get_agent()
    stream = await agent.astream_events(
        turn_input,
        run_config,
        version="v3",
        context=turn_context,
    )
    queue = asyncio.Queue(maxsize=STREAM_EVENT_BUFFER_SIZE)
    usage_calls = {}

    async def emit(event):
        # Record provider usage before browser delivery so a disconnect does
        # not discard metadata that has already arrived.
        if event["type"] in {"_usage_start", "_usage_end"}:
            call = usage_calls.setdefault(event["id"], {})
            call.update(event)
            call["provider_id"] = selected_provider
        else:
            await queue.put(event)

    async def pump():
        try:
            async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                async with stream:
                    await pump_agent(stream, "main", emit)
        except asyncio.CancelledError:
            raise
        except BaseException:
            await queue.put(_STREAM_END)
            raise
        else:
            await queue.put(_STREAM_END)

    task = asyncio.create_task(pump(), name=f"chat-turn-{turn_id}")
    status = "cancelled"
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    SSE_HEARTBEAT_SECONDS,
                )
            except TimeoutError:
                yield {"type": "ping"}
                continue
            if event is _STREAM_END:
                break
            yield event

        if usage_calls:
            yield {"type": "usage", "usage": token_usage(usage_calls.values())}
        await task

        state = await agent.aget_state(graph_config(thread_id))
        interrupts = tuple(state.interrupts)
        status = "interrupted" if interrupts else "completed"
        for interrupt in interrupts:
            yield {
                "type": "interrupt",
                "id": interrupt.id,
                "value": interrupt.value,
            }
    except Exception:
        status = "failed"
        raise
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # A normal consumer already saw the error at ``await task``. During
            # disconnect cleanup, retrieving it avoids orphaned task warnings.
            log.debug("stream pump failed while closing", exc_info=True)
        if usage_calls:
            usage = token_usage(usage_calls.values())
            # Diagnostics only. Durable credit accounting needs a database
            # turn record and explicit handling for unreported provider calls.
            log.info(
                "thread %s turn %s status=%s provider-reported tokens "
                "input=%s output=%s total=%s calls=%s unreported=%s",
                thread_id,
                turn_id,
                status,
                usage["input_tokens"],
                usage["output_tokens"],
                usage["total_tokens"],
                usage["calls"],
                usage["unreported_calls"],
            )
