import { useEffect, useRef, type ReactNode } from "react";

export type PopupItem = { key: string; icon: ReactNode; label: string; detail?: string; group?: string };

/** The list that opens above the message box for "/" and "@". The composer
 *  owns the highlighted row and the keys — the textarea has to keep focus —
 *  so this only draws the rows and keeps the highlighted one in view. */
export function Popup({ items, active, onPick, onHover, empty }: {
  items: PopupItem[];
  active: number;
  onPick: (index: number) => void;
  onHover: (index: number) => void;
  empty: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <div
      ref={ref}
      className="absolute inset-x-3 bottom-full z-30 mb-2 max-h-72 overflow-y-auto rounded-2xl border border-line bg-surface p-1.5 shadow-[0_12px_36px_rgba(28,39,54,0.12)]"
    >
      {items.length === 0 && <div className="px-3 py-2 text-sm text-gray-400">{empty}</div>}
      {items.map((item, i) => (
        <div key={item.key}>
          {item.group && (i === 0 || items[i - 1].group !== item.group) && (
            <div className="px-3 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-gray-400">{item.group}</div>
          )}
          <button
            type="button"
            data-index={i}
            onMouseDown={(e) => e.preventDefault()}
            onMouseEnter={() => onHover(i)}
            onClick={() => onPick(i)}
            className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm ${i === active ? "bg-gray-100" : ""}`}
          >
            <span className="shrink-0 text-gray-500">{item.icon}</span>
            <span className="shrink-0 font-medium text-gray-800">{item.label}</span>
            {item.detail && <span className="min-w-0 flex-1 truncate text-gray-500">{item.detail}</span>}
          </button>
        </div>
      ))}
    </div>
  );
}
