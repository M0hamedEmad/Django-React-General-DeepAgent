import { Check, CheckCircle2, ChevronRight, MessageCircleQuestion, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { isQuestion, isQuestionBatch, type InterruptData, type QuestionField } from "./types";

type BatchAnswer = string | null;

/** A paused turn: a question from the agent, or a tool that needs approval.
 *  The answer and this interrupt's id go back as the next request's
 *  `resume`. The id is required when several graph branches pause together. */
export function InterruptCard({ data, active, live, onAnswer }: {
  data: InterruptData;
  active: boolean;
  live: boolean;
  onAnswer: (interruptId: string, value: unknown, echo: string) => void;
}) {
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [answered, setAnswered] = useState(false);
  const [answers, setAnswers] = useState<Record<string, BatchAnswer>>({});
  const disabled = !active || answered;

  const answer = (value: unknown, echo: string) => {
    setAnswered(true);
    onAnswer(data.id, value, echo);
  };

  if (answered || (!active && !live)) {
    const label = isQuestion(data.value) || isQuestionBatch(data.value)
      ? "Response submitted"
      : "Approval reviewed";
    return (
      <div className="flex min-h-7 items-center gap-1.5 text-xs text-gray-400">
        <CheckCircle2 size={13} />
        <span>{label}</span>
      </div>
    );
  }

  if (isQuestionBatch(data.value)) {
    const questions = data.value.questions;
    const submittedAnswers = Object.fromEntries(
      questions.map((question) => [question.id, answers[question.id]?.trim() || null]),
    );
    const answeredCount = questions.filter((question) => answers[question.id]?.trim()).length;
    const skippedCount = questions.length - answeredCount;
    const transcript = questions
      .map((question) => `Q: ${question.question}\nA: ${answers[question.id]?.trim() || "Skipped"}`)
      .join("\n\n");
    return (
      <form
        className="max-w-3xl border-l-2 border-line py-1 pl-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (questions.length && !disabled) answer(submittedAnswers, transcript);
        }}
      >
        <div className="flex items-start gap-2.5">
          <MessageCircleQuestion size={16} className="mt-0.5 shrink-0 text-gray-400" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-gray-900">A few quick questions</h3>
              {questions.length > 1 && <span className="shrink-0 text-xs text-gray-400">{questions.length} questions</span>}
            </div>
            <p className="mt-0.5 text-xs text-gray-500">Answer what you know. You can skip any question.</p>
          </div>
        </div>
        <div className="mt-4 divide-y divide-gray-100">
          {questions.map((question, index) => (
            <QuestionInput
              key={question.id}
              question={question}
              index={index}
              value={answers[question.id]}
              disabled={disabled}
              onChange={(value) => setAnswers((current) => ({ ...current, [question.id]: value }))}
              onSkip={() =>
                setAnswers((current) => ({
                  ...current,
                  [question.id]: current[question.id] === null ? "" : null,
                }))
              }
            />
          ))}
        </div>
        <div className="mt-4 flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
          <span className="text-xs text-gray-400">
            {answeredCount} answered{skippedCount ? ` · ${skippedCount} skipped` : ""}
          </span>
          <button
            type="submit"
            disabled={!questions.length || disabled}
            className="rounded-full bg-gray-900 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-gray-900/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {answeredCount ? "Continue" : "Continue without answers"}
          </button>
        </div>
      </form>
    );
  }

  if (isQuestion(data.value)) {
    const question = data.value;
    return (
      <form
        className="max-w-3xl border-l-2 border-line py-1 pl-4"
        onSubmit={(event) => {
          event.preventDefault();
          const value = text.trim();
          if (value && !disabled) answer(value, `Q: ${question.question}\nA: ${value}`);
        }}
      >
        <div className="flex items-start gap-2.5">
          <MessageCircleQuestion size={16} className="mt-0.5 shrink-0 text-gray-400" />
          <div>
            <h3 className="text-sm font-medium text-gray-900">A quick question</h3>
          </div>
        </div>
        <p className="mt-3 text-[15px] leading-6 text-gray-900">{question.question}</p>
        {question.options?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {question.options.map((option) => (
              <button
                key={option}
                type="button"
                disabled={disabled}
                onClick={() => answer(option, `Q: ${question.question}\nA: ${option}`)}
                className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-gray-700 outline-none hover:border-gray-400 hover:bg-app focus-visible:ring-2 focus-visible:ring-emerald-500/25 disabled:opacity-40"
              >
                {option}
              </button>
            ))}
          </div>
        )}
        <div className="mt-3 flex gap-2">
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={disabled}
            placeholder={question.options?.length ? "Or enter another answer" : "Your answer"}
            className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-900/5 disabled:bg-app"
          />
          <button
            type="submit"
            disabled={disabled || !text.trim()}
            className="rounded-full bg-gray-900 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-gray-900/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Continue
          </button>
        </div>
      </form>
    );
  }

  const requests = data.value.action_requests ?? [];
  const approve = () => answer({ decisions: requests.map(() => ({ type: "approve" })) }, `Approved: ${requests.map((request) => request.name).join(", ")}`);
  const reject = () =>
    answer(
      { decisions: requests.map(() => (reason.trim() ? { type: "reject", message: reason.trim() } : { type: "reject" })) },
      `Rejected: ${requests.map((request) => request.name).join(", ")}${reason.trim() ? ` — ${reason.trim()}` : ""}`,
    );

  return (
    <section className="max-w-3xl rounded-xl border border-amber-200 bg-surface p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]" aria-label="Approval needed">
      <div className="flex items-start gap-2.5">
        <ShieldAlert size={16} className="mt-0.5 shrink-0 text-amber-600" />
        <div>
          <h3 className="text-sm font-medium text-gray-900">Approval needed</h3>
          <p className="mt-0.5 text-xs text-gray-500">Review this action before the assistant continues.</p>
        </div>
      </div>
      <div className="mt-3 divide-y divide-gray-100 border-y border-gray-100">
        {requests.map((request, index) => (
          <details key={`${request.name}:${index}`} className="group/request py-2 text-sm">
            <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-gray-700 outline-none focus-visible:ring-2 focus-visible:ring-amber-500/25">
              <span className="min-w-0 flex-1 truncate">{request.name}</span>
              <ChevronRight size={13} className="text-gray-400 transition-transform group-open/request:rotate-90" />
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-gray-50 p-2.5 text-xs leading-5 whitespace-pre-wrap text-gray-600">{JSON.stringify(request.args, null, 2)}</pre>
          </details>
        ))}
      </div>
      <input
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        disabled={disabled}
        placeholder="Reason for rejecting (optional)"
        className="mt-3 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-900/5 disabled:bg-gray-50"
      />
      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={reject}
          className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 outline-none hover:bg-gray-100 hover:text-gray-900 focus-visible:ring-2 focus-visible:ring-gray-900/10 disabled:opacity-40"
        >
          <X size={14} /> Reject
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={approve}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white outline-none hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-gray-900/25 disabled:opacity-40"
        >
          <Check size={14} /> Approve
        </button>
      </div>
    </section>
  );
}

function QuestionInput({ question, index, value, disabled, onChange, onSkip }: {
  question: QuestionField;
  index: number;
  value: BatchAnswer | undefined;
  disabled: boolean;
  onChange: (value: string) => void;
  onSkip: () => void;
}) {
  const skipped = value === null;
  return (
    <fieldset disabled={disabled} className="min-w-0 py-3 first:pt-0 last:pb-0 my-3">
      <legend className="flex w-full items-start gap-2 text-sm leading-5 text-gray-900">
        <span className="mt-px w-4 shrink-0 text-xs tabular-nums text-gray-400">{index + 1}.</span>
        <span className="min-w-0 flex-1">{question.question}</span>
        <button
          type="button"
          onClick={onSkip}
          className={`shrink-0 rounded px-1 text-xs outline-none hover:text-gray-900 focus-visible:ring-2 focus-visible:ring-gray-900/10 ${
            skipped ? "font-medium text-gray-700" : "text-gray-400"
          }`}
        >
          {skipped ? "Skipped" : "Skip"}
        </button>
      </legend>
      {question.options.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-2 pl-6">
          {question.options.map((option) => {
            const selected = value === option;
            return (
              <button
                key={option}
                type="button"
                aria-pressed={selected}
                onClick={() => onChange(option)}
                className={`rounded-full border px-3.5 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/25 ${
                  selected
                    ? "border-gray-900 bg-gray-900 text-white"
                    : "border-gray-200 bg-white text-gray-700 hover:border-gray-400 hover:bg-gray-50"
                } disabled:opacity-40`}
              >
                {option}
              </button>
            );
          })}
        </div>
      )}
      <input
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
        placeholder={
          skipped
            ? "Skipped — type to answer"
            : question.options.length
              ? "Or enter another answer"
              : "Your answer"
        }
        aria-label={question.question}
        className={`mt-2.5 ml-6 w-[calc(100%_-_1.5rem)] rounded-xl border bg-white px-3 py-2 text-sm outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-900/5 ${
          skipped ? "border-dashed border-gray-300 text-gray-400" : "border-gray-200"
        }`}
      />
    </fieldset>
  );
}
