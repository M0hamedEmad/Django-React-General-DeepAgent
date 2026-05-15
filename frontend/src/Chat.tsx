import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { AlertCircle, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, csrf } from "./api";
import { Composer } from "./Composer";
import { reportFromToolPart } from "./generative-ui/presentationData";
import { MessageView } from "./Message";
import { Safe } from "./Safe";
import { Suggestions } from "./Suggestions";
import type { ChatMessage, Config, MentionRef, Options, Part, Presentation } from "./types";

export function Chat({ threadId, initial, options, setOptions, config, onOpenPresentation, onPresentations, onTurnStart, onTurnEnd }: {
  threadId: string;
  initial: ChatMessage[];
  options: Options;
  setOptions: (options: Options) => void;
  config: Config;
  onOpenPresentation: (presentation: Presentation) => void;
  onPresentations: (presentations: Presentation[]) => void;
  onTurnStart: () => void;
  onTurnEnd: () => void;
}) {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const [draft, setDraft] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [turnTiming, setTurnTiming] = useState<TurnTiming | null>(null);
  const activeTurnStartedAt = useRef<number | null>(null);
  const scrollArea = useRef<HTMLDivElement>(null);
  const followOutput = useRef(true);

  const beginTurn = () => {
    const startedAt = Date.now();
    // A new message is an explicit request to return to the live edge. During
    // the response, scrolling upward turns this off until the user returns.
    followOutput.current = true;
    activeTurnStartedAt.current = startedAt;
    setTurnTiming({ startedAt });
    onTurnStart();
  };

  const endTurn = () => {
    const startedAt = activeTurnStartedAt.current;
    if (startedAt === null) return;
    activeTurnStartedAt.current = null;
    setTurnTiming({ startedAt, endedAt: Date.now() });
    onTurnEnd();
  };

  // One transport per thread. The body is our own shape: the new message,
  // the thread, the composer settings, and `resume` when answering an interrupt.
  const transport = useMemo(
    () =>
      new DefaultChatTransport<ChatMessage>({
        api: "/api/chat/",
        prepareSendMessagesRequest: ({ id, messages, body }) => {
          const last = messages[messages.length - 1];
          const text =
            last?.role === "user" ? (last.parts as Part[]).filter((p) => p.type === "text").map((p) => p.text).join("") : "";
          return {
            headers: { "X-CSRFToken": csrf() },
            body: {
              thread_id: id,
              message: text,
              message_id: last?.role === "user" ? last.id : undefined,
              options: optionsRef.current,
              ...(body ?? {}),
            },
          };
        },
      }),
    [threadId],
  );

  const { messages, setMessages, sendMessage, regenerate, status, stop, error } = useChat<ChatMessage>({
    id: threadId,
    messages: initial,
    transport,
    onFinish: endTurn,
    onError: endTurn,
    // Re-render at most every 50 ms while streaming, not on every token.
    experimental_throttle: 50,
  });

  const busy = status === "submitted" || status === "streaming";
  const empty = messages.length === 0;
  const lastMessage = messages[messages.length - 1];
  const assistantHasStarted = lastMessage?.role === "assistant" && (lastMessage.parts as Part[]).some((part) => {
    if (part.type === "text" || part.type === "reasoning") return Boolean(part.text?.trim());
    return part.type.startsWith("tool-") || ["data-plan", "data-subagent", "data-interrupt"].includes(part.type);
  });

  // One clock for the conversation, rather than one interval per message.
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const element = scrollArea.current;
    if (!element || !followOutput.current) return;
    element.scrollTop = element.scrollHeight;
  }, [messages, busy]);

  // Reports live in tool calls. Inline visuals belong only to their message;
  // they never enter the workspace collection.
  //
  // The app is told about them only when the set changes — never once per
  // streamed token. A state update scheduled from an effect on every commit
  // counts as a "nested update" in React, and a long, fast stream (an MCP
  // turn with thinking) reaches its limit of 50: React error #185.
  const presented = useRef("");
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    const reports = collectReports(messages);
    const key = reports.map((item) => item.id).join(",");
    if (key === presented.current) return;
    presented.current = key;
    onPresentations(reports);
    if (seen.current === null) {
      seen.current = new Set(reports.map((item) => item.id));
      return;
    }
    for (const report of reports) {
      if (!seen.current.has(report.id)) {
        seen.current.add(report.id);
        onOpenPresentation(report);
      }
    }
  }, [messages]);

  // Mentions travel beside the message, not inside the options: they are
  // about this one message, and the options are remembered across sessions.
  const send = (text: string, mentions: MentionRef[], command?: string) => {
    beginTurn();
    const body = {
      ...(mentions.length ? { mentions } : {}),
      ...(command ? { command } : {}),
    };
    sendMessage(
      { text, metadata: messageMetadata(mentions, command) },
      Object.keys(body).length ? { body } : undefined,
    );
  };
  const answer = (interruptId: string, value: unknown, echo: string) => {
    beginTurn();
    sendMessage(
      { text: echo, metadata: messageMetadata() },
      // LangGraph needs an id -> answer map whenever parallel branches have
      // more than one pending interrupt. Always using that form also works
      // for one question and keeps this path free of global/current state.
      { body: { resume: { [interruptId]: value } } },
    );
  };

  const editMessage = (messageId: string, text: string) => {
    beginTurn();
    return sendMessage(
      { text, messageId, metadata: messageMetadata() },
      { body: { action: "edit", target_message_id: messageId } },
    );
  };

  const regenerateMessage = (assistantId: string, userId: string) => {
    beginTurn();
    return regenerate({
      messageId: assistantId,
      body: { action: "regenerate", target_message_id: userId },
    });
  };

  const deleteMessage = async (messageId: string) => {
    const data = await api<{ messages: ChatMessage[] }>(
      `/api/threads/${threadId}/messages/${encodeURIComponent(messageId)}/`,
      { method: "DELETE" },
    );
    setMessages(data.messages);
    onTurnEnd();
  };

  return (
    <div className="flex h-full flex-col bg-canvas">
      {!empty && (
        <div
          ref={scrollArea}
          className="min-h-0 flex-1 overflow-y-auto"
          onScroll={(event) => {
            const element = event.currentTarget;
            followOutput.current = isNearBottom(element);
          }}
        >
          <div className="mx-auto w-full max-w-4xl space-y-7 px-4 pt-8 pb-6 sm:px-6">
            {messages.map((m, i) => {
              // The AI SDK adds an empty assistant message before the first
              // stream part. The turn timer below owns that waiting state, so
              // do not render a second avatar/Thinking placeholder here.
              if (busy && !assistantHasStarted && i === messages.length - 1 && m.role === "assistant") {
                return null;
              }
              const userId = m.role === "assistant" ? precedingUserId(messages, i) : undefined;
              const responseId = m.role === "user" ? followingAssistantId(messages, i) : undefined;
              return (
                <Safe key={m.id} label="This message">
                  <MessageView
                    message={m}
                    now={now}
                    isLast={i === messages.length - 1}
                    streaming={busy}
                    onOpenPresentation={onOpenPresentation}
                    onAnswer={answer}
                    onEdit={m.role === "user" && !busy ? (text) => editMessage(m.id, text) : undefined}
                    onDelete={m.role === "user" && !busy ? () => deleteMessage(m.id) : undefined}
                    onRegenerate={
                      !busy && m.role === "assistant" && userId
                        ? () => regenerateMessage(m.id, userId)
                        : !busy && m.role === "user" && responseId
                          ? () => regenerateMessage(responseId, m.id)
                          : undefined
                    }
                  />
                </Safe>
              );
            })}
            {error && (
              <div role="alert" className="ml-10 flex items-start gap-2 border-l-2 border-red-300 py-1 pl-3 text-sm text-gray-600">
                <AlertCircle size={15} className="mt-0.5 shrink-0 text-red-500" />
                <span>{error.message}</span>
              </div>
            )}
            {turnTiming && <TurnDuration timing={turnTiming} showAvatar={busy && !assistantHasStarted} />}
          </div>
        </div>
      )}

      <div className={`mx-auto w-full max-w-4xl px-4 transition-all duration-500 sm:px-6 ${empty ? "my-auto" : "pb-4"}`}>
        {empty && (
          <div className="mb-8 flex items-center justify-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500 text-white shadow-[0_0_0_6px_rgba(16,185,129,0.15)]">
              <Sparkles size={20} />
            </div>
            <h1 className="text-3xl font-medium tracking-tight">Your company assistant</h1>
          </div>
        )}
        <Composer
          draft={draft}
          setDraft={setDraft}
          onSend={send}
          onStop={() => {
            stop();
            endTurn();
          }}
          busy={busy}
          options={options}
          setOptions={setOptions}
          config={config}
          hero={empty}
        />
        {empty && <Suggestions commands={config.commands.filter((c) => c.placement === "hero")} onPick={setDraft} />}
        {!empty && <p className="mt-2 text-center text-xs text-gray-400">The assistant can make mistakes. Verify important results against their source.</p>}
      </div>
    </div>
  );
}

const LIVE_EDGE_DISTANCE = 96;

function isNearBottom(element: HTMLDivElement): boolean {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= LIVE_EDGE_DISTANCE;
}

type TurnTiming = { startedAt: number; endedAt?: number };

/** One clock for the active turn. It starts before the request so agent and
 * integration startup time is visible, then freezes when the stream ends. */
function TurnDuration({ timing, showAvatar }: { timing: TurnTiming; showAvatar: boolean }) {
  const running = timing.endedAt === undefined;
  const [currentTime, setCurrentTime] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    setCurrentTime(Date.now());
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [running, timing.startedAt]);

  const duration = Math.max(0, (timing.endedAt ?? currentTime) - timing.startedAt);
  if (!running) {
    return (
      <div className="ml-10 min-h-7 text-[13px] tabular-nums text-gray-400">
        Completed in {formatDuration(duration)}
      </div>
    );
  }

  return (
    <div className={`flex min-h-7 items-center text-[13px] tabular-nums text-gray-400 ${showAvatar ? "gap-3" : "ml-10"}`} role="status" aria-live="polite">
      {showAvatar && (
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-emerald-600">
          <Sparkles size={13} />
        </span>
      )}
      <span className="flex items-center gap-2">
        <span className="thinking-shimmer font-medium">Working</span>
        <span className="flex items-center gap-0.5" aria-hidden="true">
          {[0, 1, 2].map((index) => (
            <span key={index} className="h-1 w-1 animate-pulse rounded-full bg-gray-400 motion-reduce:animate-none" style={{ animationDelay: `${index * 160}ms` }} />
          ))}
        </span>
        <span>· {formatDuration(duration)}</span>
      </span>
    </div>
  );
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.floor(milliseconds / 1_000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function messageMetadata(mentions: MentionRef[] = [], command?: string) {
  return {
    created_at: new Date().toISOString(),
    ...(mentions.length ? { mentions } : {}),
    ...(command ? { command } : {}),
  };
}

function precedingUserId(messages: ChatMessage[], before: number): string | undefined {
  for (let index = before - 1; index >= 0; index -= 1) {
    if (messages[index].role === "user") return messages[index].id;
  }
  return undefined;
}

function followingAssistantId(messages: ChatMessage[], after: number): string | undefined {
  for (let index = after + 1; index < messages.length; index += 1) {
    if (messages[index].role === "user") return undefined;
    if (messages[index].role === "assistant") return messages[index].id;
  }
  return undefined;
}

function collectReports(messages: ChatMessage[]): Presentation[] {
  const reports: Presentation[] = [];
  for (const m of messages) {
    for (const p of m.parts as Part[]) {
      const report = reportFromToolPart(p);
      if (report) reports.push(report);
    }
  }
  return reports;
}
