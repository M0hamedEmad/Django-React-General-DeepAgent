"""Translate LangGraph v3 stream projections into neutral chat events."""

import asyncio
import inspect
import logging
from typing import Any
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from deep_agent_app.agent import parse_ask_user_markup
from deep_agent_app.agent.budget import ACTIVE_RUN_BUDGET
from deep_agent_app.utilities.constants import TOOL_OUTPUT_LIMIT

log = logging.getLogger(__name__)


async def emit_event(emit, event):
    """Emit with backpressure while supporting simple synchronous test sinks."""
    result = emit(event)
    if inspect.isawaitable(result):
        await result


async def pump_agent(stream, who, emit):
    """Consume all projections that share one LangGraph stream pump.

    A TaskGroup cancels the remaining projections when any one fails. Using
    ``gather`` here can leave sibling projections waiting on a pump that has
    already stopped.
    """
    async with asyncio.TaskGroup() as group:
        group.create_task(pump_messages(stream.messages, who, emit))
        group.create_task(pump_tool_calls(stream.tool_calls, who, emit))
        group.create_task(pump_subagents(stream.subagents, emit))


async def pump_subagents(channel, emit):
    async for subagent in channel:
        who = subagent.name or "subagent"
        # Use one id for both status events so the UI updates one delegation.
        delegation = uuid4().hex
        await emit_event(
            emit,
            {
                "type": "subagent",
                "id": delegation,
                "name": who,
                "status": subagent.status,
            },
        )
        try:
            await pump_agent(subagent, who, emit)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed child stream can raise before LangGraph updates the
            # mutable handle. Give the UI a terminal state before propagating
            # the real failure to the parent stream.
            status = subagent.status
            if status == "started":
                status = "failed"
            await emit_event(
                emit,
                {
                    "type": "subagent",
                    "id": delegation,
                    "name": who,
                    "status": status,
                },
            )
            raise
        status = subagent.status
        if status == "started":
            # A normally drained child is complete even if an older
            # LangGraph stream implementation leaves its handle unchanged.
            status = "completed"
        await emit_event(
            emit,
            {
                "type": "subagent",
                "id": delegation,
                "name": who,
                "status": status,
            },
        )


async def pump_messages(channel, who, emit):
    async for message in channel:
        call_id = uuid4().hex
        await emit_event(emit, {"type": "_usage_start", "id": call_id, "who": who})
        budget = ACTIVE_RUN_BUDGET.get()
        # The v3 message projection does not expose the summarizer's lc_source
        # before text deltas arrive. Buffer only in compaction mode, then use
        # the model response ID recorded by BudgetedSummaryModel to hide its
        # internal working text while retaining its usage for accounting.
        buffered = [] if budget and budget.filter_internal_model_text else None
        target = buffered.append if buffered is not None else emit
        async with asyncio.TaskGroup() as group:
            group.create_task(pump_deltas(message.text, who, "token", target))
            group.create_task(pump_deltas(message.reasoning, who, "thinking", target))
        # Text and reasoning close on message-finish, so output is now final.
        # Driving all three projections concurrently can deadlock the shared
        # experimental stream pump.
        output = await message.output
        if buffered is not None:
            await budget.wait_for_summaries()
            if not budget.is_internal_message(output.id or message.message_id):
                for event in buffered:
                    await emit_event(emit, event)
        await pump_usage(message, call_id, who, emit, output=output)


async def pump_usage(message, call_id, who, emit, *, output=None):
    """Wait for one provider response and retain its reported usage."""
    if output is None:
        output = await message.output
    metadata = output.response_metadata
    budget = ACTIVE_RUN_BUDGET.get()
    internal_provider = (
        budget.internal_message_provider(output.id or message.message_id)
        if budget is not None
        else None
    )
    await emit_event(
        emit,
        {
            "type": "_usage_end",
            "id": call_id,
            "who": who,
            "provider": metadata.get("model_provider") or "unknown",
            "model": metadata.get("model_name") or "unknown",
            "provider_id": internal_provider,
            "usage": output.usage_metadata,
        },
    )


async def pump_deltas(channel, who, kind, emit):
    if kind == "token":
        await pump_text_deltas(channel, who, emit)
        return
    async for delta in channel:
        if delta:
            await emit_event(emit, {"type": kind, "who": who, "text": delta})


async def pump_text_deltas(channel, who, emit):
    """Stream text while withholding leaked textual ``ask_user`` syntax."""
    marker = "<ask_user"
    pending = ""
    hidden = ""
    suppressing = False

    async for delta in channel:
        if not delta:
            continue
        if suppressing:
            hidden += delta
            continue
        pending += delta
        lowered = pending.lower()
        if (index := lowered.find(marker)) >= 0:
            if safe := pending[:index]:
                await emit_event(
                    emit,
                    {"type": "token", "who": who, "text": safe},
                )
            hidden = pending[index:]
            pending = ""
            suppressing = True
            continue

        # Keep the longest suffix that could still become a split marker.
        keep = next(
            (
                size
                for size in range(min(len(pending), len(marker) - 1), 0, -1)
                if marker.startswith(lowered[-size:])
            ),
            0,
        )
        safe = pending[:-keep] if keep else pending
        pending = pending[-keep:] if keep else ""
        if safe:
            await emit_event(emit, {"type": "token", "who": who, "text": safe})

    if suppressing:
        if parse_ask_user_markup(hidden) is None:
            log.error("provider returned malformed textual <ask_user> output")
            await emit_event(
                emit,
                {
                    "type": "token",
                    "who": who,
                    "text": "The model could not format its question. Please try again.",
                },
            )
        return
    if pending:
        await emit_event(emit, {"type": "token", "who": who, "text": pending})


async def pump_tool_calls(channel, who, emit):
    async for call in channel:
        await emit_event(
            emit,
            {
                "type": "tool_call",
                "who": who,
                "id": call.tool_call_id,
                "name": call.tool_name,
                "args": call.input or {},
            },
        )
        # Fully drain the stream while retaining only the browser display limit.
        chunks = []
        remaining = TOOL_OUTPUT_LIMIT
        async for delta in call.output_deltas:
            if remaining:
                chunk = str(delta)[:remaining]
                chunks.append(chunk)
                remaining -= len(chunk)
        partial = "".join(chunks)
        output = call.output
        error = call.error
        if is_interrupt(error):
            continue
        # LangChain represents handled schema/validation failures as terminal
        # ToolMessages with status="error". They are not raised exceptions, so
        # the live stream must promote them to the AI SDK error state just as
        # checkpoint history already does. This lets the report/visual UI show
        # the bounded backend correction instead of rendering invalid inputs.
        if (
            error is None
            and isinstance(output, ToolMessage)
            and output.status == "error"
        ):
            error = result_text(output) or "The tool could not complete the request."
        await emit_event(
            emit,
            {
                "type": "tool_result",
                "who": who,
                "id": call.tool_call_id,
                "name": call.tool_name,
                "result": partial or result_text(output)[:TOOL_OUTPUT_LIMIT],
                "error": None if error is None else str(error),
            },
        )


def is_interrupt(error) -> bool:
    """Return whether a streamed tool error represents a graph pause."""
    if isinstance(error, str):
        return error.startswith("(Interrupt(")
    if isinstance(error, GraphInterrupt):
        return True
    return (
        isinstance(error, tuple)
        and bool(error)
        and all(isinstance(item, Interrupt) for item in error)
    )


def as_text(content: Any) -> str:
    """Return plain text from LangChain string or typed-block content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return "" if content is None else str(content)


def as_reasoning(message) -> str:
    """Return model reasoning regardless of the provider's storage shape."""
    if isinstance(message.content, list):
        blocks = [
            block
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "reasoning"
        ]
        if blocks:
            return "".join(
                block.get("reasoning") or block.get("text") or "" for block in blocks
            )
    return message.additional_kwargs.get("reasoning_content") or ""


def result_text(output: Any) -> str:
    """Return a tool's terminal payload as text."""
    content = getattr(output, "content", None)
    if content is not None:
        return as_text(content)
    # The task tool returns a Command whose update contains the subagent reply.
    update = getattr(output, "update", None)
    if isinstance(update, dict) and (messages := update.get("messages")):
        return as_text(messages[-1].content)
    return "" if output is None else str(output)
