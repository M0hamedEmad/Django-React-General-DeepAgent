import type { ReactNode } from "react";

/** Color only tokens explicitly selected from the composer dropdown. */
export function PromptText({ text, command, mentions = [] }: {
  text: string;
  command?: string;
  mentions?: readonly string[];
}) {
  const tokens = /(^\/[\w-]+(?=\s|$))|(^|\s)(@[\w-]+(?:\/[\w-]+)*)/g;
  const selectedMentions = new Set(mentions);
  const parts: ReactNode[] = [];
  let cursor = 0;

  for (const match of text.matchAll(tokens)) {
    const token = match[1] ?? match[3];
    const start = match.index + (match[2]?.length ?? 0);
    if (start > cursor) parts.push(text.slice(cursor, start));
    const selected = token.startsWith("/")
      ? token.slice(1) === command
      : selectedMentions.has(token.slice(1));
    parts.push(selected ? (
      <span key={`${start}:${token}`} className="text-blue-600">
        {token}
      </span>
    ) : token);
    cursor = start + token.length;
  }

  if (cursor === 0) return text;
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
