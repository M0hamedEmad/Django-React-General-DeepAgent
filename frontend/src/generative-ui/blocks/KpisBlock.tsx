import { memo } from "react";
import type { PresentationBlock } from "../../types";
import { isRecord } from "../presentationData";

type Kpis = Extract<PresentationBlock, { type: "kpis" }>;

const TONE: Record<string, { accent: string; detail: string; value: string }> = {
  neutral: { accent: "bg-emerald-500", detail: "text-slate-500", value: "text-slate-950" },
  positive: { accent: "bg-emerald-500", detail: "text-emerald-700", value: "text-emerald-950" },
  warning: { accent: "bg-amber-500", detail: "text-amber-700", value: "text-amber-950" },
  negative: { accent: "bg-red-500", detail: "text-red-700", value: "text-red-950" },
};

export const KpisBlock = memo(function KpisBlock({ block, mode }: {
  block: Kpis;
  mode: "inline" | "workspace";
}) {
  if (!Array.isArray(block.items)) return null;
  const items = block.items.filter(isRecord);
  if (mode === "inline") {
    return (
      <div className="flex flex-wrap gap-y-3 border-y border-gray-200 py-3">
        {items.map((item, index) => {
          const tone = TONE[typeof item.tone === "string" ? item.tone : "neutral"] ?? TONE.neutral;
          return (
            <div key={index} className={`min-w-32 flex-1 ${index ? "border-l border-gray-200 pl-4" : "pr-4"}`}>
              <div className="truncate text-xs text-gray-500">{display(item.label)}</div>
              <div className={`mt-0.5 truncate text-xl font-semibold tracking-tight tabular-nums ${tone.value}`}>
                {display(item.value)}
              </div>
              {typeof item.detail === "string" && item.detail && (
                <div className={`mt-0.5 text-xs tabular-nums ${tone.detail}`}>
                  {item.detail}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  }
  return (
    <div className="grid overflow-hidden rounded-2xl border border-emerald-100 bg-white shadow-[0_8px_24px_rgba(15,23,42,0.045)] sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item, index) => {
        const tone = TONE[typeof item.tone === "string" ? item.tone : "neutral"] ?? TONE.neutral;
        return (
          <div key={index} className="relative min-w-0 border-b border-slate-100 px-5 py-5 last:border-b-0 sm:border-r sm:[&:nth-child(even)]:border-r-0 lg:border-b-0 lg:border-r lg:last:border-r-0 lg:[&:nth-child(even)]:border-r">
            <span className={`absolute inset-x-0 top-0 h-[3px] ${tone.accent}`} aria-hidden="true" />
            <div className="text-xs font-medium leading-5 text-slate-500">{display(item.label)}</div>
            <div className={`mt-1 text-2xl font-semibold tracking-[-0.025em] tabular-nums ${tone.value}`}>
              {display(item.value)}
            </div>
            {typeof item.detail === "string" && item.detail && (
              <div className={`mt-1.5 text-xs leading-5 ${tone.detail}`}>
                {item.detail}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
});

function display(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}
