import { AlertTriangle, CheckCircle2, Code2, Download, Eye, File, LayoutDashboard, Loader2, Printer, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, loadOptions, newId, normalizeOptions, saveOptions } from "./api";
import { FileArtifactView } from "./artifacts/FileArtifact";
import { artifactUrl, hasSourceView } from "./artifacts/artifactData";
import { Chat } from "./Chat";
import { PresentationView } from "./generative-ui/Presentation";
import { Panel, PanelButton } from "./Panel";
import { Safe } from "./Safe";
import { Sidebar } from "./Sidebar";
import type { ChatMessage, Config, Options, RuntimeStatus, ThreadInfo, WorkspaceItem } from "./types";

/** A thread's address: /chat/<id>, the id being uuid4().hex as the server mints it. */
const THREAD_PATH = /^\/chat\/([0-9a-f]{32})\/?$/;
const DISMISSED_RUNTIME_WARNING = "dismissed-runtime-warning";

function threadFromPath(): string | null {
  return THREAD_PATH.exec(location.pathname)?.[1] ?? null;
}

/** Put the open thread in the address bar (/chat/ for a new one), so the
 *  link can be copied and the back button walks through the chats. */
function showPath(id: string | null) {
  const path = id ? `/chat/${id}` : "/chat/";
  if (location.pathname !== path) history.pushState(null, "", path);
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [threadId, setThreadId] = useState(() => threadFromPath() ?? newId());
  const [initial, setInitial] = useState<ChatMessage[] | null>(() => (threadFromPath() ? null : [])); // null while a thread loads
  const [notice, setNotice] = useState<{ message: string; tone: "success" | "warning" } | null>(null);
  const [panel, setPanel] = useState<WorkspaceItem | null>(null);
  const [sourceArtifactId, setSourceArtifactId] = useState<string | null>(null);
  const [presentations, setPresentations] = useState<WorkspaceItem[]>([]);
  const [options, setOptionsState] = useState<Options>(loadOptions);
  const [sidebar, setSidebar] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [dismissedFailure, setDismissedFailure] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(DISMISSED_RUNTIME_WARNING);
    } catch {
      return null;
    }
  });

  // The thread on screen, readable from callbacks registered once.
  const current = useRef(threadId);
  current.current = threadId;

  const setOptions = (o: Options) => {
    setOptionsState(o);
    saveOptions(o);
  };

  const clearFailureDismissal = () => {
    setDismissedFailure(null);
    try {
      sessionStorage.removeItem(DISMISSED_RUNTIME_WARNING);
    } catch {
      // Storage may be unavailable in private mode; in-memory dismissal works.
    }
  };

  const dismissFailure = (key: string) => {
    setDismissedFailure(key);
    try {
      sessionStorage.setItem(DISMISSED_RUNTIME_WARNING, key);
    } catch {
      // Storage may be unavailable in private mode; in-memory dismissal works.
    }
  };

  const refreshThreads = () => api<{ threads: ThreadInfo[] }>("/api/threads/").then((d) => setThreads(d.threads));
  const refreshRuntime = () =>
    api<RuntimeStatus>("/api/runtime/").then((runtime) => {
      setConfig((currentConfig) => currentConfig ? { ...currentConfig, runtime } : currentConfig);
      if (!runtime.integrations.some((item) => item.status === "unavailable")) {
        clearFailureDismissal();
      }
    });

  const reloadRuntime = async () => {
    setReloading(true);
    setNotice(null);
    try {
      const runtime = await api<RuntimeStatus>("/api/runtime/", { method: "POST" });
      setConfig((currentConfig) => currentConfig ? { ...currentConfig, runtime } : currentConfig);
      const failed = runtime.integrations.filter((item) => item.status === "unavailable");
      if (!failed.length) {
        setNotice({ message: "Agent and connected tools reloaded.", tone: "success" });
        clearFailureDismissal();
      }
    } catch (error) {
      setNotice({
        message: error instanceof Error ? error.message : "Could not reload the connected tools.",
        tone: "warning",
      });
    } finally {
      setReloading(false);
    }
  };

  const finishTurn = () => {
    void refreshThreads();
    void refreshRuntime();
  };

  /** A new, empty thread on screen. The address is the caller's business. */
  const fresh = () => {
    setThreadId(newId());
    setInitial([]);
    setPanel(null);
    setSourceArtifactId(null);
    setPresentations([]);
  };

  /** Open a thread from the server. An answer for a thread the user has
   *  since left is dropped; a thread that is gone (deleted, or somebody
   *  else's link) is said so, and a new one takes its place. */
  const load = async (id: string) => {
    setInitial(null);
    setThreadId(id);
    setPanel(null);
    setSourceArtifactId(null);
    setPresentations([]);
    try {
      const data = await api<{ thread: ThreadInfo; messages: ChatMessage[] }>(`/api/threads/${id}/messages/`);
      if (current.current === id) {
        setInitial(data.messages);
        if (Object.keys(data.thread.options ?? {}).length) {
          setOptions(normalizeOptions({ ...options, ...data.thread.options }));
        }
      }
    } catch {
      if (current.current !== id) return;
      setNotice({ message: "That chat is no longer available. A new chat is ready.", tone: "warning" });
      fresh();
      showPath(null);
    }
  };

  useEffect(() => {
    api<Config>("/api/config/").then((c) => {
      setConfig(c);
      setOptionsState((o) => {
        const next = {
          ...o,
          model: c.models.some((m) => m.id === o.model) ? o.model : c.default_model,
          agent: c.agents.some((a) => a.id === o.agent) ? o.agent : (c.agents[0]?.id ?? ""),
          tools: o.tools.filter((tool) => c.tools.some((choice) => choice.id === tool)),
        };
        saveOptions(next);
        return next;
      });
    });
    refreshThreads();

    const linked = threadFromPath();
    if (linked) load(linked);

    // Back and forward move between chats without a reload.
    const onPop = () => {
      const id = threadFromPath();
      if (id) {
        if (id !== current.current) load(id);
      } else {
        fresh();
      }
    };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const newChat = () => {
    setNotice(null);
    fresh();
    showPath(null);
  };

  const openThread = (id: string) => {
    if (id === threadId) return;
    setNotice(null);
    showPath(id);
    load(id);
  };

  const deleteThread = async (id: string) => {
    await api(`/api/threads/${id}/`, { method: "DELETE" });
    if (id === threadId) newChat();
    refreshThreads();
  };

  const unavailable = config?.runtime.integrations.filter(
    (item) => item.status === "unavailable",
  ) ?? [];
  const failureKey = unavailable.map((item) => item.id).sort().join("|");
  const showFailure = Boolean(failureKey && dismissedFailure !== failureKey);
  const sourceVisible = panel?.kind === "file" && sourceArtifactId === panel.id;

  const closePanel = () => {
    setPanel(null);
    setSourceArtifactId(null);
  };

  const openWorkspaceItem = (item: WorkspaceItem) => {
    setPanel(item);
    setSourceArtifactId(null);
  };

  return (
    <div className="flex h-full bg-app text-ink">
      <Sidebar
        open={sidebar}
        onToggle={() => setSidebar((s) => !s)}
        threads={threads}
        currentId={threadId}
        onOpen={openThread}
        onNew={newChat}
        onDelete={deleteThread}
        presentations={presentations}
        onOpenPresentation={openWorkspaceItem}
        username={config?.user.username ?? ""}
        integrations={config?.runtime.integrations ?? []}
        canReload={config?.runtime.can_reload ?? false}
        reloading={reloading}
        onReload={() => void reloadRuntime()}
      />
      <main className="flex min-w-0 flex-1 flex-col bg-canvas">
        <div className="pointer-events-none fixed top-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
          {showFailure && (
            <div role="alert" className="pointer-events-auto flex items-start gap-2.5 rounded-xl border border-red-200 bg-surface px-3.5 py-3 text-sm shadow-lg shadow-gray-900/10">
              <AlertTriangle size={17} className="mt-0.5 shrink-0 text-red-600" />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-gray-900">Connected tools unavailable</p>
                <p className="mt-0.5 text-gray-600">
                  {unavailable.map((item) => item.id).join(", ")} could not connect. General chat still works.
                </p>
              </div>
              <button type="button" onClick={() => dismissFailure(failureKey)} title="Dismiss" aria-label="Dismiss warning" className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                <X size={14} />
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className={`pointer-events-auto flex items-center gap-2.5 rounded-xl border bg-surface px-3.5 py-3 text-sm text-gray-700 shadow-lg shadow-gray-900/10 ${notice.tone === "success" ? "border-emerald-200" : "border-amber-200"}`}>
              {notice.tone === "success"
                ? <CheckCircle2 size={17} className="shrink-0 text-emerald-600" />
                : <AlertTriangle size={17} className="shrink-0 text-amber-600" />}
              <span className="min-w-0 flex-1">{notice.message}</span>
              <button type="button" onClick={() => setNotice(null)} title="Dismiss" aria-label="Dismiss message" className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                <X size={14} />
              </button>
            </div>
          )}
        </div>
        <div className="min-h-0 flex-1">
          {config && initial ? (
            <Safe label="The chat">
              <Chat
                key={threadId}
                threadId={threadId}
                initial={initial}
                options={options}
                setOptions={setOptions}
                config={config}
                onOpenPresentation={openWorkspaceItem}
                onPresentations={setPresentations}
                // The first message on a new chat gives it an address.
                onTurnStart={() => showPath(threadId)}
                onTurnEnd={finishTurn}
              />
            </Safe>
          ) : (
            <div className="flex h-full items-center justify-center text-gray-400">
              <Loader2 className="animate-spin" />
            </div>
          )}
        </div>
      </main>
      {panel && (
        <Safe label="The workspace panel">
          <Panel
            title={panel.title}
            icon={panel.kind === "file" ? <File size={18} /> : <LayoutDashboard size={18} />}
            actions={panel.kind === "file" ? (
              <>
                {hasSourceView(panel.path) && (
                  <PanelButton
                    label={sourceVisible ? "View preview" : "View source"}
                    pressed={sourceVisible}
                    onClick={() => setSourceArtifactId(sourceVisible ? null : panel.id)}
                  >
                    {sourceVisible ? <Eye size={17} /> : <Code2 size={17} />}
                  </PanelButton>
                )}
                <a href={artifactUrl(panel, true)} download title="Download file" aria-label="Download file" className="flex h-8 w-8 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 hover:text-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/30">
                  <Download size={17} />
                </a>
              </>
            ) : (
              <PanelButton label="Print or save as PDF" onClick={() => window.print()}>
                <Printer size={17} />
              </PanelButton>
            )}
            onClose={closePanel}
          >
            <Safe label={panel.kind === "file" ? "This file" : "This presentation"}>
              {panel.kind === "file"
                ? <FileArtifactView artifact={panel} source={sourceVisible} />
                : <PresentationView presentation={panel} />}
            </Safe>
          </Panel>
        </Safe>
      )}
    </div>
  );
}
