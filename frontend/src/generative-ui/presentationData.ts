import type { Part, Presentation, PresentationBlock, Series } from "../types";

const GENERATIVE_UI_PARTS = new Set([
  "tool-present_ui",
  "tool-present_report",
  "tool-show_report",
]);

export type GenerativeUi =
  | { kind: "inline"; id: string; block: PresentationBlock | null; error?: string }
  | { kind: "report"; report: Presentation };

export function isGenerativeUiToolPart(part: Part): boolean {
  return GENERATIVE_UI_PARTS.has(part.type);
}

export function generativeUiTitle(part: Part): string {
  const input = isRecord(part.input) ? part.input : {};
  return typeof input.title === "string" && input.title.trim()
    ? input.title.trim()
    : part.type === "tool-present_ui"
      ? "Visual"
      : "Report";
}

/**
 * Tool arguments remain untrusted model output until the Python tool accepts
 * them. Only terminal tool parts may become UI.
 */
export function generativeUiFromToolPart(part: Part): GenerativeUi | null {
  if (!isGenerativeUiToolPart(part)) return null;
  if (part.state !== "output-available" && part.state !== "output-error") return null;

  const input = isRecord(part.input) ? part.input : {};
  const id = typeof part.toolCallId === "string" ? part.toolCallId : "generative-ui";
  const error = part.state === "output-error"
    ? typeof part.errorText === "string" && part.errorText.trim()
      ? part.errorText
      : "The visual could not be created."
    : undefined;

  // New calls are unambiguous: present_ui has one block and reports have
  // many. Old checkpoints remain readable, but report-sized present_ui calls
  // are promoted to the workspace instead of flooding the conversation.
  if (
    part.type === "tool-present_ui"
    && Object.prototype.hasOwnProperty.call(input, "block")
  ) {
    const block = normalizeInlineBlock(input.block);
    return {
      kind: "inline",
      id,
      block: block as PresentationBlock | null,
      ...(error ? { error } : {}),
    };
  }

  const blocks = Array.isArray(input.blocks) ? input.blocks : [];
  const legacyInlineBlock = blocks.length === 1
    ? normalizeInlineBlock(blocks[0])
    : null;
  if (
    part.type === "tool-present_ui"
    && input.placement !== "workspace"
    && legacyInlineBlock
    && isCompactInlineBlock(legacyInlineBlock)
  ) {
    return { kind: "inline", id, block: legacyInlineBlock, ...(error ? { error } : {}) };
  }

  const report: Presentation = {
    kind: "presentation",
    id,
    title: generativeUiTitle(part),
    blocks,
  };
  if (typeof input.subtitle === "string" && input.subtitle.trim()) {
    report.subtitle = input.subtitle.trim();
  }
  if (error) {
    report.error = error;
  } else if (!Array.isArray(input.blocks)) {
    report.error = "The report data has an invalid format.";
  }
  return { kind: "report", report };
}

export function reportFromToolPart(part: Part): Presentation | null {
  const content = generativeUiFromToolPart(part);
  return content?.kind === "report" ? content.report : null;
}

const BLOCK_TYPES = ["section", "markdown", "kpis", "chart", "table", "status", "links"] as const;

/** Convert validated current inputs and historical checkpoint shapes into one
 * canonical frontend contract. A malformed block stays visible as a scoped
 * workspace error instead of reaching a renderer and crashing React. */
export function normalizePresentationBlock(value: unknown): PresentationBlock | null {
  const block = unwrapNamedBlock(value, BLOCK_TYPES);
  if (!isRecord(block) || typeof block.type !== "string") return null;

  switch (block.type) {
    case "section": {
      if (!nonEmptyString(block.title) || !optionalString(block.description)) return null;
      return {
        type: "section",
        title: block.title.trim(),
        ...(block.description?.trim() ? { description: block.description.trim() } : {}),
      };
    }
    case "markdown": {
      // `text` is the format stored by reports created before this schema.
      const content = nonEmptyString(block.content)
        ? block.content
        : nonEmptyString(block.text)
          ? block.text
          : null;
      return content ? { type: "markdown", content } : null;
    }
    case "kpis": {
      if (!Array.isArray(block.items) || block.items.length === 0) return null;
      const items = block.items.map((item) => {
        if (!isRecord(item) || !nonEmptyString(item.label) || !nonEmptyString(item.value)) return null;
        const detail = typeof item.detail === "string"
          ? item.detail
          : typeof item.delta === "string"
            ? item.delta
            : "";
        const tone = isKpiTone(item.tone) ? item.tone : "neutral";
        return {
          label: item.label,
          value: item.value,
          ...(detail ? { detail } : {}),
          tone,
        };
      });
      return items.every((item) => item !== null)
        ? { type: "kpis", items: items as Extract<PresentationBlock, { type: "kpis" }>["items"] }
        : null;
    }
    case "chart": {
      if (!isChartKind(block.kind) || !stringArray(block.labels) || block.labels.length === 0 || !Array.isArray(block.series) || block.series.length === 0) return null;
      const series = block.series.map((item) => {
        if (!isRecord(item) || !nonEmptyString(item.name) || !Array.isArray(item.values)) return null;
        if (item.values.length !== block.labels.length || !item.values.every(numberOrNull)) return null;
        return { name: item.name, values: item.values as (number | null)[] };
      });
      if (series.some((item) => item === null)) return null;
      return {
        type: "chart",
        kind: block.kind,
        labels: block.labels,
        series: series as Series[],
        ...(typeof block.title === "string" && block.title ? { title: block.title } : {}),
      };
    }
    case "table": {
      if (!stringArray(block.columns) || block.columns.length === 0 || !Array.isArray(block.rows) || block.rows.length === 0) return null;
      const rows = block.rows.filter(Array.isArray);
      if (rows.length !== block.rows.length || rows.some((row) => row.length !== block.columns.length || !row.every(tableCell))) return null;
      return {
        type: "table",
        columns: block.columns,
        rows: rows as (string | number | null)[][],
        ...(typeof block.title === "string" && block.title ? { title: block.title } : {}),
      };
    }
    case "status": {
      if (!isStatusTone(block.tone) || !nonEmptyString(block.title) || !nonEmptyString(block.message)) return null;
      return { type: "status", tone: block.tone, title: block.title, message: block.message };
    }
    case "links": {
      if (!Array.isArray(block.items) || block.items.length === 0) return null;
      const items = block.items.map((item) => isRecord(item) && nonEmptyString(item.label) && nonEmptyString(item.url)
        ? { label: item.label, url: item.url }
        : null);
      return items.every((item) => item !== null)
        ? {
            type: "links",
            title: typeof block.title === "string" && block.title ? block.title : "Sources",
            items: items as { label: string; url: string }[],
          }
        : null;
    }
    case "link": {
      // Singular links were emitted by the original report tool.
      if (!nonEmptyString(block.url)) return null;
      return {
        type: "links",
        title: "Sources",
        items: [{ label: nonEmptyString(block.label) ? block.label : block.url, url: block.url }],
      };
    }
    default:
      return null;
  }
}

/** Match the server's narrow recovery for providers that represent a union as
 * `{table: {...}}` instead of `{type: "table", ...}`. */
function normalizeInlineBlock(value: unknown): PresentationBlock | null {
  const block = normalizePresentationBlock(
    unwrapNamedBlock(value, ["kpis", "chart", "table", "status"]),
  );
  return block && isInlineBlock(block) ? block : null;
}

function isCompactInlineBlock(value: unknown): boolean {
  const block = normalizeInlineBlock(value);
  if (!block) return false;
  if (block.type === "kpis") {
    return block.items.length <= 4;
  }
  if (block.type === "chart") {
    return block.labels.length <= 20 && block.series.length <= 3;
  }
  if (block.type === "table") {
    return block.columns.length <= 6 && block.rows.length <= 5;
  }
  return true;
}

function isInlineBlock(value: PresentationBlock): value is Extract<PresentationBlock, { type: "kpis" | "chart" | "table" | "status" }> {
  return value.type === "kpis" || value.type === "chart" || value.type === "table" || value.type === "status";
}

function unwrapNamedBlock(value: unknown, variants: readonly string[]): unknown {
  if (!isRecord(value) || "type" in value) return value;
  const names = variants.filter((name) => Object.prototype.hasOwnProperty.call(value, name));
  if (names.length !== 1) return value;
  const type = names[0];
  const payload = value[type];
  return isRecord(payload) ? { ...payload, type } : value;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim());
}

function optionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function numberOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function tableCell(value: unknown): value is string | number | null {
  return value === null || typeof value === "string" || (typeof value === "number" && Number.isFinite(value));
}

function isChartKind(value: unknown): value is "bar" | "line" | "pie" {
  return value === "bar" || value === "line" || value === "pie";
}

function isKpiTone(value: unknown): value is "neutral" | "positive" | "warning" | "negative" {
  return value === "neutral" || value === "positive" || value === "warning" || value === "negative";
}

function isStatusTone(value: unknown): value is "info" | "success" | "warning" | "error" {
  return value === "info" || value === "success" || value === "warning" || value === "error";
}

export function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
