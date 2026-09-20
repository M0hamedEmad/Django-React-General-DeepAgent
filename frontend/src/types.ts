import type { UIMessage } from "ai";

export type Choice = { id: string; label: string; detail?: string };

/** A fast prompt: typing "/" offers every one; those with a `placement`
 *  are also chips (`bar` under the message box, `hero` on the empty page).
 *  From the backend's data/commands.json. */
export type Command = {
  id: string;
  label: string;
  icon?: string;
  prompt: string;
  placement?: "bar" | "hero" | null;
  hint?: string;
};

/** Something "@" can point at. The backend discovers agent capabilities;
 * mentions.json can override or hide their composer metadata. */
export type MentionKind = "skill" | "agent" | "tool";
export type MentionOwner = { id: string; label: string };
export type Mention = {
  kind: MentionKind;
  id: string;
  label: string;
  description?: string;
  path?: string;
  owners?: MentionOwner[];
};
/** A mention as it is sent with a message. */
export type MentionRef = { kind: MentionKind; id: string };

export type IntegrationStatus = {
  id: string;
  status: "not_loaded" | "loading" | "ready" | "unavailable";
  message: string;
};

export type RuntimeStatus = {
  agent: { status: "not_loaded" | "ready" | "reloading" };
  integrations: IntegrationStatus[];
  can_reload: boolean;
};

export type Config = {
  user: { username: string };
  models: Choice[];
  default_model: string;
  agents: Choice[];
  tools: Choice[];
  commands: Command[];
  mentions: Mention[];
  runtime: RuntimeStatus;
};

export type ThreadInfo = {
  id: string;
  title: string;
  options: Partial<Options>;
  created_at: string;
  updated_at: string;
};

/** The composer's settings. Sent with every turn; the backend records them. */
export type ReasoningEffort = "instant" | "medium" | "high" | "max";
export type Options = { model: string; agent: string; tools: string[]; thinking: ReasoningEffort; plan: boolean };

export type Series = { name: string; values: (number | null)[] };

export type PresentationBlock =
  | { type: "section"; title: string; description?: string }
  | { type: "markdown"; content: string }
  | { type: "table"; columns: string[]; rows: (string | number | null)[][]; title?: string }
  | { type: "chart"; kind: "bar" | "line" | "pie"; labels: string[]; series: Series[]; title?: string }
  | { type: "kpis"; items: { label: string; value: string; detail?: string; tone?: "neutral" | "positive" | "warning" | "negative" }[] }
  | { type: "status"; tone: "info" | "success" | "warning" | "error"; title: string; message: string }
  | { type: "links"; title?: string; items: { label: string; url: string }[] }
  /** Legacy checkpoint shape. The presentation parser converts this to links. */
  | { type: "link"; url: string; label?: string };

export type Presentation = {
  kind: "presentation";
  id: string;
  title: string;
  subtitle?: string;
  /** Tool input is untrusted until each block is normalized by the renderer. */
  blocks: unknown[];
  error?: string;
};

export type FileArtifact = {
  kind: "file";
  id: string;
  threadId: string;
  path: string;
  title: string;
};

export type WorkspaceItem = Presentation | FileArtifact;

/** Compatibility names for code and checkpoints created before present_ui. */
export type Block = PresentationBlock;
export type Report = Presentation;

/** `Question` is retained for paused checkpoints made by the original
 * single-question tool. New turns always use one batched form. */
export type Question = { kind: "question"; question: string; options: string[] };
export type QuestionField = { id: string; question: string; options: string[] };
export type QuestionBatch = { kind: "questions"; questions: QuestionField[] };

export type Approval = {
  action_requests: { name: string; args: Record<string, unknown>; description?: string }[];
  review_configs: { action_name: string; allowed_decisions: string[] }[];
};

export type InterruptData = { id: string; value: Question | QuestionBatch | Approval };

export type PlanItem = { content: string; status: "pending" | "in_progress" | "completed" };
export type PlanLifecycle = "running" | "finished" | "interrupted" | "failed" | "stopped";

/** A UIMessage part. Tool parts are `tool-<name>`, data parts `data-<name>`. */
export type Part = { type: string; [key: string]: any };

export type MessageMetadata = {
  created_at?: string;
  command?: string;
  mentions?: MentionRef[];
};
export type ChatMessage = UIMessage<MessageMetadata>;

export function isQuestion(value: Question | QuestionBatch | Approval): value is Question {
  return (value as Question).kind === "question";
}

export function isQuestionBatch(value: Question | QuestionBatch | Approval): value is QuestionBatch {
  return (value as QuestionBatch).kind === "questions";
}
