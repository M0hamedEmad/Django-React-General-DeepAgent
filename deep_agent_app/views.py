"""Django views for the React chat page and its authenticated JSON API.

Agent turns are streamed with the AI SDK UI Message Stream protocol: each
part is an SSE ``data: {...}`` frame and the stream ends with ``[DONE]``.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie

from deep_agent_app import chat
from deep_agent_app.agent.backend import (
    delete_conversation_workspace,
    migrate_legacy_user_workspace,
)
from deep_agent_app.models import Thread, UserWorkspace
from deep_agent_app.runtime import (
    RuntimeBusyError,
    RuntimeCapacityError,
    ThreadBusyError,
    agent_runtime,
)
from deep_agent_app.utilities import composer
from deep_agent_app.utilities.constants import AGENT_UI, TOOL_OUTPUT_LIMIT, thaw
from deep_agent_app.utilities.model_registry import AUTO_MODEL, model_choices
from deep_agent_app.utilities.validation import validated_options

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# React page
# ---------------------------------------------------------------------------


def _chat_assets():
    """Resolve Vite's content-hashed JavaScript and CSS bundle names."""
    manifest_path = finders.find("chat/manifest.json")
    if not manifest_path:
        raise ImproperlyConfigured(
            "The chat frontend is not built: cd frontend && npm run build"
        )

    manifest = json.loads(Path(manifest_path).read_text())
    entry = manifest["src/main.tsx"]
    return {
        "js": f"chat/{entry['file']}",
        "css": [f"chat/{name}" for name in entry.get("css", [])],
    }


@login_required
@ensure_csrf_cookie
async def chat_page(request, thread_id=None):
    """Serve the React shell; the frontend loads owned thread data via the API."""
    return render(request, "deep_agent_app/chat.html", _chat_assets())


# ---------------------------------------------------------------------------
# AI SDK stream protocol
# ---------------------------------------------------------------------------


class AiSdkEventStream:
    """Translate one internal agent event stream into AI SDK SSE frames.

    The object owns the mutable state required to join token deltas into text
    and reasoning blocks. Keeping that state here makes the protocol mapping
    independent from HTTP request parsing and thread persistence.
    """

    HEARTBEAT = ": ping\n\n"
    DONE = "data: [DONE]\n\n"
    PLAN_TOOL = "write_todos"

    def __init__(
        self,
        thread_id,
        text,
        *,
        workspace_id=None,
        resume=None,
        options=None,
        message_id=None,
        checkpoint_config=None,
    ):
        self.thread_id = thread_id
        self.workspace_id = workspace_id
        self.text = text
        self.resume = resume
        self.options = options
        self.message_id = message_id
        self.checkpoint_config = checkpoint_config

        self.plan_id = uuid4().hex
        self.plan_todos = None
        self.interrupted = False
        self.block = None
        self.block_id = None
        self.block_opened = False
        self.held_whitespace = ""

    async def __aiter__(self):
        yield self._frame(
            {
                "type": "start",
                "messageId": uuid4().hex,
                "messageMetadata": {
                    "created_at": datetime.now(timezone.utc).isoformat()
                },
            }
        )

        try:
            turn_kwargs = {
                "resume": self.resume,
                "options": self.options,
                "message_id": self.message_id,
                "checkpoint_config": self.checkpoint_config,
            }
            if self.workspace_id is not None:
                turn_kwargs["workspace_id"] = self.workspace_id
            events = chat.run_turn(
                self.thread_id,
                self.text,
                **turn_kwargs,
            )
            async for event in events:
                for output in self._event_frames(event):
                    yield output

            if end := self._close_block():
                yield end
            if self.plan_todos is not None:
                lifecycle = "interrupted" if self.interrupted else "finished"
                yield self._frame(self._plan_part(lifecycle))
            yield self._frame({"type": "finish"})
        except Exception as exc:
            log.exception("turn failed on thread %s", self.thread_id)
            if end := self._close_block():
                yield end
            if self.plan_todos is not None:
                yield self._frame(self._plan_part("failed"))
            yield self._frame({"type": "error", "errorText": self._error_text(exc)})
        finally:
            chat.finish_turn(self.thread_id)

        yield self.DONE

    def _event_frames(self, event):
        """Return the SSE frames produced by one internal agent event."""
        event_type = event["type"]
        if event_type == "ping":
            return [self.HEARTBEAT]
        if event_type in {"token", "thinking"}:
            return self._text_frames(event)

        frames = []
        if end := self._close_block():
            frames.append(end)
        if part := self._data_part(event):
            frames.append(self._frame(part))
        return frames

    def _text_frames(self, event):
        """Append a token to the correct text/reasoning block."""
        kind = (
            "text"
            if event["type"] == "token" and event["who"] == "main"
            else "reasoning"
        )
        next_block = (kind, event["who"])
        frames = []

        if self.block != next_block:
            if end := self._close_block():
                frames.append(end)
            self.block = next_block
            self.block_id = uuid4().hex

        if not self.block_opened:
            self.held_whitespace += event["text"]
            if not self.held_whitespace.strip():
                return frames
            self.block_opened = True
            delta = self.held_whitespace
            frames.append(self._frame({"type": f"{kind}-start", "id": self.block_id}))
        else:
            delta = event["text"]

        frames.append(
            self._frame({"type": f"{kind}-delta", "id": self.block_id, "delta": delta})
        )
        return frames

    def _close_block(self):
        """Close the current visible block and reset all block state."""
        if self.block is None:
            return None

        kind = self.block[0]
        block_id = self.block_id
        was_opened = self.block_opened
        self.block = None
        self.block_id = None
        self.block_opened = False
        self.held_whitespace = ""

        if was_opened:
            return self._frame({"type": f"{kind}-end", "id": block_id})
        return None

    def _data_part(self, event):
        """Map a non-token event to one AI SDK part, if it is user-visible."""
        event_type = event["type"]

        if event_type == "tool_call":
            if event["name"] == self.PLAN_TOOL:
                self.plan_todos = self._plan_todos(event)
                return self._plan_part("running")
            return {
                "type": "tool-input-available",
                "toolCallId": event["id"],
                "toolName": event["name"],
                "input": event["args"],
            }

        if event_type == "tool_result":
            if event["name"] == self.PLAN_TOOL:
                return None
            if event["error"]:
                return {
                    "type": "tool-output-error",
                    "toolCallId": event["id"],
                    "errorText": event["error"],
                }
            return {
                "type": "tool-output-available",
                "toolCallId": event["id"],
                "output": event["result"][:TOOL_OUTPUT_LIMIT],
            }

        if event_type == "subagent":
            return {
                "type": "data-subagent",
                "id": event["id"],
                "data": {"name": event["name"], "status": event["status"]},
            }
        if event_type == "interrupt":
            self.interrupted = True
            return {
                "type": "data-interrupt",
                "id": event["id"],
                "data": {"id": event["id"], "value": event["value"]},
            }
        if event_type == "usage":
            return {"type": "data-usage", "data": event["usage"]}
        return None

    def _plan_part(self, lifecycle):
        """Return one replaceable plan part with an explicit turn lifecycle."""
        return {
            "type": "data-plan",
            "id": self.plan_id,
            "data": {"todos": self.plan_todos or [], "lifecycle": lifecycle},
        }

    @staticmethod
    def _frame(part):
        return f"data: {json.dumps(part)}\n\n"

    @staticmethod
    def _plan_todos(event):
        """Read a planning update without trusting model-generated arguments."""
        args = event.get("args")
        if not isinstance(args, dict):
            return []
        todos = args.get("todos")
        return todos if isinstance(todos, list) else []

    @staticmethod
    def _error_text(exc):
        """Return a safe client message while logs retain the real exception."""
        while isinstance(exc, BaseExceptionGroup):  # noqa: F821
            exc = exc.exceptions[0]
        if isinstance(exc, TimeoutError):
            return "The assistant reached its time limit. Please try again."
        return "The assistant could not complete this request. Please try again."


async def ai_sdk_frames(
    thread_id,
    text,
    workspace_id=None,
    resume=None,
    options=None,
    message_id=None,
    checkpoint_config=None,
):
    """Compatibility entry point for callers consuming the AI SDK stream."""
    stream = AiSdkEventStream(
        thread_id,
        text,
        workspace_id=workspace_id,
        resume=resume,
        options=options,
        message_id=message_id,
        checkpoint_config=checkpoint_config,
    )
    async for output in stream:
        yield output


# ---------------------------------------------------------------------------
# API base views
# ---------------------------------------------------------------------------


class AuthenticatedApiView(View):
    """Authenticate API requests and provide their shared response helpers."""

    async def dispatch(self, request, *args, **kwargs):
        request.user = await request.auser()
        if not request.user.is_authenticated:
            return self.error("login required", status=401)
        return await super().dispatch(request, *args, **kwargs)

    @staticmethod
    def json_body(request, *, allow_empty=False):
        if allow_empty and not request.body:
            return {}
        try:
            body = json.loads(request.body)
        except (TypeError, ValueError):
            raise ValueError("body must be JSON") from None
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    @staticmethod
    def error(message, *, status):
        return JsonResponse({"error": message}, status=status)


class OwnedThreadView(AuthenticatedApiView):
    """Shared ownership lookup for endpoints that require an existing thread."""

    @staticmethod
    async def get_thread(request, thread_id):
        return await Thread.objects.filter(id=thread_id, user=request.user).afirst()

    async def owned_thread_or_error(self, request, thread_id):
        thread = await self.get_thread(request, thread_id)
        if thread is None:
            return None, self.error("not found", status=404)
        return thread, None


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ChatTurn:
    thread_id: str
    text: str
    resume: Any
    action: str
    options: dict[str, Any]
    command: dict[str, Any] | None
    message_id: str | None
    target_message_id: str | None
    checkpoint_config: dict[str, Any] | None = None


class ChatView(AuthenticatedApiView):
    """POST /api/chat/ — validate, prepare, and stream one agent turn."""

    ACTIONS = frozenset({"send", "edit", "regenerate"})
    PERSISTED_OPTION_KEYS = ("model", "agent", "tools", "thinking", "plan")

    @staticmethod
    async def _workspace_id(user):
        workspace, _created = await UserWorkspace.objects.aget_or_create(user=user)
        await asyncio.to_thread(
            migrate_legacy_user_workspace,
            user.pk,
            workspace.id.hex,
        )
        return workspace.id.hex

    async def post(self, request):
        try:
            turn = self._parse_turn(request)
        except ValueError as exc:
            return self.error(str(exc), status=400)

        thread = await Thread.objects.filter(id=turn.thread_id).afirst()
        if thread is not None and thread.user_id != request.user.id:
            return self.error("not found", status=404)
        if thread is None and turn.action != "send":
            return self.error("not found", status=404)

        try:
            chat.reserve_chat_turn(turn.thread_id)
        except ThreadBusyError as exc:
            return self.error(str(exc), status=409)
        except RuntimeCapacityError as exc:
            response = self.error(str(exc), status=429)
            response["Retry-After"] = "5"
            return response
        except RuntimeBusyError as exc:
            return self.error(str(exc), status=503)

        try:
            await self._prepare_turn(turn)
            await self._save_thread(request, thread, turn)
            return self._stream_response(
                turn,
                await self._workspace_id(request.user),
            )
        except chat.MessageNotFound as exc:
            chat.finish_turn(turn.thread_id)
            return self.error(str(exc), status=404)
        except Exception:
            chat.finish_turn(turn.thread_id)
            raise

    @classmethod
    def _parse_turn(cls, request):
        body = cls.json_body(request)
        thread_id = body.get("thread_id") or body.get("id")
        if not isinstance(thread_id, str) or re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", thread_id
        ) is None:
            raise ValueError(
                "thread_id must be 1-64 letters, numbers, hyphens, or underscores"
            )

        text = cls._user_text(body)
        resume = body.get("resume")
        action = body.get("action") or "send"
        if action not in cls.ACTIONS:
            raise ValueError("unknown chat action")

        raw_options = body.get("options")
        options = validated_options({} if raw_options is None else raw_options)
        if mentions := cls._user_mentions(body):
            options["mentions"] = mentions

        command = composer.resolve_command(body.get("command"), text)
        message_id = cls._clean_message_id(cls._user_message_id(body))
        target_message_id = cls._clean_message_id(
            body.get("target_message_id"), field="target_message_id"
        )

        if action in {"edit", "regenerate"} and target_message_id is None:
            raise ValueError("target_message_id is required")
        if action != "regenerate" and not (text or resume is not None):
            raise ValueError("thread_id and message (or resume) are required")

        return _ChatTurn(
            thread_id=thread_id,
            text=text,
            resume=resume,
            action=action,
            options=options,
            command=command,
            message_id=message_id,
            target_message_id=target_message_id,
        )

    @staticmethod
    def _last_user_message(body):
        messages = body.get("messages")
        if not isinstance(messages, list):
            return None
        return next(
            (
                message
                for message in reversed(messages)
                if isinstance(message, dict) and message.get("role") == "user"
            ),
            None,
        )

    @classmethod
    def _user_text(cls, body):
        """Read ``message`` or text parts from the last AI SDK user message."""
        if body.get("message") is not None:
            text = body["message"]
            if not isinstance(text, str):
                raise ValueError("message must be a string")
            return text

        message = cls._last_user_message(body)
        if message is None:
            return ""
        parts = message.get("parts")
        if not isinstance(parts, list):
            return ""
        return "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text", ""), str)
        )

    @classmethod
    def _user_message_id(cls, body):
        """Read the browser message id retained in the LangGraph checkpoint."""
        if body.get("message_id") is not None:
            return body["message_id"]
        message = cls._last_user_message(body)
        return message.get("id") if message else None

    @staticmethod
    def _clean_message_id(value, *, field="message_id"):
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(
                f"{field} must be a non-empty string of at most 200 characters"
            )
        return value

    @staticmethod
    def _user_mentions(body):
        """Keep only known skill, agent, and tool mentions from this message."""
        mentions = body.get("mentions")
        if not isinstance(mentions, list) or not mentions:
            return []

        known = {(item["kind"], item["id"]) for item in composer.mentions()}
        return [
            {"kind": mention["kind"], "id": mention["id"]}
            for mention in mentions
            if isinstance(mention, dict)
            and mention.get("kind") in composer.MENTION_KINDS
            and isinstance(mention.get("id"), str)
            and (mention["kind"], mention["id"]) in known
        ]

    @staticmethod
    async def _prepare_turn(turn):
        """Branch edit/regeneration turns and attach the trusted command prompt."""
        if turn.action in {"edit", "regenerate"}:
            turn.checkpoint_config, original_text = await chat.branch_before_message(
                turn.thread_id, turn.target_message_id
            )
            if turn.checkpoint_config is None:
                await chat.delete_checkpoint_history(turn.thread_id)
            if turn.action == "regenerate":
                turn.text = original_text
            turn.message_id = turn.target_message_id

        # Regeneration has no text in its request body, so infer its original
        # slash command only after recovering the historical user message.
        if turn.command is None:
            turn.command = composer.resolve_command(None, turn.text)
        if turn.command is not None:
            turn.options["command"] = {
                "id": turn.command["id"],
                "prompt": turn.command["prompt"],
            }

    @classmethod
    async def _save_thread(cls, request, thread, turn):
        """Create/update thread metadata without persisting transient mentions."""
        saved_options = {
            key: value
            for key, value in turn.options.items()
            if key in cls.PERSISTED_OPTION_KEYS
        }
        if thread is None:
            return await Thread.objects.acreate(
                id=turn.thread_id,
                user=request.user,
                title=turn.text[:60],
                options=saved_options,
            )

        thread.title = thread.title or turn.text[:60]
        thread.options = saved_options
        await thread.asave()  # also bumps updated_at for sidebar ordering
        return thread

    @staticmethod
    def _stream_response(turn, workspace_id):
        response = StreamingHttpResponse(
            ai_sdk_frames(
                turn.thread_id,
                turn.text,
                workspace_id=workspace_id,
                resume=turn.resume,
                options=turn.options,
                message_id=turn.message_id,
                checkpoint_config=turn.checkpoint_config,
            ),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        response["x-vercel-ai-ui-message-stream"] = "v1"
        return response


class ConfigView(AuthenticatedApiView):
    """GET /api/config/ — return the authenticated user's composer catalog."""

    async def get(self, request):
        return JsonResponse(
            {
                "user": {"username": request.user.username},
                "models": model_choices(),
                "default_model": AUTO_MODEL,
                "runtime": self._runtime_status(request),
                **thaw(AGENT_UI),
                # Composer metadata is process-cached for fast model-call
                # routing. Restart the ASGI process after editing its config.
                "commands": composer.commands(),
                "mentions": composer.mentions(),
            }
        )

    @staticmethod
    def _runtime_status(request):
        status = agent_runtime.public_status()
        status["can_reload"] = bool(getattr(request.user, "is_staff", False))
        return status


class RuntimeView(AuthenticatedApiView):
    """Inspect or administratively reload the process-shared agent runtime."""

    async def get(self, request):
        return JsonResponse(ConfigView._runtime_status(request))

    async def post(self, request):
        if not request.user.is_staff:
            return self.error("administrator access required", status=403)
        try:
            await agent_runtime.reload_agent()
        except RuntimeBusyError as exc:
            return self.error(str(exc), status=409)
        except Exception:
            log.exception("deep-agent runtime reload failed")
            return self.error(
                "agent reload failed; check the server logs",
                status=503,
            )
        return JsonResponse(ConfigView._runtime_status(request))


class ThreadListView(AuthenticatedApiView):
    """List the user's threads or create an empty thread."""

    async def get(self, request):
        threads = [
            thread.as_dict()
            async for thread in Thread.objects.filter(user=request.user)
        ]
        return JsonResponse({"threads": threads})

    async def post(self, request):
        try:
            body = self.json_body(request, allow_empty=True)
            title = body.get("title", "")
            if not isinstance(title, str):
                raise ValueError("title must be a string")
        except ValueError as exc:
            return self.error(str(exc), status=400)

        thread = await Thread.objects.acreate(
            user=request.user,
            title=title[:200],
        )
        return JsonResponse(thread.as_dict(), status=201)


class ThreadView(OwnedThreadView):
    """Retrieve a thread or delete it together with its checkpoint history."""

    async def get(self, request, thread_id):
        thread, error = await self.owned_thread_or_error(request, thread_id)
        return error or JsonResponse(thread.as_dict())

    async def delete(self, request, thread_id):
        thread, error = await self.owned_thread_or_error(request, thread_id)
        if error:
            return error
        if not chat.try_start_turn(thread_id):
            return self.error("a turn is running on this thread", status=409)

        try:
            # History first: if it fails, the database row remains for retry.
            await chat.delete_checkpoint_history(thread_id)
            workspace_id = await ChatView._workspace_id(request.user)
            await asyncio.to_thread(
                delete_conversation_workspace,
                workspace_id,
                thread_id,
            )
            await thread.adelete()
        finally:
            chat.finish_turn(thread_id)
        return HttpResponse(status=204)


class ThreadMessagesView(OwnedThreadView):
    """Return a thread transcript as AI SDK UI messages."""

    async def get(self, request, thread_id):
        thread, error = await self.owned_thread_or_error(request, thread_id)
        if error:
            return error
        messages = await chat.get_history(thread_id)
        return JsonResponse({"thread": thread.as_dict(), "messages": messages})


class ThreadMessageView(OwnedThreadView):
    """Delete one user message and all messages generated after it."""

    async def delete(self, request, thread_id, message_id):
        thread, error = await self.owned_thread_or_error(request, thread_id)
        if error:
            return error
        if not chat.try_start_turn(thread_id):
            return self.error("a turn is running on this thread", status=409)

        try:
            messages = await chat.delete_message(thread_id, message_id)
            await thread.asave()  # move the changed thread in the sidebar
        except chat.MessageNotFound as exc:
            return self.error(str(exc), status=404)
        finally:
            chat.finish_turn(thread_id)
        return JsonResponse({"thread": thread.as_dict(), "messages": messages})
