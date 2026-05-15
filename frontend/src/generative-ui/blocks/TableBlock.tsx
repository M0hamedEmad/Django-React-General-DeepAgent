import { memo } from "react";
import type { PresentationBlock } from "../../types";

type Table = Extract<PresentationBlock, { type: "table" }>;
const INLINE_ROWS = 5;

export const TableBlock = memo(function TableBlock({ block, mode }: {
  block: Table;
  mode: "inline" | "workspace";
}) {
  if (!Array.isArray(block.columns) || !Array.isArray(block.rows)) return null;
  const rows = mode === "inline" ? block.rows.slice(0, INLINE_ROWS) : block.rows;
  const frame = mode === "inline"
    ? "overflow-hidden border-y border-slate-200"
    : "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_8px_24px_rgba(15,23,42,0.04)]";
  return (
    <section className="min-w-0">
      {block.title && <h3 className={mode === "inline" ? "mb-2 text-sm font-semibold text-slate-800" : "mb-3 text-base font-semibold text-slate-950"}>{block.title}</h3>}
      <div className={frame}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className={`border-b text-left text-xs ${mode === "inline" ? "border-slate-200 bg-slate-50 text-slate-500" : "border-emerald-100 bg-emerald-50/80 text-emerald-950/70"}`}>
              <tr>
                {block.columns.map((column, index) => (
                  <th key={index} className="whitespace-nowrap px-4 py-3 font-semibold">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex} className={mode === "inline" ? "border-b border-slate-100 last:border-0" : "border-b border-slate-100 transition-colors last:border-0 even:bg-slate-50/45 hover:bg-emerald-50/40"}>
                  {(Array.isArray(row) ? row : []).map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      className={`max-w-sm px-4 py-3 align-top leading-5 text-slate-700 ${cellIndex === 0 ? "font-medium text-slate-900" : ""} ${typeof cell === "number" ? "whitespace-nowrap text-right tabular-nums" : "whitespace-normal"}`}
                    >
                      {display(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
});

function display(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "number" ? value.toLocaleString() : String(value);
}
