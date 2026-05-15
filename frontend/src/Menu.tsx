import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Choice } from "./types";

/** A small dropdown: a pill button that opens a list with a check on the current choice. */
export function Menu({ icon, label, choices, value, onChange, title }: {
  icon?: ReactNode;
  label: string;
  choices: Choice[];
  value: string;
  onChange: (id: string) => void;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        title={title}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
      >
        {icon}
        <span className="max-w-40 truncate">{label}</span>
        <ChevronDown size={14} className="text-gray-400" />
      </button>
      {open && (
        <div className="absolute bottom-full right-0 z-20 mb-2 min-w-64 rounded-xl border border-line bg-surface p-1 shadow-lg shadow-gray-900/10">
          {choices.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => {
                onChange(c.id);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between gap-4 rounded-lg px-3 py-2 text-left text-sm hover:bg-gray-100"
            >
              <span className="min-w-0">
                <span className="block truncate">{c.label}</span>
                {c.detail && <span className="mt-0.5 block whitespace-nowrap text-xs text-gray-400">{c.detail}</span>}
              </span>
              {c.id === value && <Check size={14} className="shrink-0 text-emerald-600" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
