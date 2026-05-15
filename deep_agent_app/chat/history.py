"""Checkpoint-backed transcript reconstruction and message branching."""

from langgraph.types import Interrupt

from deep_agent_app.runtime import agent_runtime
from deep_agent_app.utilities.constants import TOOL_OUTPUT_LIMIT

from .streaming import as_reasoning, as_text


class MessageNotFound(ValueError):
    """A user message is not present on the thread's active checkpoint branch."""


def graph_config(thread_id: str, checkpoint_config=None):
    """Build a fresh graph config, optionally anchored to an older checkpoint."""
    configurable = {"thread_id": thread_id}
    if checkpoint_config:
        source = checkpoint_config.get("configurable", {})
        if source.get("checkpoint_id"):
            configurable["checkpoint_id"] = source["checkpoint_id"]
        if "checkpoint_ns" in source:
            configurable["checkpoint_ns"] = source["checkpoint_ns"]
    return {"configurable": configurable}


async def get_history(thread_id: str):
    """Return the active thread as AI SDK UI messages.

    Consecutive assistant model/tool steps are merged into one visible message.
    Pending interrupts are restored so questions remain visible after reload.
    The graph is used instead of the saver's tuple API because this checkpoint
    storage format exposes channel values through graph state.
    """
    graph = await agent_runtime.get_agent()
    state = await graph.aget_state(graph_config(thread_id))
    messages = list(state.values.get("messages", []))
    results = {
        message.tool_call_id: message for message in messages if message.type == "tool"
    }
    ui = []
    for message in messages:
        if message.type == "human":
            ui.append(
                ui_message(
                    message,
                    "user",
                    [{"type": "text", "text": as_text(message.content)}],
                )
            )
        elif message.type == "ai":
            parts = []
            if (reasoning := as_reasoning(message)).strip():
                parts.append({"type": "reasoning", "text": reasoning})
            if text := as_text(message.content):
                parts.append({"type": "text", "text": text})
            for call in message.tool_calls:
                if call["name"] == "write_todos":
                    parts.append(plan_part(call))
                else:
                    parts.append(tool_part(call, results.get(call["id"])))
            if not parts:
                continue
            if ui and ui[-1]["role"] == "assistant":
                merge_assistant_parts(ui[-1]["parts"], parts)
            else:
                ui.append(ui_message(message, "assistant", parts))
    for interrupt in state.interrupts:
        if not ui or ui[-1]["role"] != "assistant":
            ui.append({"id": interrupt.id, "role": "assistant", "parts": []})
        ui[-1]["parts"].append(interrupt_part(interrupt))
    if state.interrupts:
        set_latest_plan_lifecycle(ui, "interrupted")
    return ui


def ui_message(message, role, parts):
    """Build one UI message and preserve its checkpointed timestamp."""
    item = {"id": message.id, "role": role, "parts": parts}
    metadata = getattr(message, "response_metadata", {}) or {}
    created_at = metadata.get("created_at")
    ui_metadata = {}
    if isinstance(created_at, str) and created_at:
        ui_metadata["created_at"] = created_at
    command = metadata.get("command")
    if isinstance(command, str) and command:
        ui_metadata["command"] = command
    mentions = metadata.get("mentions")
    if isinstance(mentions, list):
        ui_metadata["mentions"] = [
            {"kind": mention["kind"], "id": mention["id"]}
            for mention in mentions
            if isinstance(mention, dict)
            and isinstance(mention.get("kind"), str)
            and isinstance(mention.get("id"), str)
        ]
    if ui_metadata:
        item["metadata"] = ui_metadata
    return item


def merge_assistant_parts(current, incoming):
    """Merge a model step into its turn, replacing the previous plan."""
    for part in incoming:
        if part["type"] == "data-plan":
            index = next(
                (
                    index
                    for index, old in enumerate(current)
                    if old["type"] == "data-plan"
                ),
                None,
            )
            if index is not None:
                current[index] = part
                continue
        current.append(part)


def plan_part(call, lifecycle="finished"):
    args = call.get("args") or {}
    todos = args.get("todos") if isinstance(args, dict) else []
    return {
        "type": "data-plan",
        "id": "plan",
        "data": {
            "todos": todos if isinstance(todos, list) else [],
            "lifecycle": lifecycle,
        },
    }


def set_latest_plan_lifecycle(messages, lifecycle):
    """Mark the current turn's plan without changing model-authored todos."""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        for part in reversed(message.get("parts", [])):
            if part.get("type") == "data-plan":
                part.setdefault("data", {})["lifecycle"] = lifecycle
                return


def tool_part(call, result):
    part = {
        "type": f"tool-{call['name']}",
        "toolCallId": call["id"],
        "input": call["args"],
    }
    if result is None:
        part["state"] = "input-available"
    elif result.status == "error":
        part |= {"state": "output-error", "errorText": as_text(result.content)}
    else:
        part |= {
            "state": "output-available",
            "output": as_text(result.content)[:TOOL_OUTPUT_LIMIT],
        }
    return part


def interrupt_part(interrupt: Interrupt):
    return {
        "type": "data-interrupt",
        "id": interrupt.id,
        "data": {"id": interrupt.id, "value": interrupt.value},
    }


async def delete_checkpoint_history(thread_id: str):
    """Delete only the LangGraph checkpoints for a Django chat thread."""
    saver = await agent_runtime.get_saver()
    await saver.adelete_thread(thread_id)


def state_message(state, message_id: str):
    return next(
        (
            message
            for message in state.values.get("messages", [])
            if message.type == "human" and message.id == message_id
        ),
        None,
    )


async def branch_before_message(thread_id: str, message_id: str):
    """Return the checkpoint immediately before a visible user message."""
    graph = await agent_runtime.get_agent()
    state = await graph.aget_state(graph_config(thread_id))
    message = state_message(state, message_id)
    if message is None:
        raise MessageNotFound("user message not found in the active conversation")

    text = as_text(message.content)
    while state.parent_config is not None:
        parent = await graph.aget_state(state.parent_config)
        if state_message(parent, message_id) is None:
            return parent.config, text
        state = parent
    return None, text


async def delete_message(thread_id: str, message_id: str):
    """Rewind the active conversation to just before ``message_id``."""
    graph = await agent_runtime.get_agent()
    checkpoint_config, _ = await branch_before_message(thread_id, message_id)
    if checkpoint_config is None:
        await delete_checkpoint_history(thread_id)
    else:
        # Fork the earlier checkpoint without applying pending input writes.
        await graph.aupdate_state(checkpoint_config, {}, as_node="__copy__")
    return await get_history(thread_id)
