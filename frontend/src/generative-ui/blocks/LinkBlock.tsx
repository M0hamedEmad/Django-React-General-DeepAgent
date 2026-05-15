import { ExternalLink } from "lucide-react";
import { memo } from "react";
import type { PresentationBlock } from "../../types";

type Link = Extract<PresentationBlock, { type: "link" }>;

export const LinkBlock = memo(function LinkBlock({ block, mode }: {
  block: Link;
  mode: "inline" | "workspace";
}) {
  const url = safeUrl(block.url);
  if (!url) return <p className="text-sm text-red-700">This presentation contains an unsafe link.</p>;
  return (
    <section className="space-y-3">
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:underline"
      >
        <ExternalLink size={14} />
        {block.label || url}
      </a>
      {mode === "workspace" && (
        <iframe
          src={url}
          title={block.label || url}
          loading="lazy"
          referrerPolicy="no-referrer"
          sandbox=""
          className="h-[70vh] w-full rounded-xl border border-gray-200 bg-white"
        />
      )}
    </section>
  );
});

function safeUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = new URL(value, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}
