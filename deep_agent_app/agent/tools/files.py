"""Present validated conversation files to the authenticated user."""

from typing import Annotated

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deep_agent_app.agent.backend import (
    current_workspace_scope,
    resolve_conversation_file,
)


class PresentFileInput(BaseModel):
    """Arguments for one user-facing workspace file."""

    model_config = ConfigDict(extra="forbid")

    path: Annotated[
        str,
        Field(
            min_length=2,
            max_length=500,
            description=(
                "Absolute path inside the current conversation workspace, "
                "for example /sales-report.pdf."
            ),
        ),
    ]
    title: Annotated[
        str,
        Field(
            max_length=120,
            description="Optional concise title shown to the user.",
        ),
    ] = ""

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("path must start with /")
        return value


def _present_file(path: str, title: str = "") -> str:
    """Deliver one completed workspace file to the user.

    Call this only after the requested file has been created successfully. Do
    not present temporary files, helper scripts, caches, virtual environments,
    or dependencies unless the user explicitly asks for that exact file.
    """
    scope = current_workspace_scope()
    try:
        resolved = resolve_conversation_file(
            scope.workspace_id,
            scope.thread_id,
            path,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise ToolException(str(exc)) from exc
    label = title.strip() or resolved.name
    return f"File '{label}' is ready for the user."


def _validation_message(_: ValidationError) -> str:
    return (
        "Invalid present_file arguments. Use an absolute current-workspace path "
        "such as /report.pdf and an optional title of at most 120 characters."
    )


def _tool_error(error: ToolException) -> str:
    return (
        f"Invalid present_file path: {error}. Create the file in the current "
        "conversation workspace, then call present_file again."
    )


present_file = StructuredTool.from_function(
    func=_present_file,
    name="present_file",
    description=_present_file.__doc__,
    args_schema=PresentFileInput,
    handle_validation_error=_validation_message,
    handle_tool_error=_tool_error,
)


__all__ = ["PresentFileInput", "present_file"]
