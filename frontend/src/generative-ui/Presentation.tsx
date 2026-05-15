import { AlertTriangle, ArrowUpRight, ChevronRight, FileBarChart, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { Safe } from "../Safe";
import type { Part, Presentation, PresentationBlock } from "../types";
import { ChartBlock } from "./blocks/ChartBlock";
import { KpisBlock } from "./blocks/KpisBlock";
import { LinksBlock } from "./blocks/LinksBlock";
import { MarkdownBlock } from "./blocks/MarkdownBlock";
import { SectionBlock } from "./blocks/SectionBlock";
import { StatusBlock } from "./blocks/StatusBlock";
import { TableBlock } from "./blocks/TableBlock";
import {
  generativeUiFromToolPart,
  generativeUiTitle,
  isRecord,
  normalizePresentationBlock,
} from "./presentationData";

/** Render a generative-UI tool according to its contract. A chat visual stays
 * compact; a report stays a simple door into the shared workspace. */
export function GenerativeUiPart({ part, live, onOpen }: {
  part: Part;
  live: boolean;
  onOpen: (presentation: Presentation) => void;
}) {
  const content = generativeUiFromToolPart(part);
  if (!content) return <PendingUiPart part={part} live={live} />;

  if (content.kind === "report") {
    return <ReportCard report={content.report} onOpen={onOpen} />;
  }

  if (content.error || !content.block) {
    return <InlineError message={content.error ?? "The visual has an invalid format."} />;
  }

  return (
    <div className="my-1.5 max-w-3xl">
      <Safe label="This chat visual" fallback={<InvalidBlock data={content.block} />}>
        <BlockView block={content.block} mode="inline" />
      </Safe>
    </div>
  );
}

function PendingUiPart({ part, live }: { part: Part; live: boolean }) {
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-gray-500">
      <Loader2 size={14} className={live ? "animate-spin text-emerald-600" : "text-gray-400"} />
      <span className="truncate">
        {live ? `Preparing ${generativeUiTitle(part).toLowerCase()}…` : "Visual was not completed."}
      </span>
    </div>
  );
}

function ReportCard({ report, onOpen }: {
  report: Presentation;
  onOpen: (presentation: Presentation) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(report)}
      className="group/report flex w-full max-w-md items-center gap-3 rounded-xl border border-line bg-app/70 p-2.5 text-left outline-none transition-colors hover:border-gray-300 hover:bg-surface-muted focus-visible:ring-2 focus-visible:ring-emerald-500/25"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-gray-600 shadow-[0_1px_1px_rgba(15,23,42,0.04)]">
        <FileBarChart size={17} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-gray-900">{report.title}</div>
        <div className="mt-0.5 text-xs text-gray-500">
          {report.error ? "Report needs attention" : "Report · Open in workspace"}
        </div>
      </div>
      <ArrowUpRight size={15} className="mr-1 text-gray-400 transition-transform group-hover/report:-translate-y-0.5 group-hover/report:translate-x-0.5 group-hover/report:text-gray-600" />
    </button>
  );
}

/** A report reads as one ordered business document, not a dashboard of cards. */
export function PresentationView({ presentation }: { presentation: Presentation }) {
  const blocks = Array.isArray(presentation.blocks) ? presentation.blocks : [];
  return (
    <article className="report-document mx-auto w-full max-w-[1040px] pb-12">
      <header className="relative mb-10 overflow-hidden rounded-2xl border border-emerald-200/80 bg-emerald-50 px-6 py-6 shadow-[0_1px_2px_rgba(6,78,59,0.06)] sm:px-8 sm:py-7">
        <span className="absolute inset-y-0 left-0 w-1.5 bg-emerald-600" aria-hidden="true" />
        <h1 className="max-w-[26ch] text-2xl font-semibold tracking-[-0.03em] text-slate-950 sm:text-[32px] sm:leading-[1.16]">
          {presentation.title}
        </h1>
        {presentation.subtitle && (
          <p className="mt-2.5 max-w-[70ch] text-sm leading-6 text-emerald-950/65 sm:text-[15px]">{presentation.subtitle}</p>
        )}
      </header>
      {presentation.error ? (
        <PresentationError message={presentation.error} />
      ) : blocks.length ? (
        <div className="space-y-8">
          {blocks.map((rawBlock, index) => {
            const block = normalizePresentationBlock(rawBlock);
            return (
              <div key={index} className={`report-block min-w-0 ${block ? `report-block-${block.type}` : "report-block-invalid"}`}>
                {block ? (
                  <Safe label="This report block" fallback={<InvalidBlock data={rawBlock} />}>
                    <BlockView block={block} mode="workspace" />
                  </Safe>
                ) : (
                  <InvalidBlock data={rawBlock} />
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-sm text-gray-500">This report has no content.</div>
      )}
    </article>
  );
}

function BlockView({ block, mode }: {
  block: PresentationBlock;
  mode: "inline" | "workspace";
}) {
  if (!isRecord(block)) return <InvalidBlock data={block} />;
  switch (block.type) {
    case "section": return mode === "workspace" ? <SectionBlock block={block} /> : <InvalidBlock data={block} />;
    case "markdown": return mode === "workspace" ? <MarkdownBlock block={block} /> : <InvalidBlock data={block} />;
    case "kpis": return <KpisBlock block={block} mode={mode} />;
    case "chart": return <ChartBlock block={block} mode={mode} />;
    case "table": return <TableBlock block={block} mode={mode} />;
    case "status": return <StatusBlock block={block} mode={mode} />;
    case "links": return mode === "workspace" ? <LinksBlock block={block} /> : <InvalidBlock data={block} />;
    default: return <InvalidBlock data={block} />;
  }
}

function PresentationError({ message }: { message: string }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50/60 p-4 text-red-900">
      <AlertTriangle size={17} className="mt-0.5 shrink-0 text-red-600" />
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">Report could not be created</h3>
        <p className="mt-1 whitespace-pre-wrap text-sm leading-5 text-red-800/80">{message}</p>
      </div>
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <details role="alert" className="group/visual-error max-w-xl border-l border-gray-300 py-1 pl-3 text-sm text-gray-500">
      <summary className="flex cursor-pointer list-none items-center gap-2 outline-none hover:text-gray-700 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-gray-900/10">
        <AlertTriangle size={14} className="shrink-0 text-gray-400" />
        <span className="min-w-0 flex-1">Couldn’t show this visual.</span>
        <ChevronRight size={12} className="text-gray-400 transition-transform group-open/visual-error:rotate-90" />
      </summary>
      <p className="mt-1.5 pl-5 text-xs leading-5 text-gray-400">{message}</p>
    </details>
  );
}

function InvalidBlock({ data }: { data: unknown }) {
  return (
    <div role="alert" className="max-w-xl border-l border-gray-300 py-1 pl-3 text-sm text-gray-500">
      <div className="flex items-center gap-2">
        <AlertTriangle size={14} className="shrink-0 text-gray-400" />
        <span>Couldn’t show this visual.</span>
      </div>
      <details className="mt-1 pl-5 text-xs text-gray-400">
        <summary className="cursor-pointer outline-none hover:text-gray-600 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-gray-900/10">Technical details</summary>
        <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-gray-50 p-2.5 leading-5 whitespace-pre-wrap text-gray-500">{safeJson(data)}</pre>
      </details>
    </div>
  );
}

function safeJson(value: unknown): ReactNode {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "Unable to serialize this block.";
  }
}
