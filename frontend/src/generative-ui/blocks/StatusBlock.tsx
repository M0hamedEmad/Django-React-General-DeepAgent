import { AlertTriangle, CheckCircle2, CircleX, Info } from "lucide-react";
import { memo, type ReactNode } from "react";
import type { PresentationBlock } from "../../types";

type Status = Extract<PresentationBlock, { type: "status" }>;

const STYLE: Record<string, { workspace: string; inline: string; icon: ReactNode }> = {
  info: { workspace: "border-blue-200 bg-blue-50/60 text-blue-900", inline: "border-blue-500 text-blue-900", icon: <Info size={17} className="text-blue-600" /> },
  success: { workspace: "border-emerald-200 bg-emerald-50/60 text-emerald-900", inline: "border-emerald-500 text-emerald-900", icon: <CheckCircle2 size={17} className="text-emerald-600" /> },
  warning: { workspace: "border-amber-200 bg-amber-50/60 text-amber-950", inline: "border-amber-500 text-amber-950", icon: <AlertTriangle size={17} className="text-amber-600" /> },
  error: { workspace: "border-red-200 bg-red-50/60 text-red-900", inline: "border-red-500 text-red-900", icon: <CircleX size={17} className="text-red-600" /> },
};

export const StatusBlock = memo(function StatusBlock({ block, mode }: {
  block: Status;
  mode: "inline" | "workspace";
}) {
  const style = STYLE[block.tone] ?? STYLE.info;
  return (
    <section className={mode === "inline"
      ? `flex items-start gap-3 border-l-2 py-1 pl-3 ${style.inline}`
      : `flex items-start gap-3 rounded-xl border px-3.5 py-3 ${style.workspace}`
    }>
      <span className="mt-0.5 shrink-0">{style.icon}</span>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">{block.title}</h3>
        <p className="mt-0.5 text-sm leading-5 opacity-80">{block.message}</p>
      </div>
    </section>
  );
});
