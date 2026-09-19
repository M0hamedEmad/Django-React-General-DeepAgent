"""Validated document-style report tool and legacy compatibility entrypoint."""

from collections.abc import Mapping
from typing import Annotated, Any

from langchain_core.tools import StructuredTool
from pydantic import Field, ValidationError, model_validator

from .present_ui import (
    Block,
    ChartBlock,
    Kpi,
    KpisBlock,
    LinkItem,
    LinksBlock,
    MarkdownBlock,
    SectionBlock,
    Series,
    StatusBlock,
    TableBlock,
    UiModel,
    normalize_named_block,
)


REPORT_BLOCK_TYPES = (
    "section",
    "markdown",
    "kpis",
    "chart",
    "table",
    "status",
    "links",
)


class PresentReportInput(UiModel):
    """Arguments for one ordered workspace report."""

    title: Annotated[
        str,
        Field(min_length=1, max_length=120, description="Short report title."),
    ]
    subtitle: Annotated[
        str,
        Field(
            max_length=180,
            description="Optional period, scope, or context shown below the title.",
        ),
    ] = ""
    blocks: Annotated[
        list[Block],
        Field(
            min_length=1,
            max_length=20,
            description=(
                "Ordered document blocks. Use section blocks for hierarchy, markdown "
                "for narrative, charts for numeric values, tables for detailed data, "
                "status for important notices, and links for sources."
            ),
        ),
    ]

    @model_validator(mode="before")
    @classmethod
    def normalize_variant_wrappers(cls, value: Any) -> Any:
        """Repair only the common unambiguous ``{table: {...}}`` shape."""
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        blocks = data.get("blocks")
        if isinstance(blocks, list):
            data["blocks"] = [
                normalize_named_block(block, REPORT_BLOCK_TYPES) for block in blocks
            ]
        return data


def _present_report(
    title: str,
    blocks: list[Block],
    subtitle: str = "",
) -> str:
    """Open a multi-section report in the workspace.

    Use for requested reports, multiple visuals, long or wide tables, documents,
    or two or more structured sections. Do not use for one compact chat visual.
    """
    return (
        f"Report '{title}' is ready. Give one short executive summary; "
        "do not repeat its rows or values."
    )


_BLOCK_FIELDS = {
    "section": "type, title, description",
    "markdown": "type, content",
    "kpis": "type, items",
    "chart": "type, kind, title, labels, series",
    "table": "type, title, columns, rows",
    "status": "type, tone, title, message",
    "links": "type, title, items",
}


def _validation_message(error: ValidationError) -> str:
    """Give bounded, input-free field guidance instead of a union error tree."""
    details = []
    for issue in error.errors(
        include_input=False, include_context=False, include_url=False
    ):
        loc = issue["loc"]
        kind = issue["type"]
        if loc[:1] == ("title",):
            detail = "title must be 1–120 characters"
        elif loc[:1] == ("subtitle",):
            detail = "subtitle must be at most 180 characters"
        elif loc[:1] == ("blocks",) and len(loc) == 1:
            detail = "blocks must contain 1–20 valid blocks"
        elif loc[:1] == ("blocks",) and len(loc) >= 2:
            index = loc[1]
            prefix = f"blocks[{index}]" if isinstance(index, int) else "blocks"
            variant = loc[2] if len(loc) >= 3 else None
            if kind in {"union_tag_invalid", "union_tag_not_found"}:
                detail = f"{prefix} needs a valid type: {', '.join(REPORT_BLOCK_TYPES)}"
            elif variant in _BLOCK_FIELDS:
                label = f"{prefix} ({variant})"
                field = loc[3] if len(loc) >= 4 else None
                if kind == "missing" and field in _BLOCK_FIELDS[variant].split(", "):
                    detail = f"{label} requires {field}"
                elif kind == "extra_forbidden":
                    detail = (
                        f"{label} has an unsupported field; allowed: "
                        f"{_BLOCK_FIELDS[variant]}"
                    )
                elif kind == "value_error" and variant == "table":
                    detail = f"{label} needs one row value per column"
                elif kind == "value_error" and variant == "chart":
                    detail = f"{label} needs one numeric value per label in each series"
                elif isinstance(field, str) and field in _BLOCK_FIELDS[variant].split(
                    ", "
                ):
                    detail = f"{label} has invalid {field}; allowed: {_BLOCK_FIELDS[variant]}"
                else:
                    detail = (
                        f"{label} has invalid values; allowed: {_BLOCK_FIELDS[variant]}"
                    )
            else:
                detail = f"{prefix} needs a valid type: {', '.join(REPORT_BLOCK_TYPES)}"
        else:
            detail = "use only title, optional subtitle, and blocks"
        if detail not in details:
            details.append(detail)
        if len(details) == 2:
            break
    correction = "; ".join(details) if details else "check title and blocks"
    return (
        f"Invalid present_report data: {correction}. "
        "Block types may be mixed; section is optional. Correct the arguments "
        "and call present_report again."
    )


present_report = StructuredTool.from_function(
    func=_present_report,
    name="present_report",
    description=_present_report.__doc__,
    args_schema=PresentReportInput,
    handle_validation_error=_validation_message,
)


def show_report(
    title: Annotated[
        str,
        Field(description="A short, specific title for the report workspace."),
    ],
    blocks: Annotated[
        list[Block],
        Field(
            description=(
                "Ordered report sections. Charts accept numeric series only; use "
                "a table or markdown block for categorical or qualitative values."
            )
        ),
    ],
) -> str:
    """Open an older structured report in the UI workspace."""
    return _present_report(title, blocks)


__all__ = [
    "Block",
    "ChartBlock",
    "Kpi",
    "KpisBlock",
    "LinkItem",
    "LinksBlock",
    "MarkdownBlock",
    "PresentReportInput",
    "SectionBlock",
    "Series",
    "StatusBlock",
    "TableBlock",
    "present_report",
    "show_report",
]
