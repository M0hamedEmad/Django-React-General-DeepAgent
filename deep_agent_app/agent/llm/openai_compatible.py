"""OpenAI-compatible response normalization.

Some gateways return visible reasoning in non-standard fields that
``ChatOpenAI`` does not currently preserve. Keep the version-sensitive
LangChain overrides isolated here so the model factory remains ordinary.
"""

from collections.abc import Mapping

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_openai import ChatOpenAI


def visible_reasoning(value) -> str:
    """Extract displayable reasoning while ignoring encrypted payloads."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(filter(None, (visible_reasoning(item) for item in value)))
    if isinstance(value, Mapping):
        if value.get("type") in {"reasoning.encrypted", "encrypted"}:
            return ""
        for key in (
            "text",
            "reasoning",
            "reasoning_content",
            "thinking",
            "summary",
            "content",
        ):
            if text := visible_reasoning(value.get(key)):
                return text
    return ""


def response_reasoning(payload) -> str:
    """Read reasoning from the common OpenAI-gateway response fields."""
    if not isinstance(payload, Mapping):
        return ""
    for key in ("reasoning", "reasoning_content", "thinking", "reasoning_details"):
        if text := visible_reasoning(payload.get(key)):
            return text
    return ""


class GatewayChatOpenAI(ChatOpenAI):
    """Preserve non-standard reasoning fields from compatible gateways.

    These hooks are private LangChain extension points. Contract tests protect
    both streaming and non-streaming behavior when LangChain is upgraded.
    """

    configured_provider_id: str = "openai_compatible"

    def _convert_chunk_to_generation_chunk(
        self, chunk, default_chunk_class, base_generation_info
    ):
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
        delta = choices[0].get("delta") if choices else None
        if generation is not None and isinstance(generation.message, AIMessageChunk):
            generation.message.response_metadata["model_provider"] = (
                self.configured_provider_id
            )
            if reasoning := response_reasoning(delta):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return generation

    def _create_chat_result(self, response, generation_info=None):
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(warnings=False)
        )
        result = super()._create_chat_result(response, generation_info)
        for generation, choice in zip(
            result.generations, response_dict.get("choices") or [], strict=False
        ):
            if isinstance(generation.message, AIMessage) and (
                reasoning := response_reasoning(choice.get("message"))
            ):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result
