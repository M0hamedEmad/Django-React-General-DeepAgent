import { AlertTriangle, RotateCcw } from "lucide-react";
import { Component, type ReactNode } from "react";

/** An error boundary. A bug in one part of the page — a chart, one message,
 *  the panel — shows a small notice in its place; everything else keeps
 *  working. With `reload`, the notice offers a page reload instead. */
export class Safe extends Component<
  { children: ReactNode; label?: string; fallback?: ReactNode; reload?: boolean },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error(`[${this.props.label ?? "ui"}]`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;
    const label = this.props.label ?? "This part";
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        <div className="flex items-center gap-2 font-medium">
          <AlertTriangle size={15} />
          {label} could not be shown
        </div>
        <div className="mt-1 break-words text-xs text-red-600/80">{describe(this.state.error)}</div>
        <button
          type="button"
          onClick={() => (this.props.reload ? location.reload() : this.setState({ error: null }))}
          className="mt-2 inline-flex items-center gap-1 rounded-full border border-red-300 bg-white px-3 py-1 text-xs hover:bg-red-100"
        >
          <RotateCcw size={12} />
          {this.props.reload ? "Reload the page" : "Try again"}
        </button>
      </div>
    );
  }
}

/** React's production build ships numbered errors; name the common ones. */
function describe(error: Error): string {
  const match = /Minified React error #(\d+)/.exec(error.message);
  if (!match) return error.message;
  const known: Record<string, string> = {
    "185": "a component kept updating itself (maximum update depth)",
    "31": "an object was rendered where text was expected",
    "310": "hooks were called in a different order",
  };
  return `React error #${match[1]}: ${known[match[1]] ?? `see react.dev/errors/${match[1]}`}`;
}
