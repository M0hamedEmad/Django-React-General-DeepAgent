import { ArrowUpRight } from "lucide-react";
import { memo } from "react";
import type { PresentationBlock } from "../../types";

type Links = Extract<PresentationBlock, { type: "links" }>;

export const LinksBlock = memo(function LinksBlock({ block }: { block: Links }) {
  return (
    <section className="border-t border-gray-200 pt-5">
      {block.title && <h3 className="mb-3 text-sm font-semibold text-gray-900">{block.title}</h3>}
      <ul className="flex flex-wrap gap-x-5 gap-y-2">
        {block.items.map((item, index) => {
          const url = safeUrl(item.url);
          return (
            <li key={`${item.url}:${index}`}>
              {url ? (
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 underline decoration-blue-700/25 underline-offset-4 hover:decoration-blue-700 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30"
                >
                  {item.label}
                  <ArrowUpRight size={13} aria-hidden="true" />
                </a>
              ) : (
                <span className="text-sm text-gray-400">{item.label}</span>
              )}
            </li>
          );
        })}
      </ul>
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
