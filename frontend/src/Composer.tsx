import { ArrowUp, Bot, Brain, Cpu, Globe, ListTodo, Mic, Plus, Square, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Icon, MENTION_ICON } from "./icons";
import { Menu } from "./Menu";
import { Popup, type PopupItem } from "./Popup";
import { PromptText } from "./PromptText";
import type { Command, Config, Mention, MentionRef, Options, ReasoningEffort } from "./types";

const MODES = [
  { id: "instant", label: "Instant", detail: "Fastest available response" },
  { id: "medium", label: "Medium", detail: "Balanced speed and depth" },
  { id: "high", label: "High", detail: "More analysis for difficult work" },
  { id: "max", label: "Max", detail: "Deepest available analysis; slowest" },
] satisfies { id: ReasoningEffort; label: string; detail: string }[];

const KIND_LABEL: Record<Mention["kind"], string> = { skill: "Skills", agent: "Agents", tool: "Tools" };
const KIND_ORDER: Mention["kind"][] = ["skill", "agent", "tool"];

/** What the caret is on. "/name" at the very start of the draft opens the
 *  commands; "@name" anywhere opens the mentions. `start`..`end` is the
 *  token the pick replaces. */
type Trigger = { kind: "command" | "mention"; query: string; start: number; end: number };

function triggerAt(text: string, caret: number): Trigger | null {
  const before = text.slice(0, caret);
  const slash = /^\/([\w-]*)$/.exec(before);
  if (slash) return { kind: "command", query: slash[1], start: 0, end: caret };
  const at = /(?:^|\s)@([\w-]*)$/.exec(before);
  if (at) return { kind: "mention", query: at[1], start: caret - at[1].length - 1, end: caret };
  return null;
}

const fold = (s: string) => s.toLowerCase().replace(/[-_]/g, " ");
const matches = (haystack: string, query: string) => fold(haystack).includes(fold(query));

/** The @names in a message that point at something real, in order, once each. */
function mentionsIn(text: string, known: Mention[], selected: ReadonlySet<string>): MentionRef[] {
  const found: MentionRef[] = [];
  const re = /(?:^|\s)@([\w-]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const id = m[1];
    if (!selected.has(id)) continue;
    const hit = known.find((k) => k.id === id);
    if (hit && !found.some((f) => f.kind === hit.kind && f.id === hit.id)) found.push({ kind: hit.kind, id: hit.id });
  }
  return found;
}

export function Composer({ draft, setDraft, onSend, onStop, busy, options, setOptions, config, hero }: {
  draft: string;
  setDraft: (text: string) => void;
  onSend: (text: string, mentions: MentionRef[], command?: string) => void;
  onStop: () => void;
  busy: boolean;
  options: Options;
  setOptions: (options: Options) => void;
  config: Config;
  hero: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const highlight = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(false);
  const [caret, setCaret] = useState(0);
  const [closed, setClosed] = useState(false); // Escape closed the list; the next keystroke reopens it
  const [active, setActive] = useState(0);
  const [command, setCommand] = useState<Command | null>(null);
  const [selectedMentions, setSelectedMentions] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    ref.current?.focus();
  }, [hero]);

  const candidate = closed ? null : triggerAt(draft, caret);
  const trigger = command && candidate?.kind === "command" ? null : candidate;
  const query = trigger?.query;
  const kind = trigger?.kind;

  // The rows the list shows, and what picking each one puts in the draft.
  const choices = useMemo((): {
    item: PopupItem;
    insert?: string;
    command?: Command;
    mention?: Mention;
    enablePlan?: true;
  }[] => {
    if (kind === "command") {
      const plan = {
        item: {
          key: "mode:plan",
          icon: <ListTodo size={15} />,
          label: "Plan",
          detail: "Show and track the steps while the assistant works",
        },
        insert: "",
        enablePlan: true as const,
      };
      const commands = config.commands
        .filter((c) => c.id !== "plan")
        .filter((c) => matches(`${c.id} ${c.label} ${c.prompt}`, query ?? ""))
        .map((c) => ({
          item: { key: `c:${c.id}`, icon: <Icon name={c.icon} />, label: c.label, detail: c.hint || c.prompt },
          insert: `/${c.id} `,
          command: c,
        }));
      return matches("plan show track steps", query ?? "") ? [plan, ...commands] : commands;
    }
    if (kind === "mention") {
      return config.mentions
        .filter((m) => matches(
          `${m.id} ${m.label} ${m.description ?? ""} ${m.owners?.map((owner) => `${owner.id} ${owner.label}`).join(" ") ?? ""}`,
          query ?? "",
        ))
        .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
        .map((m) => {
          const owners = m.owners?.map((owner) => owner.label).join(", ");
          return {
            item: {
              key: `${m.kind}:${m.id}`,
              icon: <Icon name={MENTION_ICON[m.kind]} />,
              label: `@${m.id}`,
              detail: [m.description, owners && `Available to ${owners}`].filter(Boolean).join(" · "),
              group: KIND_LABEL[m.kind],
            },
            insert: `@${m.id} `,
            mention: m,
          };
        });
    }
    return [];
  }, [kind, query, config]);

  useEffect(() => setActive(0), [kind, query]);
  const activeIndex = Math.min(active, Math.max(choices.length - 1, 0));

  const pick = (index: number) => {
    const choice = choices[index];
    if (!trigger || !choice) return;
    const insert = choice.insert ?? "";
    const next = draft.slice(0, trigger.start) + insert + draft.slice(trigger.end);
    const pos = trigger.start + insert.length;
    if (choice.enablePlan) {
      setOptions({ ...options, plan: true });
      setCommand(null);
    } else if (choice.command) {
      setCommand(choice.command);
    }
    if (choice.mention) {
      setSelectedMentions((current) => new Set(current).add(choice.mention!.id));
    }
    setDraft(next);
    setCaret(pos);
    setClosed(true);
    requestAnimationFrame(() => {
      ref.current?.focus();
      ref.current?.setSelectionRange(pos, pos);
    });
  };

  const send = () => {
    const text = draft.trim();
    if (!text || busy) return;
    if (text === "/plan") {
      setOptions({ ...options, plan: true });
      setDraft("");
      setCommand(null);
      setSelectedMentions(new Set());
      setClosed(true);
      return;
    }
    onSend(text, mentionsIn(text, config.mentions, selectedMentions), command?.id);
    setDraft("");
    setCommand(null);
    setSelectedMentions(new Set());
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (trigger && choices.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => Math.min(a + 1, choices.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        pick(activeIndex);
        return;
      }
    }
    if (trigger && e.key === "Escape") {
      e.preventDefault();
      setClosed(true);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  const toggleTool = (id: string) => {
    const tools = options.tools.includes(id) ? options.tools.filter((t) => t !== id) : [...options.tools, id];
    setOptions({ ...options, tools });
  };

  const modelLabel = config.models.find((m) => m.id === options.model)?.label ?? "Model";
  const agentLabel = config.agents.find((a) => a.id === options.agent)?.label ?? "Agent";
  const modeLabel = MODES.find((mode) => mode.id === options.thinking)?.label ?? "Instant";

  return (
    <div
      className={`relative rounded-3xl border bg-surface transition-[border-color,box-shadow] ${
        focused ? "border-gray-300 shadow-[0_4px_14px_rgba(32,32,30,0.07)]" : "border-line shadow-[0_2px_8px_rgba(32,32,30,0.04)]"
      }`}
    >
      {trigger && (
        <Popup
          items={choices.map((c) => c.item)}
          active={activeIndex}
          onPick={pick}
          onHover={setActive}
          empty={trigger.kind === "command" ? "No prompt matches" : "Nothing matches"}
        />
      )}

      <div className="relative">
        <div
          ref={highlight}
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900"
        >
          <PromptText
            text={draft}
            command={command?.id}
            mentions={Array.from(selectedMentions)}
          />
          {draft && "\u200b"}
        </div>
        <textarea
          ref={ref}
          value={draft}
          onChange={(e) => {
            let value = e.target.value;
            let nextCaret = e.target.selectionStart;
            const planPrefix = /^\/plan\s+/.exec(value);
            if (planPrefix) {
              value = value.slice(planPrefix[0].length);
              nextCaret = Math.max(0, nextCaret - planPrefix[0].length);
              setOptions({ ...options, plan: true });
              setCommand(null);
              requestAnimationFrame(() => {
                ref.current?.setSelectionRange(nextCaret, nextCaret);
              });
            }
            setDraft(value);
            setCaret(nextCaret);
            setClosed(false);
            if (command && !new RegExp(`^/${command.id}(?:\\s|$)`).test(value)) {
              setCommand(null);
            }
            setSelectedMentions((current) => {
              const present = new Set(
                Array.from(
                  value.matchAll(/(?:^|\s)@([\w-]+)/g),
                  (match) => match[1],
                ),
              );
              const next = new Set(
                Array.from(current).filter((id) => present.has(id)),
              );
              return next.size === current.size ? current : next;
            });
          }}
          onSelect={(e) => setCaret(e.currentTarget.selectionStart)}
          onScroll={(e) => {
            if (highlight.current) {
              highlight.current.scrollTop = e.currentTarget.scrollTop;
              highlight.current.scrollLeft = e.currentTarget.scrollLeft;
            }
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={onKeyDown}
          placeholder={hero ? "Assign a task or ask anything — / for a command, @ for a skill, agent or tool" : "Message"}
          rows={hero ? 3 : 1}
          className="relative block max-h-64 w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-transparent caret-gray-900 outline-none selection:bg-blue-100 placeholder:text-gray-400"
        />
      </div>

      {hero && (
        <div className="flex flex-wrap items-center gap-2 px-4 pb-2">
          {config.commands
            .filter((c) => c.placement === "bar")
            .map((c) => (
              <button
                key={c.id}
                type="button"
                title={c.hint}
                onClick={() => {
                  const replacing = command && new RegExp(`^/${command.id}(?:\\s|$)`).test(draft);
                  const details = replacing ? draft.slice(command.id.length + 1).trimStart() : draft;
                  const next = command?.id === c.id ? details : `/${c.id}${details ? ` ${details}` : " "}`;
                  setCommand(command?.id === c.id ? null : c);
                  setDraft(next);
                  const pos = next.length;
                  setCaret(pos);
                  requestAnimationFrame(() => {
                    ref.current?.focus();
                    ref.current?.setSelectionRange(pos, pos);
                  });
                }}
                aria-pressed={command?.id === c.id}
                className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm ${command?.id === c.id ? "border-blue-200 bg-blue-50 text-blue-700" : "border-line text-gray-700 hover:bg-app"}`}
              >
                <span className="text-gray-500">
                  <Icon name={c.icon} />
                </span>
                {c.label}
              </button>
            ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-3">
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" title="Attach (soon)" className="rounded-full p-2 text-gray-500 hover:bg-gray-100" disabled>
            <Plus size={18} />
          </button>

          {config.tools.map((t) => {
            const on = options.tools.includes(t.id);
            return (
              <button
                key={t.id}
                type="button"
                title={`${t.label}: ${on ? "on" : "off"}`}
                onClick={() => toggleTool(t.id)}
                className={`rounded-full p-2 ${on ? "bg-emerald-50 text-emerald-700" : "text-gray-400 hover:bg-gray-100"}`}
              >
                <Globe size={15} />
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">
          {options.plan && (
            <button
              type="button"
              onClick={() => setOptions({ ...options, plan: false })}
              title="Turn off plan mode"
              aria-label="Turn off plan mode"
              aria-pressed="true"
              className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1.5 text-sm text-emerald-700 hover:bg-emerald-100"
            >
              <ListTodo size={15} />
              Plan
            </button>
          )}
          <Menu
            icon={options.thinking === "instant" ? <Zap size={15} /> : <Brain size={15} />}
            label={modeLabel}
            choices={MODES}
            value={options.thinking}
            onChange={(thinking) => setOptions({ ...options, thinking: thinking as ReasoningEffort })}
            title="Reasoning effort"
          />
          <Menu icon={<Bot size={15} />} label={agentLabel} choices={config.agents} value={options.agent} onChange={(agent) => setOptions({ ...options, agent })} title="Agent" />
          <Menu icon={<Cpu size={15} />} label={modelLabel} choices={config.models} value={options.model} onChange={(model) => setOptions({ ...options, model })} title="Model" />
          <button type="button" title="Voice (soon)" className="rounded-full p-2 text-gray-500 hover:bg-gray-100" disabled>
            <Mic size={18} />
          </button>
          {busy ? (
            <button type="button" onClick={onStop} title="Stop" className="rounded-full bg-gray-900 p-2.5 text-white hover:bg-gray-700">
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={send}
              disabled={!draft.trim()}
              title="Send"
              className="rounded-full bg-gray-900 p-2.5 text-white hover:bg-gray-700 disabled:bg-gray-200 disabled:text-gray-400"
            >
              <ArrowUp size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
