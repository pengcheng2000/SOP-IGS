# AGENTS.md

## Purpose

This file defines how Codex should work in this repository.

Keep this file concise and stable.

Do **not** use this file as a project log, task tracker, or session history.

Project state belongs in `PROJECT_STATE.md`.
Task status belongs in `TODO.md`.

---

## Working Principles

* Understand the existing project before making significant changes.
* Prefer simple, maintainable solutions appropriate for the current project size.
* Avoid premature abstraction and unnecessary infrastructure.
* Do not introduce major dependencies, services, frameworks, or architectural patterns without a clear reason.
* Follow the existing code style and project structure unless there is a strong reason to change them.
* Avoid modifying unrelated files.
* For major architectural or cross-module changes, plan before implementation.
* When requirements are ambiguous and materially affect implementation, clarify or explicitly state assumptions before proceeding.

---

## Coding

* Keep modules focused and responsibilities clear.
* Prefer readable code over clever code.
* Reuse existing abstractions where appropriate, but do not force reuse when it increases complexity.
* Avoid unnecessary duplication.
* Keep configuration separate from business logic where practical.
* Do not leave dead code, temporary debug code, or unexplained workarounds.
* Preserve backward compatibility unless the task explicitly requires breaking it.

---

## Testing

For meaningful changes:

* Run the most relevant existing tests.
* Add or update tests when behavior changes and testing is practical.
* Verify affected modules after implementation.
* Do not claim a change is complete if relevant tests or verification are failing.
* If verification cannot be completed, record the limitation in `PROJECT_STATE.md` or `TODO.md` when it matters for future work.

---

## Project Memory

Codex must actively maintain:

* `PROJECT_STATE.md` — durable project state and important decisions.
* `TODO.md` — current execution queue.

These files are part of the development workflow, not optional documentation.

Before significant work, read them when they exist.

Do not assume previous chat/session context is available.

---

## Checkpoint Rules

Create a checkpoint by reviewing and updating `PROJECT_STATE.md` and `TODO.md` when any of the following occurs:

### Mandatory checkpoints

* A major feature or meaningful project milestone is completed.
* The architecture or an important technical design changes.
* A significant technical decision is made.
* A major dependency, service, database structure, API contract, or integration changes.
* An important problem, risk, limitation, or blocker is discovered.
* A previously important problem or blocker is resolved.
* The current development phase changes.
* A session is likely to end after meaningful work.
* Work is about to stop with unfinished context that another session would need.

### Autonomous checkpoints

Codex should also update these files whenever it determines that enough **durable project state** has accumulated.

Durable project state means information that a fresh Codex session would need in order to continue the project correctly without relying on previous conversation history.

Examples include:

* an implementation now differs meaningfully from the previous architecture;
* an important design assumption has been confirmed or rejected;
* ownership or responsibility of modules has changed;
* a new constraint affects future implementation;
* several completed tasks collectively change the project's current state;
* the next logical development step has materially changed.

Do **not** checkpoint for trivial edits, formatting changes, small bug fixes with no lasting impact, or routine implementation details.

---

## PROJECT_STATE.md Rules

`PROJECT_STATE.md` should describe the **current truth**, not the full history.

Keep it concise.

Maintain information such as:

* current development stage;
* current architecture;
* current technology stack;
* important confirmed decisions;
* major completed modules;
* important active problems or risks;
* relevant known limitations.

When information becomes obsolete, replace or remove it rather than continually appending history.

Do not turn `PROJECT_STATE.md` into a changelog.

---

## TODO.md Rules

`TODO.md` represents the current work queue.

Maintain these sections:

* `Doing`
* `Next`
* `Backlog`
* `Blocked`

Rules:

* Keep `Doing` small and focused.
* Move tasks when their status changes.
* Remove completed tasks once their completion is reflected in project state when relevant.
* Do not accumulate a permanent history of completed tasks.
* Break large tasks into actionable units when useful.
* Record blockers clearly enough that a future session can understand what is preventing progress.

---

## AGENTS.md Maintenance

`AGENTS.md` must remain concise.

Only modify this file when a **stable repository-level working rule** changes.

Do not add:

* session notes;
* project status;
* completed work;
* temporary decisions;
* implementation history;
* one-off instructions;
* task lists.

Prefer editing or replacing an existing rule instead of continuously appending new rules.

If information belongs in `PROJECT_STATE.md` or `TODO.md`, put it there instead.

---

## Before Ending Meaningful Work

Before ending a meaningful development session:

1. Check whether the implementation and `PROJECT_STATE.md` still agree.
2. Check whether `TODO.md` reflects the actual next steps.
3. Record unresolved blockers or important risks.
4. Remove stale information.
5. Keep both files concise enough that a fresh Codex session can quickly understand the project.
