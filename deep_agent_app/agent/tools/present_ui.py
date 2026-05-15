"""Typed visual blocks and the single-block inline chat tool."""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    model_validator,
)


class UiModel(BaseModel):
    """Reject model-invented fields instead of silently ignoring bad UI data."""

    model_config = ConfigDict(extra="forbid")


class Series(UiModel):
    name: Annotated[
        str,
        Field(min_length=1, max_length=80, description="Chart legend label."),
    ]
    values: Annotated[
        list[float | None],
        Field(
            min_length=1,
            max_length=50,
            description=(
                "Numeric values aligned with the chart labels. Use null for a "
                "missing value; never put categories or qualitative text here."
            ),
        ),
    ]


class Kpi(UiModel):
    label: Annotated[str, Field(min_length=1, max_length=80)]
    value: Annotated[
        str,
        Field(
            min_length=1, max_length=80, description="Formatted value with its unit."
        ),
    ]
    detail: Annotated[
        str,
        Field(
            max_length=160,
            description="Optional context explaining what the value means.",
        ),
    ] = ""
    tone: Literal["neutral", "positive", "warning", "negative"] = "neutral"


class KpisBlock(UiModel):
    type: Literal["kpis"]
    items: Annotated[list[Kpi], Field(min_length=1, max_length=4)]


class SectionBlock(UiModel):
    type: Literal["section"]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(max_length=500)] = ""


class ChartBlock(UiModel):
    type: Literal["chart"]
    kind: Literal["bar", "line", "pie"]
    title: Annotated[str, Field(max_length=120)] = ""
    labels: Annotated[list[str], Field(min_length=1, max_length=50)]
    series: Annotated[
        list[Series],
        Field(
            min_length=1,
            max_length=6,
            description=(
                "Numeric series. Every series must have one value per label. "
                "Pie charts use exactly one series."
            ),
        ),
    ]

    @model_validator(mode="after")
    def validate_series(self):
        label_count = len(self.labels)
        if any(len(series.values) != label_count for series in self.series):
            raise ValueError("every chart series must have one value per label")
        if self.kind == "pie" and len(self.series) != 1:
            raise ValueError("pie charts require exactly one series")
        return self


class TableBlock(UiModel):
    type: Literal["table"]
    title: Annotated[str, Field(max_length=120)] = ""
    columns: Annotated[list[str], Field(min_length=1, max_length=12)]
    rows: Annotated[
        list[list[str | float | int | None]],
        Field(
            min_length=1,
            max_length=100,
            description=(
                "Rows aligned with columns. Use tables for text, categories, and "
                "qualitative values such as High, Medium, and Low."
            ),
        ),
    ]

    @model_validator(mode="after")
    def validate_rows(self):
        width = len(self.columns)
        if any(len(row) != width for row in self.rows):
            raise ValueError("every table row must have one value per column")
        return self


class StatusBlock(UiModel):
    type: Literal["status"]
    tone: Literal["info", "success", "warning", "error"] = "info"
    title: Annotated[str, Field(min_length=1, max_length=120)]
    message: Annotated[str, Field(min_length=1, max_length=1000)]


class MarkdownBlock(UiModel):
    type: Literal["markdown"]
    content: Annotated[
        str,
        Field(
            min_length=1,
            max_length=8000,
            description="Markdown narrative, insights, or a short executive summary.",
        ),
    ]


class LinkItem(UiModel):
    url: Annotated[HttpUrl, Field(description="An http or https document URL.")]
    label: Annotated[str, Field(min_length=1, max_length=120)]


class LinksBlock(UiModel):
    type: Literal["links"]
    title: Annotated[str, Field(max_length=120)] = "Sources"
    items: Annotated[list[LinkItem], Field(min_length=1, max_length=20)]


Block = Annotated[
    (
        SectionBlock
        | MarkdownBlock
        | KpisBlock
        | ChartBlock
        | TableBlock
        | StatusBlock
        | LinksBlock
    ),
    Field(discriminator="type"),
]

InlineBlock = Annotated[
    KpisBlock | ChartBlock | TableBlock | StatusBlock,
    Field(discriminator="type"),
]


class PresentUiInput(UiModel):
    """Arguments for one compact inline visual."""

    block: Annotated[
        KpisBlock | ChartBlock | TableBlock | StatusBlock,
        Field(
            discriminator="type",
            description=(
                "Exactly one compact chat block. Put the variant in `type`; do "
                "not nest the data under a `kpis`, `chart`, `table`, or `status` "
                "key. Limits: 4 KPIs, 20 chart labels and 3 series, or 6 table "
                "columns and 5 rows. Use present_report for multiple blocks or "
                "anything larger."
            ),
            json_schema_extra={
                "examples": [
                    {
                        "type": "kpis",
                        "items": [{"label": "Revenue", "value": "$12,400"}],
                    },
                    {
                        "type": "chart",
                        "kind": "bar",
                        "labels": ["Jan", "Feb"],
                        "series": [{"name": "Revenue", "values": [10, 12]}],
                    },
                    {
                        "type": "table",
                        "columns": ["Customer", "Status"],
                        "rows": [["Acme", "Active"]],
                    },
                    {
                        "type": "status",
                        "tone": "warning",
                        "title": "Needs attention",
                        "message": "Two invoices are overdue.",
                    },
                ]
            },
        ),
    ]

    @model_validator(mode="before")
    @classmethod
    def normalize_variant_wrapper(cls, value: Any) -> Any:
        """Accept the common ``block: {table: {...}}`` provider mistake."""
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        data["block"] = normalize_named_block(
            data.get("block"),
            ("kpis", "chart", "table", "status"),
        )
        return data

    @model_validator(mode="after")
    def validate_inline_size(self):
        """Turn oversize visuals into a recoverable tool-validation response."""
        _validate_inline_size(self.block)
        return self


def _present_ui(block: InlineBlock) -> str:
    """Show one compact visual inside chat when it improves scanning.

    Do not use for plain-text answers, reports, multiple charts, or multiple
    sections. After calling it, add at most one short insight and do not repeat
    the displayed values.
    """
    return "Displayed in chat. Do not repeat its data; add at most one short insight."


def _validation_message(_: ValidationError) -> str:
    """Give the model one actionable error instead of every union-branch error."""
    return (
        "Invalid present_ui block. Set block.type to kpis, chart, table, or status. "
        "KPIs require items; charts require kind, labels, and numeric series; "
        "tables require columns and rows; status requires title and message. "
        "Reduce oversized data or use present_report, then call the tool again."
    )


# An explicit args model preserves the discriminator. LangChain's inferred
# function schema flattened the nested Annotated metadata into an ``anyOf`` and
# some providers consequently invented ``block.table`` wrapper objects.
present_ui = StructuredTool.from_function(
    func=_present_ui,
    name="present_ui",
    description=_present_ui.__doc__,
    args_schema=PresentUiInput,
    handle_validation_error=_validation_message,
)


def _validate_inline_size(block: InlineBlock) -> None:
    """Keep accidental report-sized model output out of the conversation."""
    if isinstance(block, KpisBlock) and len(block.items) > 4:
        raise ValueError(
            "inline KPI blocks support at most 4 items; use present_report"
        )
    if isinstance(block, ChartBlock) and (
        len(block.labels) > 20 or len(block.series) > 3
    ):
        raise ValueError(
            "inline charts support at most 20 labels and 3 series; use present_report"
        )
    if isinstance(block, TableBlock) and (
        len(block.columns) > 6 or len(block.rows) > 5
    ):
        raise ValueError(
            "inline tables support at most 6 columns and 5 rows; use present_report"
        )


def normalize_named_block(value: Any, variants: tuple[str, ...]) -> Any:
    """Flatten one unambiguous ``{variant: payload}`` provider wrapper."""
    if not isinstance(value, Mapping) or "type" in value:
        return value
    names = [name for name in variants if name in value]
    if len(names) != 1:
        return value
    variant = names[0]
    payload = value[variant]
    if not isinstance(payload, Mapping):
        return value
    return {**payload, "type": variant}
