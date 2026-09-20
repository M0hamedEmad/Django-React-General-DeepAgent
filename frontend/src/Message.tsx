import {
  AlertCircle, Bot, Brain, Check, CheckCircle2, ChevronRight, Circle, Copy, Globe, ListTodo, ListTree, Loader2, MessageCircleQuestion, PauseCircle, Pencil, RefreshCw, Sparkles, Trash2, Wrench, X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { FileArtifactPart } from "./artifacts/FileArtifact";
import { isFileArtifactPart } from "./artifacts/artifactData";
import { GenerativeUiPart } from "./generative-ui/Presentation";
import { isGenerativeUiToolPart, isRecord, reportFromToolPart } from "./generative-ui/presentationData";
import { InterruptCard } from "./Interrupt";
import { Markdown } from "./Markdown";
import { PromptText } from "./PromptText";
import type { ChatMessage, InterruptData, Part, PlanItem, PlanLifecycle, WorkspaceItem } from "./types";

export function MessageView({ message, threadId, now, isLast, streaming, onOpenPresentation, onAnswer, onEdit, onDelete, onRegenerate }: {
  message: ChatMessage;
  threadId: string;
  now: number;
  isLast: boolean;
  streaming: boolean;
  onOpenPresentation: (item: WorkspaceItem) => void;
  onAnswer: (interruptId: string, value: unknown, echo: string) => void;
  onEdit?: (text: string) => Promise<void> | void;
  onDelete?: () => Promise<void> | void;
  onRegenerate?: () => Promise<void> | void;
}) {
  const parts = message.parts as Part[];
  const text = parts.filter((part) => part.type === "text").map((part) => part.text ?? "").join("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [copied, setCopied] = useState(false);
  const createdAt = message.metadata?.created_at;
  const selectedCommand = message.metadata?.command;
  const selectedMentions = message.metadata?.mentions?.map((mention) => mention.id);

  const copy = async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard access can be denied outside HTTPS; the chat stays usable.
    }
  };

  if (message.role === "user") {
    if (editing) {
      const save = () => {
        const value = draft.trim();
        if (!value || value === text) {
          setEditing(false);
          return;
        }
        setEditing(false);
        void onEdit?.(value);
      };
      return (
        <div className="flex justify-end">
          <div className="w-full max-w-[80%] rounded-2xl border border-emerald-200 bg-surface p-2 shadow-sm">
            <textarea
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={2}
              className="max-h-48 min-h-16 w-full resize-none bg-transparent px-2 py-1 text-[15px] outline-none"
              aria-label="Edit message"
            />
            <div className="flex justify-end gap-1.5">
              <button type="button" onClick={() => { setDraft(text); setEditing(false); }} className="rounded-lg px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-100">
                Cancel
              </button>
              <button type="button" onClick={save} disabled={!draft.trim()} className="rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-40">
                Save and regenerate
              </button>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="group flex justify-end">
        <div className="relative max-w-[80%]">
          <div className="whitespace-pre-wrap rounded-[20px] bg-surface-muted px-4 py-2.5 text-[15px] leading-6 text-ink">
            <PromptText text={text} command={selectedCommand} mentions={selectedMentions} />
          </div>
          <div className={`absolute right-1 -bottom-6 flex h-6 items-center gap-0.5 transition-opacity ${confirmDelete ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"}`}>
            {confirmDelete ? (
              <div className="flex items-center gap-1 rounded-lg border border-red-100 bg-surface px-1.5 py-0.5 text-xs shadow-sm">
                <span className="px-1 text-gray-600">Delete from here?</span>
                <ActionButton label="Delete message" danger onClick={() => void onDelete?.()}><Check size={14} /></ActionButton>
                <ActionButton label="Cancel" onClick={() => setConfirmDelete(false)}><X size={14} /></ActionButton>
              </div>
            ) : (
              <>
                <MessageTime value={createdAt} now={now} />
                <ActionButton label={copied ? "Copied" : "Copy"} onClick={() => void copy()}>{copied ? <Check size={14} /> : <Copy size={14} />}</ActionButton>
                {onRegenerate && <ActionButton label="Regenerate response" onClick={() => void onRegenerate()}><RefreshCw size={14} /></ActionButton>}
                {onEdit && <ActionButton label="Edit message" onClick={() => { setDraft(text); setEditing(true); }}><Pencil size={14} /></ActionButton>}
                {onDelete && <ActionButton label="Delete message" danger onClick={() => setConfirmDelete(true)}><Trash2 size={14} /></ActionButton>}
              </>
            )}
          </div>
        </div>
      </div>
    );
  }
  const live = isLast && streaming;
  const active = isLast && !streaming;
  // Reports are artifacts attached to this response. Keep inline UI in the
  // model's stream order, but anchor every completed report after this
  // message's final text instead of wherever its tool call happened.
  const workspaceParts: Part[] = [];
  const contentParts: Part[] = [];
  for (const part of parts) {
    (isWorkspacePart(part) ? workspaceParts : contentParts).push(part);
  }
  const chunks = fold(contentParts);
  return (
    <div className="group flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-emerald-600">
        <Sparkles size={13} />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {chunks.map((chunk, i) =>
          chunk.kind === "part" ? (
            <PartView key={chunk.index} part={chunk.part} live={live} active={active} onOpenPresentation={onOpenPresentation} onAnswer={onAnswer} />
          ) : (
            <Activity
              key={chunk.index}
              steps={chunk.steps}
              live={live}
              running={live && i === chunks.length - 1}
              active={active}
              onOpenPresentation={onOpenPresentation}
              onAnswer={onAnswer}
            />
          ),
        )}
        {workspaceParts.length > 0 && (
          <div className="space-y-2 pt-1">
            {workspaceParts.map((part, index) => isFileArtifactPart(part) ? (
              <FileArtifactPart key={part.toolCallId ?? `file:${index}`} part={part} threadId={threadId} onOpen={onOpenPresentation} />
            ) : (
              <GenerativeUiPart key={part.toolCallId ?? `report:${index}`} part={part} live={live} onOpen={onOpenPresentation} />
            ))}
          </div>
        )}
        {!live && (text || onRegenerate) && (
          <div className="flex h-6 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <MessageTime value={createdAt} now={now} />
            {text && <ActionButton label={copied ? "Copied" : "Copy answer"} onClick={() => void copy()}>{copied ? <Check size={14} /> : <Copy size={14} />}</ActionButton>}
            {onRegenerate && <ActionButton label="Regenerate answer" onClick={() => void onRegenerate()}><RefreshCw size={14} /></ActionButton>}
          </div>
        )}
      </div>
    </div>
  );
}

function ActionButton({ label, danger = false, onClick, children }: {
  label: string;
  danger?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`flex h-6 w-6 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/30 ${danger ? "text-gray-400 hover:text-red-600" : "text-gray-400 hover:text-gray-800"}`}
    >
      {children}
    </button>
  );
}

function MessageTime({ value, now }: { value?: string; now: number }) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return (
    <time dateTime={value} title={date.toLocaleString()} className="mr-1 whitespace-nowrap text-[11px] tabular-nums text-gray-400">
      {relativeTime(date.getTime(), now)}
    </time>
  );
}

function relativeTime(timestamp: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 60) return "just now";
  const units: [number, string][] = [
    [31_536_000, "year"],
    [2_592_000, "month"],
    [86_400, "day"],
    [3_600, "hour"],
    [60, "minute"],
  ];
  for (const [size, label] of units) {
    if (seconds >= size) {
      const count = Math.floor(seconds / size);
      return `${count} ${label}${count === 1 ? "" : "s"} ago`;
    }
  }
  return "just now";
}

/* --- Folding the working steps ------------------------------------------ */

type Step = { part: Part; index: number };
type Chunk = { kind: "part"; part: Part; index: number } | { kind: "group"; steps: Step[]; index: number };

function isWorkspacePart(part: Part): boolean {
  if (isFileArtifactPart(part)) return true;
  return part.type === "tool-present_report"
    || part.type === "tool-show_report"
    || reportFromToolPart(part) !== null;
}

/** A working step: something the agent did on the way to an answer, as
 *  opposed to something it said or asked. A report card and a question
 *  are for the person, so they stay out of the fold. */
function isStep(part: Part): boolean {
  if (part.type === "reasoning" || part.type === "data-subagent") return true;
  return part.type.startsWith("tool-") && !isGenerativeUiToolPart(part);
}

/** Parts with nothing to show. Whitespace-only thinking is a model clearing
 *  its throat, not a thought; an empty text part is a block that has just
 *  opened. Neither should split a run of steps into two folds. */
function isHidden(part: Part): boolean {
  if (part.type === "reasoning" || part.type === "text") return !(part.text ?? "").trim();
  return !(part.type.startsWith("tool-") || part.type === "data-subagent" || part.type === "data-interrupt" || part.type === "data-plan");
}

/** Consecutive steps become one group; a lone step stays as it is. Keys are
 *  the index of a chunk's first part, which never moves — parts only append. */
function fold(parts: Part[]): Chunk[] {
  const out: Chunk[] = [];
  let run: Step[] = [];
  const flush = () => {
    // Even one internal step uses the same compact activity disclosure. This
    // keeps a lone reasoning or tool part from becoming a full-width widget.
    if (run.length > 0) out.push({ kind: "group", steps: run, index: run[0].index });
    run = [];
  };
  parts.forEach((part, index) => {
    if (isHidden(part)) return;
    if (isStep(part)) {
      run.push({ part, index });
    } else {
      flush();
      out.push({ kind: "part", part, index });
    }
  });
  flush();
  return out;
}

/** What a run of steps amounted to, for the fold's header. */
function summarize(parts: Part[]): string {
  const agents = new Set<string>();
  for (const p of parts) {
    if (p.type === "data-subagent" && p.data?.name) agents.add(String(p.data.name));
    if (p.type === "tool-task" && p.input?.subagent_type) agents.add(String(p.input.subagent_type));
  }
  const tools = parts.filter((p) => p.type.startsWith("tool-") && p.type !== "tool-task").length;
  const thoughts = parts.filter((p) => p.type === "reasoning").length;
  const bits = [
    agents.size ? `${agents.size} agent${agents.size === 1 ? "" : "s"}` : "",
    tools ? `${tools} tool${tools === 1 ? "" : "s"}` : "",
    thoughts ? `${thoughts} reasoning step${thoughts === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return bits.length ? bits.join(" · ") : `${parts.length} step${parts.length === 1 ? "" : "s"}`;
}

function planTodos(part: Part): PlanItem[] {
  return Array.isArray(part.data?.todos) ? part.data.todos : [];
}

function planLifecycle(part: Part, live: boolean): PlanLifecycle {
  const lifecycle = part.data?.lifecycle;
  if (["running", "finished", "interrupted", "failed"].includes(lifecycle)) {
    return lifecycle === "running" && !live ? "stopped" : lifecycle;
  }
  // Old checkpoints have no lifecycle. A historical turn is terminal; an
  // actively streaming one is still running.
  return live ? "running" : "finished";
}

/** The step in progress, for the fold's header while it works. */
function current(part: Part): { icon: ReactNode; label: string; summary: string } {
  if (part.type === "reasoning") return { icon: <Brain size={14} />, label: "Reasoning", summary: "" };
  if (part.type === "data-subagent") {
    return { icon: <Bot size={15} />, label: `${part.data?.name ?? "sub"} agent`, summary: SUBAGENT_STATUS[part.data?.status ?? ""]?.[0] ?? "" };
  }
  return describe(part);
}

function stepIsRunning(part: Part): boolean {
  if (part.type === "reasoning") return part.state === "streaming";
  if (part.type === "data-subagent") return part.data?.status === "started";
  return part.type.startsWith("tool-") && (part.state === "input-available" || part.state === "input-streaming");
}

/** A run of working steps, folded into one row: the step in progress while
 *  the agent works, what it all amounted to once it is done. Opening it
 *  shows every step, each still openable on its own. */
function Activity({ steps, live, running, active, onOpenPresentation, onAnswer }: {
  steps: Step[];
  live: boolean;
  running: boolean;
  active: boolean;
  onOpenPresentation: (presentation: WorkspaceItem) => void;
  onAnswer: (interruptId: string, value: unknown, echo: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const parts = steps.map((s) => s.part);
  const pending = parts.some((p) => p.type.startsWith("tool-") && (p.state === "input-available" || p.state === "input-streaming"));
  const failed = parts.some((p) => p.state === "output-error" || (p.type === "data-subagent" && ["error", "failed"].includes(p.data?.status)));
  const last = parts[parts.length - 1];
  const stepRunning = running && Boolean(last) && stepIsRunning(last);
  const status = stepRunning
    ? <ThinkingDots />
    : failed
      ? <AlertCircle size={14} className="text-red-500" />
      : pending
        ? <PauseCircle size={14} className="text-amber-600" />
        : null;
  const now = stepRunning ? current(last) : null;

  return (
    <div className="max-w-3xl">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="group/activity flex min-h-7 w-full items-center gap-1.5 text-left text-[13px] text-gray-500 outline-none hover:text-gray-800 focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-emerald-500/25"
      >
        <span className="text-gray-400">{now ? now.icon : <ListTree size={14} />}</span>
        <span className={stepRunning ? "thinking-shimmer font-medium" : "font-medium text-gray-600"}>
          {stepRunning ? "Thinking" : "Activity"}
        </span>
        <span className="min-w-0 flex-1 truncate text-gray-400">
          {now ? [now.label, now.summary].filter(Boolean).join(" · ") : summarize(parts)}
        </span>
        {status}
        <ChevronRight size={13} className={`text-gray-400 transition-transform group-hover/activity:text-gray-600 ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="ml-1.5 space-y-1.5 border-l border-gray-200 py-1.5 pl-4">
          {steps.map((s) => (
            <PartView key={s.index} part={s.part} live={live} active={active} onOpenPresentation={onOpenPresentation} onAnswer={onAnswer} />
          ))}
        </div>
      )}
    </div>
  );
}

/* --- One part --------------------------------------------------------- */

function PartView({ part, live, active, onOpenPresentation, onAnswer }: {
  part: Part;
  live: boolean;
  active: boolean;
  onOpenPresentation: (presentation: WorkspaceItem) => void;
  onAnswer: (interruptId: string, value: unknown, echo: string) => void;
}) {
  if (part.type === "text") return part.text ? <div className="max-w-[70ch]"><Markdown text={part.text} /></div> : null;
  if (part.type === "reasoning") return part.text?.trim() ? <Thinking text={part.text} streaming={live && part.state === "streaming"} /> : null;
  if (part.type === "data-plan") return <PlanCard part={part} live={live} />;
  if (part.type === "data-subagent") return <SubagentChip name={part.data?.name} status={part.data?.status} live={live} />;
  if (part.type === "data-interrupt") return <InterruptCard data={part.data as InterruptData} active={active} live={live} onAnswer={onAnswer} />;
  if (isGenerativeUiToolPart(part)) {
    return <GenerativeUiPart part={part} live={live} onOpen={onOpenPresentation} />;
  }
  if (part.type.startsWith("tool-")) return <ToolStep part={part} live={live} />;
  return null;
}

function PlanCard({ part, live }: { part: Part; live: boolean }) {
  const todos = planTodos(part);
  const lifecycle = planLifecycle(part, live);
  const completed = lifecycle === "finished"
    ? todos.length
    : todos.filter((todo) => todo.status === "completed").length;
  const currentTodo = todos.find((todo) => todo.status === "in_progress");
  const [open, setOpen] = useState(live && lifecycle === "running");

  useEffect(() => {
    setOpen(live && lifecycle === "running");
  }, [live, lifecycle]);

  if (!todos.length) return null;

  const summary = lifecycle === "finished"
    ? `${todos.length} step${todos.length === 1 ? "" : "s"} completed`
    : lifecycle === "running"
      ? currentTodo?.content ?? `${completed} of ${todos.length} completed`
      : `${completed} of ${todos.length} completed`;
  const stateLabel = lifecycle === "interrupted"
    ? "Paused"
    : lifecycle === "failed" || lifecycle === "stopped"
      ? "Stopped"
      : null;
  const status = lifecycle === "running"
    ? <ThinkingDots />
    : lifecycle === "finished"
      ? <CheckCircle2 size={14} className="text-emerald-600" />
      : lifecycle === "interrupted"
        ? <PauseCircle size={14} className="text-amber-600" />
        : <AlertCircle size={14} className="text-red-500" />;

  return (
    <section className="max-w-3xl border-y border-line" aria-label="Execution plan">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-9 w-full items-center gap-2 py-1.5 text-left text-[13px] outline-none hover:text-gray-900 focus-visible:ring-2 focus-visible:ring-emerald-500/25"
      >
        <ListTodo size={14} className="shrink-0 text-gray-500" />
        <span className="font-medium text-gray-700">Plan</span>
        {stateLabel && <span className="text-gray-400">{stateLabel}</span>}
        <span className="min-w-0 flex-1 truncate text-gray-400">{summary}</span>
        {status}
        <ChevronRight size={13} className={`shrink-0 text-gray-400 transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && <ol className="space-y-0.5 border-t border-gray-100 py-2">
        {todos.map((todo, index) => {
          const done = lifecycle === "finished" || todo.status === "completed";
          const active = lifecycle === "running" && todo.status === "in_progress";
          return (
            <li key={`${index}:${todo.content}`} className="flex items-start gap-2.5 py-1 text-[13px]">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden="true">
                {done ? (
                  <CheckCircle2 size={14} className="text-gray-400" />
                ) : active ? (
                  <span className="h-2.5 w-2.5 rounded-full border-[3px] border-emerald-600 bg-white" />
                ) : (
                  <Circle size={13} className="text-gray-300" />
                )}
              </span>
              <span className={done ? "text-gray-400 line-through decoration-gray-300" : active ? "font-medium text-gray-800" : "text-gray-500"}>
                {todo.content}
              </span>
            </li>
          );
        })}
      </ol>}
    </section>
  );
}

function Thinking({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1.5 py-1 text-left text-xs text-gray-500 outline-none hover:text-gray-800 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-500/25">
        <Brain size={13} />
        <span className={streaming ? "thinking-shimmer" : ""}>{streaming ? "Reasoning" : "View reasoning"}</span>
        <ChevronRight size={12} className={`ml-auto transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && <div className="max-h-72 overflow-y-auto py-1.5 text-[13px] leading-5 text-gray-500 whitespace-pre-wrap">{text}</div>}
    </div>
  );
}

function ThinkingDots() {
  return (
    <span className="flex shrink-0 items-center gap-0.5" aria-hidden="true">
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          className="h-1 w-1 animate-pulse rounded-full bg-gray-400 motion-reduce:animate-none"
          style={{ animationDelay: `${index * 160}ms` }}
        />
      ))}
    </span>
  );
}

const SUBAGENT_STATUS: Record<string, [string, ReactNode]> = {
  started: ["working", <Loader2 size={13} className="animate-spin" />],
  completed: ["done", <CheckCircle2 size={13} className="text-emerald-600" />],
  drained: ["done", <CheckCircle2 size={13} className="text-emerald-600" />],
  interrupted: ["waiting for you", <PauseCircle size={13} className="text-amber-600" />],
  error: ["failed", <AlertCircle size={13} className="text-red-600" />],
  failed: ["failed", <AlertCircle size={13} className="text-red-600" />],
};

/** One delegation. The server sends the same part id when it ends, so this
 *  chip is replaced in place: "working" becomes "done" where it stands. */
function SubagentChip({ name, status, live }: { name?: string; status?: string; live: boolean }) {
  // A disconnected or older stream may never deliver its terminal event.
  // Once the parent stream ends, a stale "started" state must not keep moving.
  const visibleStatus = status === "started" && !live ? "completed" : status ?? "";
  const [label, icon] = SUBAGENT_STATUS[visibleStatus] ?? [visibleStatus, null];
  return (
    <div className="flex items-center gap-1.5 py-1 text-xs text-gray-500">
      <Bot size={13} />
      <span className="font-medium">{name} agent</span> {label} {icon}
    </div>
  );
}

function describe(part: Part): { icon: ReactNode; label: string; summary: string } {
  const name = part.type.slice("tool-".length);
  const input = part.input ?? {};
  if (name === "task") return { icon: <Bot size={15} />, label: `Delegated to the ${input.subagent_type ?? "sub"} agent`, summary: input.description ?? "" };
  if (name === "internet_search") return { icon: <Globe size={15} />, label: "Searched the web", summary: input.query ?? "" };
  if (name === "ask_user") {
    const questions = Array.isArray(input.questions) ? input.questions : [];
    const summary = input.question ?? questions[0]?.question ?? "";
    return {
      icon: <MessageCircleQuestion size={15} />,
      label: questions.length > 1 ? `Asked you ${questions.length} questions` : "Asked you",
      summary,
    };
  }
  const summary = Object.entries(input)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return { icon: <Wrench size={15} />, label: name.replace(/_/g, " "), summary };
}

/** One tool call: what was called, with what, and what came back. */
function ToolStep({ part, live }: { part: Part; live: boolean }) {
  const [open, setOpen] = useState(false);
  const { icon, label, summary } = describe(part);
  const pending = part.state === "input-available" || part.state === "input-streaming";
  const status = pending
    ? live
      ? <Loader2 size={14} className="animate-spin text-gray-400" />
      : <PauseCircle size={14} className="text-amber-500" />
    : part.state === "output-error"
      ? <AlertCircle size={14} className="text-red-500" />
      : <CheckCircle2 size={14} className="text-emerald-600" />;
  const output = typeof part.output === "string" ? part.output : JSON.stringify(part.output, null, 2);
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 py-1 text-left text-[13px] text-gray-500 outline-none hover:text-gray-800 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-500/25">
        <span className="text-gray-500">{icon}</span>
        <span className="font-medium text-gray-700">{label}</span>
        {summary && <span className="min-w-0 flex-1 truncate text-gray-400">{summary}</span>}
        {!summary && <span className="flex-1" />}
        {status}
        <ChevronRight size={12} className={`text-gray-400 transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="space-y-2 py-1.5 pl-5 text-xs">
          <div>
            <div className="mb-1 font-medium text-gray-500">Input</div>
            <pre className="max-h-56 overflow-auto rounded-lg bg-gray-50 p-2.5 leading-5 whitespace-pre-wrap text-gray-600">{JSON.stringify(part.input, null, 2)}</pre>
          </div>
          {part.state === "output-error" && (
            <div>
              <div className="mb-1 font-medium text-red-600">Error</div>
              <pre className="overflow-x-auto rounded-lg bg-red-50 p-2.5 leading-5 whitespace-pre-wrap text-red-700">{part.errorText}</pre>
            </div>
          )}
          {part.state === "output-available" && (
            <div>
              <div className="mb-1 font-medium text-gray-500">Output</div>
              <pre className="max-h-72 overflow-auto rounded-lg bg-gray-50 p-2.5 leading-5 whitespace-pre-wrap text-gray-600">{output}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
