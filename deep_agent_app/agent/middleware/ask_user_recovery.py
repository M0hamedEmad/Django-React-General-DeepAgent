"""Recover textual ask_user markup emitted by OpenAI-compatible gateways."""

import html
import logging
import re
from uuid import uuid4

from langchain.agents.middleware import ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage

log = logging.getLogger(__name__)

MINIMAX_SEPARATOR_RE = re.compile(r"\]?\s*<\]minimax\[>\s*\[?", re.IGNORECASE)
ASK_USER_BLOCK_RE = re.compile(
    r"<ask_user\b[^>]*>(.*?)(?:</ask_user\s*>|$)", re.IGNORECASE | re.DOTALL
)
QUESTION_RE = re.compile(
    r"<question\b[^>]*>(.*?)</question\s*>", re.IGNORECASE | re.DOTALL
)
OPTION_RE = re.compile(r"<item\b[^>]*>(.*?)</item\s*>", re.IGNORECASE | re.DOTALL)
OPTIONS_RE = re.compile(
    r"<options\b[^>]*>(.*?)</options\s*>", re.IGNORECASE | re.DOTALL
)


def clean_model_markup(value):
    value = MINIMAX_SEPARATOR_RE.sub("", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def parse_ask_user_markup(content):
    if not isinstance(content, str) or "<ask_user" not in content.lower():
        return None
    normalized = MINIMAX_SEPARATOR_RE.sub("", content)
    block = ASK_USER_BLOCK_RE.search(normalized)
    if block is None:
        return None
    body = block.group(1)
    question_matches = list(QUESTION_RE.finditer(body))
    if not question_matches:
        return None
    remaining = (normalized[: block.start()] + normalized[block.end() :]).strip()
    recovered = []
    for index, question_match in enumerate(question_matches):
        question = clean_model_markup(question_match.group(1))
        if not question:
            continue
        end = (
            question_matches[index + 1].start()
            if index + 1 < len(question_matches)
            else len(body)
        )
        tail = body[question_match.end() : end]
        options_block = OPTIONS_RE.search(tail)
        option_source = options_block.group(1) if options_block else tail
        options = [
            option
            for match in OPTION_RE.finditer(option_source)
            if (option := clean_model_markup(match.group(1)))
        ]
        recovered.append({"question": question, "options": options})
    if not recovered:
        return None
    args = recovered[0] if len(recovered) == 1 else {"questions": recovered}
    return args, remaining


def repair_ask_user_response(response):
    if not isinstance(response, ModelResponse):
        return response
    repaired = []
    changed = False
    for message in response.result:
        parsed = (
            parse_ask_user_markup(message.content)
            if isinstance(message, AIMessage)
            else None
        )
        if parsed is None:
            repaired.append(message)
            continue
        args, remaining = parsed
        tool_calls = list(message.tool_calls)
        if not any(call.get("name") == "ask_user" for call in tool_calls):
            tool_calls.append(
                {
                    "name": "ask_user",
                    "args": args,
                    "id": f"call_{uuid4().hex}",
                    "type": "tool_call",
                }
            )
        repaired.append(
            message.model_copy(
                update={
                    "content": remaining,
                    "tool_calls": tool_calls,
                    "invalid_tool_calls": [],
                }
            )
        )
        changed = True
        log.warning("recovered textual <ask_user> output as a structured tool call")
    if not changed:
        return response
    return ModelResponse(
        result=repaired, structured_response=response.structured_response
    )


@wrap_model_call(name="AskUserMarkupRecovery")
async def recover_ask_user_markup(request, handler):
    return repair_ask_user_response(await handler(request))
