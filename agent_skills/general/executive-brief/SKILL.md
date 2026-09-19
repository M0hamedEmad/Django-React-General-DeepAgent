---
name: executive-brief
description: Turn company information, research, notes, incidents, performance updates, or analysis into a decision-ready brief for leaders. Use whenever the user asks for an executive summary, management brief, leadership update, CEO or board summary, what management needs to know, key risks and actions, or a concise synthesis for a decision. This is for interpreting and communicating evidence, not for merely retrieving a record or performing an operational transaction.
required-tools: [ask_user, present_report]
---

# Executive Brief

Turn scattered evidence into a brief a leader can understand, trust, and act on quickly.

## Working principles

- Optimize for the decision, not for completeness. Put the most consequential information first.
- Separate observed facts, interpretation, and recommendations. A leader should be able to see where the evidence ends and judgment begins.
- Preserve figures, dates, names, and units exactly as their sources provide them. Never manufacture a missing value or quietly convert an estimate into a fact.
- Prefer material changes, exceptions, dependencies, and decisions over routine detail.
- Give actions an owner and timing only when the source or user supplies them. Otherwise write `Owner: unassigned` or `Timing: not set` instead of inventing accountability.
- Treat recommendations as proposals. This skill does not grant permission to send, approve, publish, purchase, or change anything.
- Do not imply that a reporting team, dashboard, auditor, target, compliance duty, or reporting cycle exists unless the user or a verified source names it. Ask for an authorized source generically when its owner or system is unknown.

## Workflow

### 1. Identify the brief's job

Determine:

- audience;
- decision or outcome the brief should support;
- time period and scope;
- urgency or deadline;
- available evidence.

Infer low-risk details from the request. If missing information would materially change the analysis, call `ask_user` once with every clarification already known. Let the user skip questions, then state any assumptions you must make.

### 2. Build an evidence ledger

Before writing, organize the available information privately into:

- confirmed facts and their sources;
- estimates or forecasts;
- interpretations;
- unknowns and conflicts.

Use supplied documents and current tool results before general knowledge. If the request depends on fresh external information, research it. If a needed source is unavailable or a tool fails, disclose the gap; do not treat failure as evidence that nothing happened.

For every material quantitative claim, retain enough source context to explain where it came from. Do not expose private chain-of-thought or the private ledger itself.

### 3. Find what matters

Prioritize information that changes at least one of these:

- a decision;
- financial, legal, operational, security, or reputational risk;
- a deadline or dependency;
- a customer or employee outcome;
- an accountable next action.

Compress repeated details. Surface contradictions instead of averaging or silently choosing between them.

### 4. Form the recommendation

When the evidence supports a recommendation, make it direct and explain why. Include credible alternatives only when they represent a real choice. State uncertainty proportionately:

- **High confidence** — supported by consistent, direct evidence.
- **Medium confidence** — reasonable interpretation with some missing or indirect evidence.
- **Low confidence** — important but weakly supported; validation is needed before acting.

Do not add a confidence label when the user only wants a neutral summary and no judgment is required.

### 5. Choose the delivery format

Use a concise chat response when the brief is short and has no useful structured display.
When the user explicitly asks for a short brief, keep it in chat; do not expand it into a report merely because the topic is executive-facing.

Use `present_report` when the user asks for a report, when the brief has several sections, or when KPIs, comparisons, trends, or a decision table materially improve understanding. In a report:

- use `kpis` only for sourced headline values;
- use a `table` for exact comparisons, owners, risks, or actions;
- use a `chart` only when a visual trend or comparison is genuinely easier to understand;
- use `markdown` for the situation, interpretation, recommendation, and caveats;
- use `links` for authoritative sources or existing deliverables.

After opening a report, summarize the decision and the most important risk in chat rather than repeating the entire report.

## Output contract

Read `/skills/general/executive-brief/references/brief-template.md` when producing a full brief. Adapt the headings to the user's situation; do not print empty sections merely to satisfy a template.

For a short response, use this order:

1. Bottom line.
2. Two to five material findings.
3. Decision or recommendation, when requested.
4. Risks and unknowns.
5. Next actions.

Use plain business language. Explain specialist terminology once. Keep source references beside the claims they support when sources are available.

## Quality check

Before delivering, verify that:

- the first paragraph answers why the brief matters;
- every figure is sourced, supplied, or clearly labeled as an estimate;
- facts and recommendations are distinguishable;
- contradictory evidence and important unknowns are visible;
- proposed actions do not imply they have already happened;
- the result is shorter and more decision-useful than the material it summarizes.
