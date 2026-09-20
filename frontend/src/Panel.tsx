import { Maximize2, Minimize2, X } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

const MIN_WIDTH = 380;
const DEFAULT_MAX_WIDTH = 920;
const WIDTH_STORAGE_KEY = "workspace-panel-width";

type PanelProps = {
  title: string;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  onClose: () => void;
};

/** A reusable right-side workspace for presentations and future rich content. */
export function Panel({ title, icon, actions, children, onClose }: PanelProps) {
  const [fullscreen, setFullscreen] = useState(false);
  const [width, setWidth] = useState(readWidth);
  const drag = useRef<{ pointerId: number; startX: number; startWidth: number; currentWidth: number } | null>(null);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (fullscreen) setFullscreen(false);
      else onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen, onClose]);

  useEffect(() => () => releaseDocumentPointerStyles(), []);

  const resize = (event: PointerEvent<HTMLDivElement>) => {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const next = clampWidth(active.startWidth + active.startX - event.clientX);
    active.currentWidth = next;
    setWidth(next);
  };

  const finishResize = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    storeWidth(drag.current.currentWidth);
    drag.current = null;
    releaseDocumentPointerStyles();
  };

  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? 1 : -1;
    setWidth((current) => {
      const next = clampWidth(current + direction * 24);
      storeWidth(next);
      return next;
    });
  };

  const style = { "--workspace-panel-width": `${width}px` } as CSSProperties;
  return (
    <aside
      id="workspace-panel"
      aria-label={title}
      data-fullscreen={fullscreen}
      style={style}
      className="workspace-panel flex min-w-0 shrink-0 flex-col border-l border-line bg-app"
    >
      {!fullscreen && (
        <div
          role="separator"
          aria-label="Resize workspace panel"
          aria-orientation="vertical"
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={maximumWidth()}
          aria-valuenow={Math.round(width)}
          tabIndex={0}
          className="workspace-panel-resizer no-print absolute inset-y-0 left-0 z-10 w-2 -translate-x-1/2 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:bg-transparent hover:after:bg-emerald-400 focus-visible:after:bg-emerald-500"
          onDoubleClick={() => {
            const next = clampWidth(window.innerWidth * 0.46);
            setWidth(next);
            storeWidth(next);
          }}
          onKeyDown={resizeWithKeyboard}
          onPointerDown={(event) => {
            drag.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: width, currentWidth: width };
            event.currentTarget.setPointerCapture(event.pointerId);
            document.body.style.userSelect = "none";
            document.body.style.cursor = "col-resize";
          }}
          onPointerMove={resize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
        />
      )}

      <header className="no-print flex shrink-0 items-center gap-2 border-b border-line bg-surface px-4 py-3">
        {icon && <span className="text-emerald-600">{icon}</span>}
        <h2 className="min-w-0 flex-1 truncate font-semibold">{title}</h2>
        {actions}
        <PanelButton
          label={fullscreen ? "Exit full screen" : "Open full screen"}
          onClick={() => setFullscreen((value) => !value)}
        >
          {fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
        </PanelButton>
        <PanelButton label="Close panel" onClick={onClose}>
          <X size={17} />
        </PanelButton>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
    </aside>
  );
}

export function PanelButton({ label, onClick, children, pressed = false }: { label: string; onClick: () => void; children: ReactNode; pressed?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      className={`flex h-8 w-8 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/30 ${pressed ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100" : "text-gray-500 hover:bg-gray-100 hover:text-gray-800"}`}
    >
      {children}
    </button>
  );
}

function maximumWidth(): number {
  if (typeof window === "undefined") return DEFAULT_MAX_WIDTH;
  return Math.max(MIN_WIDTH, Math.min(DEFAULT_MAX_WIDTH, window.innerWidth - 360));
}

function clampWidth(width: number): number {
  return Math.min(maximumWidth(), Math.max(MIN_WIDTH, width));
}

function readWidth(): number {
  if (typeof window === "undefined") return 640;
  try {
    const stored = Number(window.localStorage.getItem(WIDTH_STORAGE_KEY));
    if (Number.isFinite(stored) && stored > 0) return clampWidth(stored);
  } catch {
    // Private browsing can block local storage; the default still works.
  }
  return clampWidth(window.innerWidth * 0.46);
}

function storeWidth(width: number) {
  try {
    window.localStorage.setItem(WIDTH_STORAGE_KEY, String(Math.round(width)));
  } catch {
    // Width persistence is optional.
  }
}

function releaseDocumentPointerStyles() {
  document.body.style.userSelect = "";
  document.body.style.cursor = "";
}
