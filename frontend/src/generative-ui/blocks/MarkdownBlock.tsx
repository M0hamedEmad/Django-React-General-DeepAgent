import { memo } from "react";
import { Markdown } from "../../Markdown";
import type { PresentationBlock } from "../../types";

type MarkdownData = Extract<PresentationBlock, { type: "markdown" }>;

export const MarkdownBlock = memo(function MarkdownBlock({ block }: { block: MarkdownData }) {
  return typeof block.content === "string" ? (
    <div className="report-markdown max-w-[78ch] text-[15px] leading-7 text-slate-700">
      <Markdown text={block.content} />
    </div>
  ) : null;
});
