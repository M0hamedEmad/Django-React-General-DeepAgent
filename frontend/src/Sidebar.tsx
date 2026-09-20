import { CheckCircle2, CircleAlert, File, LayoutDashboard, Loader2, LogOut, MessageSquarePlus, PanelLeft, RefreshCw, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { csrf } from "./api";
import type { IntegrationStatus, ThreadInfo, WorkspaceItem } from "./types";

export function Sidebar({ open, onToggle, threads, currentId, onOpen, onNew, onDelete, presentations, onOpenPresentation, username, integrations, canReload, reloading, onReload }: {
  open: boolean;
  onToggle: () => void;
  threads: ThreadInfo[];
  currentId: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  presentations: WorkspaceItem[];
  onOpenPresentation: (presentation: WorkspaceItem) => void;
  username: string;
  integrations: IntegrationStatus[];
  canReload: boolean;
  reloading: boolean;
  onReload: () => void;
}) {
  const [accountOpen, setAccountOpen] = useState(false);
  const account = useRef<HTMLDivElement>(null);
  const unavailable = integrations.filter((item) => item.status === "unavailable");
  const hasIssue = unavailable.length > 0;

  useEffect(() => {
    if (!accountOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!account.current?.contains(event.target as Node)) setAccountOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAccountOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [accountOpen]);

  if (!open) {
    return (
      <div className="flex w-12 flex-col items-center gap-1 border-r border-line bg-sidebar py-3">
        <button type="button" onClick={onToggle} title="Show sidebar" className="rounded-lg p-2 text-gray-600 hover:bg-gray-200">
          <PanelLeft size={18} />
        </button>
        <button type="button" onClick={onNew} title="New chat" className="rounded-lg p-2 text-gray-600 hover:bg-gray-200">
          <MessageSquarePlus size={18} />
        </button>
      </div>
    );
  }
  return (
    <div className="flex w-64 shrink-0 flex-col border-r border-line bg-sidebar">
      <div className="flex items-center gap-2 px-3 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500 text-white">
          <Sparkles size={14} />
        </div>
        <span className="flex-1 font-semibold">Assistant</span>
        <button type="button" onClick={onToggle} title="Hide sidebar" className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-200">
          <PanelLeft size={17} />
        </button>
      </div>

      <button
        type="button"
        onClick={onNew}
        className="mx-3 flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-sm font-medium hover:border-gray-300"
      >
        <MessageSquarePlus size={16} />
        New chat
      </button>

      <div className="mt-4 flex-1 overflow-y-auto px-2">
        <div className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-gray-400">Chats</div>
        {threads.length === 0 && <div className="px-2 py-2 text-sm text-gray-400">No chats yet</div>}
        {threads.map((t) => (
          <div
            key={t.id}
            className={`group flex items-center gap-1 rounded-lg pr-1 ${t.id === currentId ? "bg-surface-muted" : "hover:bg-surface-muted/70"}`}
          >
            <button type="button" onClick={() => onOpen(t.id)} className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-sm">
              {t.title || "New chat"}
            </button>
            <button
              type="button"
              onClick={() => onDelete(t.id)}
              title="Delete"
              className="rounded p-1 text-gray-400 opacity-0 hover:text-red-600 group-hover:opacity-100"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}

        {presentations.length > 0 && (
          <>
            <div className="mt-5 px-2 pb-1 text-xs font-medium uppercase tracking-wide text-gray-400">Workspace</div>
            {presentations.map((presentation) => (
              <button
                key={presentation.id}
                type="button"
                onClick={() => onOpenPresentation(presentation)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-gray-200/50"
              >
                {presentation.kind === "file"
                  ? <File size={15} className="shrink-0 text-emerald-600" />
                  : <LayoutDashboard size={15} className="shrink-0 text-emerald-600" />}
                <span className="truncate">{presentation.title}</span>
              </button>
            ))}
          </>
        )}
      </div>

      <div ref={account} className="relative border-t border-line p-2">
        {accountOpen && (
          <section role="dialog" aria-label="Connected tools" className="absolute right-2 bottom-full left-2 z-40 mb-2 rounded-xl border border-line bg-surface p-3 shadow-xl shadow-gray-900/10">
            <div className="flex items-start gap-2">
              <div className={`mt-0.5 ${hasIssue ? "text-red-600" : "text-emerald-600"}`}>
                {hasIssue ? <CircleAlert size={17} /> : <CheckCircle2 size={17} />}
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-gray-900">Connected tools</h2>
                <p className="mt-0.5 text-xs leading-5 text-gray-500">
                  {hasIssue
                    ? "Some company tools could not connect. General chat still works."
                    : integrations.length
                      ? "All company tools are available."
                      : "Connections load with the first message."}
                </p>
              </div>
              <button type="button" onClick={() => setAccountOpen(false)} aria-label="Close connection status" className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                <X size={14} />
              </button>
            </div>

            {integrations.length > 0 && (
              <div className="mt-3 space-y-1.5 border-t border-gray-100 pt-2.5">
                {integrations.map((item) => (
                  <div key={item.id} className="text-xs">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full ${statusColor(item.status)}`} />
                      <span className="min-w-0 flex-1 truncate font-medium text-gray-700">{item.id}</span>
                      <span className={item.status === "unavailable" ? "font-medium text-red-600" : "text-gray-400"}>{statusLabel(item.status)}</span>
                    </div>
                    {item.status === "unavailable" && (
                      <p className="mt-1 ml-4 leading-4 text-red-700/80">{item.message}</p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {canReload ? (
              <button
                type="button"
                onClick={onReload}
                disabled={reloading}
                className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-gray-900 px-3 py-2 text-xs font-medium text-white hover:bg-gray-800 disabled:cursor-wait disabled:opacity-60"
              >
                {reloading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {reloading ? "Reconnecting…" : "Reconnect tools and reload agent"}
              </button>
            ) : hasIssue ? (
              <p className="mt-3 border-t border-gray-100 pt-2.5 text-xs text-gray-500">Ask an administrator to reconnect the tools.</p>
            ) : null}
          </section>
        )}

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setAccountOpen((value) => !value)}
            aria-expanded={accountOpen}
            aria-haspopup="dialog"
            title={hasIssue ? "Connected tools need attention" : "Account and connected tools"}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1 py-1 text-left hover:bg-gray-200/70"
          >
            <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-300 text-xs font-semibold uppercase text-white">
              {username.slice(0, 1)}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm">{username}</span>
            {hasIssue && (
              <span className="h-2 w-2 shrink-0 rounded-full bg-red-500 ring-2 ring-red-100" aria-hidden="true" />
            )}
            {hasIssue && <span className="sr-only">Connected tools need attention</span>}
          </button>
          <form method="post" action="/accounts/logout/">
            <input type="hidden" name="csrfmiddlewaretoken" value={csrf()} />
            <button type="submit" title="Sign out" className="rounded-lg p-2 text-gray-500 hover:bg-gray-200">
              <LogOut size={16} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function statusColor(status: IntegrationStatus["status"]): string {
  if (status === "ready") return "bg-emerald-500";
  if (status === "unavailable") return "bg-red-500";
  if (status === "loading") return "bg-amber-400";
  return "bg-gray-300";
}

function statusLabel(status: IntegrationStatus["status"]): string {
  if (status === "ready") return "Available";
  if (status === "unavailable") return "Unavailable";
  if (status === "loading") return "Connecting";
  return "Not loaded";
}
