---
description: Implement a batch of 2 or more queue items in one session and update AIDE progress.
---

<!-- Project-local command (not part of the upstream AIDE extension). -->
<!-- Maintained by this project. See docs/aide/customizing-the-flow.md -->

# Execute Batch

Implement a batch of work items from the AIDE queue in a single session.

## Purpose

Batch variant of Step 6 of the AI-Driven Engineering workflow
(`/speckit.aide.execute-item`). It takes an explicit list of at least two item
numbers, creates any missing work item specifications in `docs/aide/items/`,
implements the items sequentially, and keeps `docs/aide/progress.md` up to date
after every item so the batch can always be resumed.

## User Input

$ARGUMENTS

Accepted formats (item numbers, zero-padded or not):

- Range: `020-023`
- List: `020,021,022` or `020 021 022`
- Mixed: `020-023,027`

## Instructions

### 1. Validate the input (before changing anything)

1. Parse `$ARGUMENTS` into unique item numbers, normalized to 3 digits.
2. If fewer than **2** valid numbers result, print this message and **STOP**.
   Do not create, edit, or delete any file:

   > Uso: `/speckit.aide.execute-batch <items>` — indique al menos 2 items pendientes (p. ej. `020-023,027`).

3. Locate each `### Item NNN: ...` heading in `docs/aide/queue/queue-*.md`
   (most recent queue first). If a number does not exist in any queue, report
   it and **STOP**.
4. Read `docs/aide/progress.md`. If any item is already marked ✅, report it and
   **STOP** — only pending items (📋 or 🚧) may be batched.
5. Sort the items ascending by number and tell the user the batch that will be
   executed.

### 2. Create the batch (specifications first)

1. For every item without a matching `docs/aide/items/NNN-*.md` file, create the
   specification following the required sections of `/speckit.aide.create-item`:
   - Description, Acceptance criteria, Implementation steps, Testing strategy,
     Dependencies.
   - Decisions & Trade-offs (initialized with "To be updated during implementation.").
   - Testing prerequisites and the `progress.md` completion reminder.
2. Keep each specification focused on its item; do not pad.
3. Register the whole batch with the todo list tool (one entry per item) before
   implementing anything.

### 3. Implement sequentially (one item at a time)

For each item, in ascending order:

1. Read only that item's specification.
2. Update `docs/aide/progress.md` for that item only: 📋 → 🚧 (skip if already 🚧).
3. Implement exactly what the specification describes; write or extend the tests
   it requires.
4. Run the item's targeted tests plus the project checks on the touched code
   (`uv run pytest <paths>`, `uv run ruff check`, `uv run mypy`).
5. Document decisions and evidence in the specification's
   "Decisions & Trade-offs" section.
6. Update `docs/aide/progress.md` for that item only: 🚧 → ✅ with a short
   evidence note (command + result).
7. Mark the item complete in the todo list and move to the next one.
8. Do **not** create git commits.

### 4. On a blocked item

- Document the blocker in the item's specification and leave the item in 🚧.
- **STOP the batch immediately**; do not start the next item.
- Leave the remaining items in 📋.
- Tell the user the blocked item number and to run `/speckit.aide.feedback-loop`.

### 5. Batch closure

1. Run the full project check from the repository root: `uv run pytest`,
   `uv run ruff check`, `uv run mypy`.
2. Update `docs/aide/progress.md`:
   - Stage/deliverable statuses that this batch closes (e.g. a roadmap stage → ✅).
   - The "Última actualización" line.
3. Print a summary: item → status (✅ / ⛔ blocked) and the files changed per item.
4. Next step:
   - Pending items remain in the queue → new chat session and run
     `/speckit.aide.execute-batch` with the next set.
   - Queue exhausted → new chat session and run `/speckit.aide.create-queue`.

## Rules

- Update only the progress entries that belong to this batch; never mark
  unrelated work complete.
- Never skip a failing test to advance to the next item.
- Never commit, amend, or push.
- The specification is the source of truth: if implementation must diverge,
  update the specification and record why.
