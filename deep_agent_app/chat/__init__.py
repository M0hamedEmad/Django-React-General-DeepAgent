"""Public chat API.

Application code imports from this package boundary. The turn runner,
checkpoint history, streaming adapters, and usage accounting remain separate
internally so each can evolve without growing another monolithic module.
"""

from deep_agent_app.runtime import agent_runtime
from .chat import run_turn
from .history import (
    MessageNotFound,
    branch_before_message,
    delete_checkpoint_history,
    delete_message,
    get_history,
)


def try_start_turn(thread_id: str) -> bool:
    return agent_runtime.try_start_turn(thread_id)


def reserve_chat_turn(thread_id: str) -> None:
    agent_runtime.reserve_chat_turn(thread_id)


def finish_turn(thread_id: str) -> None:
    agent_runtime.finish_turn(thread_id)


def is_turn_running(thread_id: str) -> bool:
    return agent_runtime.is_turn_running(thread_id)


__all__ = [
    "MessageNotFound",
    "branch_before_message",
    "delete_checkpoint_history",
    "delete_message",
    "finish_turn",
    "get_history",
    "is_turn_running",
    "run_turn",
    "reserve_chat_turn",
    "try_start_turn",
]
