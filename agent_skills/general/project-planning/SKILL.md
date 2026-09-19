---
name: project-planning
description: Turn a company objective or change into an actionable project, implementation, rollout, launch, migration, or roadmap plan. Use whenever the user asks how to execute an initiative, define scope, create phases or milestones, assign ownership, sequence dependencies, estimate a timeline, identify project risks, or recover a delayed project. Do not use for a simple personal task list, a meeting agenda, or a retrospective summary with no future execution work.
required-tools: [ask_user, present_report]
---

# Project Planning

Turn an objective into a plan that a team can execute, inspect, and revise.

## Planning principles

- Begin with the business outcome. Activity without a measurable result is not progress.
- Match detail to certainty. Early ideas need decision points and ranges; approved initiatives can support owners, dates, and detailed work packages.
- Build around deliverables and acceptance criteria, not vague activity labels such as “work on integration”.
- Make dependencies visible. A plausible list of tasks is not a plan until its sequence and blockers are clear.
- Preserve every supplied date, budget, owner, constraint, and metric exactly. Never invent precision to make the plan look complete. A final deadline alone does not justify adding earlier calendar deadlines.
- Do not create hard pilot sizes, completion percentages, acceptance thresholds, durations, or owner-appointment gates from thin air. Mark them `To be defined`; if useful, label alternatives as unapproved proposals rather than acceptance criteria.
- Treat the plan as a proposal until the user says it is approved. Do not imply that work has started, resources are committed, or people accepted assignments.
- Do not turn suggested acceptance checks into already-approved thresholds or invent the status of permits, inspections, reviews, staff training, or other work. If a step or gate is only a reasonable suggestion, label it `Proposed` and leave its threshold undefined.

The agent's internal planning tool may help manage its own work, but that private checklist is not the user's project plan. Deliver the project plan explicitly in chat or through `present_report`.

## Workflow

### 1. Establish the planning level

Choose the least detailed level that is useful:

- **Outline** — direction, major phases, key decisions, and rough sequencing for an early idea.
- **Working plan** — scoped deliverables, milestone targets, dependencies, risks, and role-level ownership.
- **Execution plan** — accepted scope with named owners, anchored dates, resources, controls, and acceptance criteria.

Do not present an execution plan when the information only supports an outline.

### 2. Define the outcome and boundaries

Identify:

- objective and business reason;
- success measures and acceptance conditions;
- sponsor, users, and affected teams;
- scope included and explicitly excluded;
- fixed deadline, budget, policy, technology, or resource constraints;
- current state and known prior decisions.

Infer low-risk details from the request. If missing information would change scope, sequence, cost, or feasibility, call `ask_user` once with every material question already known. Let the user skip questions and record any resulting assumptions visibly.

If the user specifically requests a conditional recovery plan or decision options, do not interrupt solely because an owner or revised forecast is missing. Show the unknown, give a bounded conditional plan, and name the decision to make. Ask before committing resources or taking action, or when no useful conditional answer is possible.

### 3. Decompose by deliverable

Create workstreams only where they represent distinct outcomes or ownership. Within each workstream:

1. name the deliverable;
2. define what “done” means;
3. identify prerequisite inputs and decisions;
4. assign an owner supplied by the user, or an appropriate role placeholder;
5. estimate duration only when evidence supports it.

Keep tasks at a level a responsible owner can understand and manage. Avoid hundreds of artificial subtasks.

### 4. Sequence milestones and dependencies

Link milestones to completed outcomes, not to elapsed time. Identify:

- hard dependencies that block the next step;
- external dependencies outside the project team's control;
- decision gates requiring approval;
- work that can proceed in parallel;
- work explicitly approved to proceed in parallel must not acquire a new prerequisite without evidence;
- do not add a blocking dependency merely because two steps appear in a sensible order; distinguish a confirmed blocker from a proposed sequencing preference;
- the likely critical path, when enough timing information exists.

Use dependency order or relative periods such as `Week 1` or `Phase 2` when intermediate dates are unknown. Even if a final deadline is supplied, do not assign calendar dates to earlier milestones unless the user supplied them or gave durations and explicitly asked you to calculate a proposed schedule. Use ranges for uncertain estimates and label the basis of the estimate.

### 5. Plan ownership and governance

Use named owners only when provided or confirmed. Otherwise assign role-level ownership such as `Project lead` or `Security owner`, and mark it as proposed.

Define a lightweight operating rhythm appropriate to the work:

- who makes which decisions;
- how progress and blockers are reviewed;
- when scope or schedule changes must be escalated;
- what evidence closes each decision gate.

Do not add ceremonies that do not help control delivery.

### 6. Build the risk and assumption register

For each material risk, state the cause, potential consequence, early warning sign, mitigation, and proposed owner. Keep assumptions separate: an assumption must be validated, while a risk may or may not occur.

Surface contradictions and infeasible constraints directly. Do not make a schedule fit by hiding unresolved work.

### 7. Deliver the plan

Use chat for a requested concise outline or recovery plan. Do not call `present_report` merely because a concise answer has several headings or acceptance checks. Use `present_report` for an explicitly requested report or a substantial working or execution plan with several workstreams, milestone tables, risks, or status indicators.

In the side panel:

- use `markdown` for the objective, scope, approach, and assumptions;
- use a `table` for milestones, workstreams, decision gates, and risks;
- use `kpis` only for supplied targets or plan-level counts that are genuinely useful;
- use a `chart` only when a timeline or comparison is clearer visually and its values are supported;
- use `links` for authoritative sources or existing project documents.

After opening the report, state the immediate next decision and biggest delivery risk in chat rather than repeating the full plan.

## Output contract

Read `/skills/general/project-planning/references/project-plan-template.md` for a working or execution plan. Omit empty sections, but always make these visible:

1. objective and success criteria;
2. scope and assumptions;
3. phases or milestones with dependencies;
4. ownership;
5. material risks;
6. immediate next actions or decisions.

Use status terms consistently:

- **Proposed** — not yet agreed.
- **Ready** — prerequisites are met but work has not necessarily started.
- **In progress** — only when the user or a source confirms it.
- **Blocked** — a named dependency currently prevents progress.
- **Done** — acceptance criteria are confirmed, not merely because an activity occurred.

## Quality check

Before delivering, verify that:

- success is measurable or explicitly marked for definition;
- scope exclusions are visible;
- milestones describe completed outcomes;
- dates, durations, budgets, and owners are supplied, derived transparently, or labeled as proposed;
- every blocking dependency has a resolution path or an explicit decision needed;
- risks and assumptions are not mixed together;
- the plan does not claim authorization or progress that has not happened.
