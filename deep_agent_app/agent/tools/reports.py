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


def _validation_message(_: ValidationError) -> str:
    """Return one correction instruction instead of a full union error tree."""
    return (
        "Invalid present_report data. Use title, optional subtitle, and 1-20 blocks. "
        "Every block needs type: section, markdown, kpis, chart, table, status, or "
        "links. Correct the arguments and call present_report again."
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
