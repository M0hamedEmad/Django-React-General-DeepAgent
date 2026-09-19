"""Run-scoped model and thinking selection for every agent model call."""

import logging
from datetime import datetime, timezone

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage, SystemMessage

from ..context import TurnContext
from deep_agent_app.utilities import model_registry
from deep_agent_app.utilities.validation import resolve_provider
from . import clients, reasoning

log = logging.getLogger(__name__)

EMPTY_RESPONSE_RETRY_INSTRUCTION = (
    "The previous model attempt produced neither user-visible text nor a tool call. "
    "Complete this turn with a concise answer or an appropriate tool call. "
    "Do not return an empty message."
)


class EmptyModelResponseError(RuntimeError):
    """The provider twice returned neither answer text nor a tool call."""


def is_empty_model_response(response):
    """Detect a provider's silent completion without misclassifying tool calls."""
    if (
        not isinstance(response, ModelResponse)
        or response.structured_response is not None
    ):
        return False
    if len(response.result) != 1 or not isinstance(response.result[0], AIMessage):
        return False
    message = response.result[0]
    if message.tool_calls:
        return False
    if isinstance(message.content, str):
        return not message.content.strip()
    if isinstance(message.content, list):
        return not any(
            isinstance(block, dict)
            and block.get("type") == "text"
            and str(block.get("text", "")).strip()
            for block in message.content
        )
    return not message.content


def empty_response_retry_request(request):
    system_message = request.system_message
    if system_message is None:
        system_message = SystemMessage(content=EMPTY_RESPONSE_RETRY_INSTRUCTION)
    else:
        system_message = system_message.model_copy(
            update={
                "content": (
                    f"{system_message.content}\n\n{EMPTY_RESPONSE_RETRY_INSTRUCTION}"
                )
            }
        )
    return request.override(system_message=system_message)


def timestamp_model_response(response):
    if not isinstance(response, ModelResponse):
        return response
    created_at = datetime.now(timezone.utc).isoformat()
    messages = []
    changed = False
    for message in response.result:
        if isinstance(message, AIMessage) and not message.response_metadata.get(
            "created_at"
        ):
            message = message.model_copy(
                update={
                    "response_metadata": {
                        **message.response_metadata,
                        "created_at": created_at,
                    }
                }
            )
            changed = True
        messages.append(message)
    if not changed:
        return response
    return ModelResponse(
        result=messages, structured_response=response.structured_response
    )


def command_system_message(system_message, context):
    if not context or not context.command_id or not context.command_prompt:
        return system_message
    instruction = "\n\n".join(
        (
            "## Selected slash command",
            f"The user selected /{context.command_id}. Its configured meaning is: {context.command_prompt}",
            "Apply that meaning to any text after the slash command. The later text narrows or overrides details. Do not discuss the slash token unless the user asks about it.",
        )
    )
    if system_message is None:
        return SystemMessage(content=instruction)
    return system_message.model_copy(
        update={"content": f"{system_message.content}\n\n{instruction}"}
    )


@wrap_model_call
async def model_selector(request: ModelRequest[TurnContext], handler):
    """Select one cached model for the current turn without changing globals."""
    context = request.runtime.context
    provider_id = resolve_provider(
        context.model if context else model_registry.AUTO_MODEL
    )
    model = clients.build_llm(provider_id, 0.0)
    overrides = {"model": model}
    if context and context.command_id:
        overrides["system_message"] = command_system_message(
            request.system_message, context
        )
    effort = context.thinking if context else "instant"
    thinking_key = (
        provider_id,
        model_registry.PROVIDERS[provider_id]["model"],
        effort,
    )
    thinking_settings = (
        reasoning.thinking_model_settings(
            provider_id,
            effort,
            reasoning.model_reasoning_profile(model),
        )
        if context and thinking_key not in reasoning.REJECTED_THINKING_MODELS
        else {}
    )
    if thinking_settings:
        overrides["model_settings"] = {
            **request.model_settings,
            **thinking_settings,
        }
    dispatched_request = request.override(**overrides)

    async def invoke(candidate):
        if context and context.run_budget is not None:
            context.run_budget.consume_model_call()
        return await handler(candidate)

    try:
        response = await invoke(dispatched_request)
    except Exception as exc:
        if thinking_settings and reasoning.is_unsupported_thinking_error(exc):
            reasoning.REJECTED_THINKING_MODELS.add(thinking_key)
            log.warning(
                "provider %s model %s rejected thinking effort %s; continuing normally: %s",
                provider_id,
                model_registry.PROVIDERS[provider_id]["model"],
                effort,
                exc,
            )
            dispatched_request = request.override(
                model=model, model_settings=request.model_settings
            )
            response = await invoke(dispatched_request)
        else:
            raise
    if is_empty_model_response(response):
        log.warning(
            "provider %s model %s returned an empty final response; retrying once",
            provider_id,
            model_registry.PROVIDERS[provider_id]["model"],
        )
        retry_request = dispatched_request
        if thinking_settings:
            retry_request = request.override(
                model=model, model_settings=request.model_settings
            )
        response = await invoke(empty_response_retry_request(retry_request))
        if is_empty_model_response(response):
            raise EmptyModelResponseError(
                "The model returned an empty response twice; please retry the turn."
            )
    return timestamp_model_response(response)
