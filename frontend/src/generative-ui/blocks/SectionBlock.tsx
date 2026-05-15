import { memo } from "react";
import type { PresentationBlock } from "../../types";

type Section = Extract<PresentationBlock, { type: "section" }>;

export const SectionBlock = memo(function SectionBlock({ block }: { block: Section }) {
  return (
    <header className="border-l-[3px] border-emerald-500 py-0.5 pl-4">
      <h2 className="text-lg font-semibold tracking-[-0.015em] text-slate-950 sm:text-xl">{block.title}</h2>
      {block.description && (
        <p className="mt-1.5 max-w-[75ch] text-sm leading-6 text-slate-500">{block.description}</p>
      )}
    </header>
  );
});
