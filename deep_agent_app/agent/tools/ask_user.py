"""One interrupt containing every clarification currently known."""

from collections.abc import Mapping
from typing import Annotated

from langgraph.types import interrupt
from pydantic import BaseModel, Field


class AskUserQuestion(BaseModel):
    question: str = Field(description="A short, direct question.")
    options: list[str] = Field(
        default_factory=list,
        description="Known choices. Leave empty when free text is needed.",
    )


def _ask_user_questions(questions, question, options):
    raw = questions or (
        [{"question": question, "options": options or []}] if question else []
    )
    normalized = []
    for index, item in enumerate(raw, 1):
        if isinstance(item, AskUserQuestion):
            item = item.model_dump()
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("question") or "").strip()
        if not text:
            continue
        choices = item.get("options")
        choices = choices if isinstance(choices, list) else []
        normalized.append(
            {
                "id": f"q{index}",
                "question": text,
                "options": [str(choice) for choice in choices if str(choice).strip()],
            }
        )
    if not normalized:
        raise ValueError("ask_user requires at least one non-empty question")
    return normalized


def _answer_text(value):
    if value is None:
        return "Skipped"
    if isinstance(value, str):
        return value.strip() or "Skipped"
    return str(value)


def _question_answer_transcript(questions, answers):
    if isinstance(answers, Mapping):
        values = [_answer_text(answers.get(question["id"])) for question in questions]
    elif isinstance(answers, (list, tuple)):
        values = [_answer_text(value) for value in answers]
    else:
        values = [_answer_text(answers)] if len(questions) == 1 else []
    return "\n\n".join(
        f"Q: {question['question']}\nA: {values[index] if index < len(values) else ''}"
        for index, question in enumerate(questions)
    )


def ask_user(
    questions: Annotated[
        list[AskUserQuestion] | None,
        "Every clarification already known. Prefer this even for one question.",
    ] = None,
    question: Annotated[str | None, "Legacy single-question input."] = None,
    options: Annotated[list[str] | None, "Legacy choices for question."] = None,
) -> str:
    """Pause once for a batch and return a labeled Q/A transcript."""
    fields = _ask_user_questions(questions, question, options)
    answers = interrupt({"kind": "questions", "questions": fields})
    return _question_answer_transcript(fields, answers)
