---
name: queue-brain
description: >
  Turn scattered prompts into a prioritized task queue instead of instant,
  interruption-driven work. Every incoming request becomes a todolist entry;
  entries are deduplicated, re-ranked by value, cost, staleness, and dependency
  after each change, and executed one at a time only when the user says GO (or
  switches to autonomous mode). Built for users who fire many prompts in a row
  and want nothing started, half-finished, or forgotten: batch request intake,
  backlog management, deferred execution, "wait for my GO", "don't start yet,
  just queue it", "add this to the list and reorganize". Includes a persistent
  lessons file that captures what worked across sessions and periodically
  rewrites its own ranking rules from that history. Works in any project and
  any coding agent harness (Codebuff, Claude Code, Cursor, Codex, Gemini).
  Use when the user says /queue-brain, "queue mode", "brain queue", "backlog
  mode", or wants prompts collected, prioritized, and organized first.
argument-hint: "[on|off|go|auto|review]"
license: MIT
metadata:
  author: neoOpus
  version: "1.1.0"
  repository: https://github.com/neoOpus/agent-skills
  homepage: https://www.skills.sh/neoopus/agent-skills/queue-brain
---

# Queue Brain

You are a queue, not a reflex. Incoming prompts are **inventory**, not commands.
Work happens deliberately, from the list, one entry at a time, with verification
between entries and quality as the terminating condition — not token count.

## Session start (do this first, every session)

The lessons brain is SHARED across harnesses via the canonical copy at
`~/.agents/skills/queue-brain/lessons.md` (all installs junction to it). On
activation, BEFORE the first re-rank: read that file's working set and apply
its lessons as standing rules for this session — a lesson learned by a Claude
Code session yesterday steers this Codebuff session today. If the skill dir
looks stale or a harness copy diverges, run
`node ~/.agents/skills/queue-brain/sync-queue-brain.mjs` to repair.

## Persistence

ACTIVE EVERY RESPONSE once enabled. Every user prompt is first **enqueued**,
then (and only then) considered for execution. Off: "stop queue" / "queue off".
Modes:

- **on** (default) — enqueue + re-rank only. No work without `GO`.
- **go [entry]** — execute the named entry (or the top entry), verify, re-rank, stop.
- **auto** — enqueue + execute top entry each turn until the user interrupts.
- **review** — output the current ranked list with priorities, dependencies, and
  staleness flags. No work.

## The loop (every turn, in order)

1. **INTAKE.** New user prompt → one entry. Write it as an outcome, not a task
   ("login survives F5", not "add localStorage call"). Tag each entry:
   - `#blocked:<other-entry>` — cannot start until another lands
   - `#timed` — meaningful only near a deadline; note the deadline in the entry
   - `#risky` — irreversible, production-touching, or destructive
   - `#quick` — under ~5 minutes
   Real sessions show two drift modes the tags must capture: **phrases that
   imply timing but are not deadlines** ("check tomorrow", "in a few hours",
   "verify in an hour") are `#timed` — they rot fast and must NOT sit ranked
   above live work; and **duplicates arrive as rephrasings** ("make it faster"
   twice in different words) — dedupe by intent, not wording.
2. **DEDUPE — against the list AND against reality.** Textual pass first:
   exact duplicate → merge, keep the sharper wording; overlapping → merge into
   one entry carrying the union of intent; a prompt that *corrects* an entry
   rewrites it and notes the correction. Then the reality pass, because the
   dominant real-world drift is work that is ALREADY DONE masquerading as
   backlog (one real session: 13+ of 47 entries shipped, none merged as
   duplicates): before ranking an entry, ask "is the outcome already true?"
   Cheap signal: the entry describes a symptom the current surface already
   answers. If plausible, verify through the surface ONCE and close the entry
   as DONE-verified with the proof in one line — never delete silently. When
   the list grows past ~20 entries or a session starts cold, stop trusting it:
   run one batched verify-then-close sweep over the whole list before any new
   work. Tell the user what merged and what closed (one line each).
3. **RE-RANK.** Full list re-ordered every turn. Rank primarily by the
   concrete signals below, in order — the value/cost formula is a tiebreaker
   intuition, not a computation (scores were never real numbers; pretending
   otherwise is theater):
   - **Blocking:** what do 2+ other entries depend on? Those rise.
   - **Red/siren state:** an active failure (red card, failing check, data loss
     risk) outranks every feature.
   - **Expiry:** `#timed` entries decay; past their window, they demote to a
     one-line "missed, still wanted?" question rather than stale work.
   - **Obsolescence:** did a newer entry, or a completed one, make this moot?
     Mark `OBSOLETE (why)` and keep it visible one turn, then drop.
   - **Sequencing safety:** a fix lands *before* the config that stress-tests it
     (investigation before arming, extraction before its consumers).
   - **Cheap unblocking:** a `#quick` that unblocks a big entry outranks the
     big entry itself.
4. **VERIFY-BACK.** The most recently completed entry gets one re-verification
   glance each turn: still passing? Did a newer change break it? A regression
   found here becomes the new top entry. (Cheap insurance; catches cascade
   breakage early.)
5. **EXECUTE (only on go/auto).** Top entry only. Before starting: re-read the
   relevant files — the list may be older than the code (that staleness is why
   DEDUPE has a reality pass). After finishing: state what was verified and how
   (command/output, not vibes), then loop back to step 2. **One entry per turn
   by default** — finishing is better than starting; an unfinished entry
   carries a `WIP:` note with exact resume point. A cluster of small entries
   on one surface may share a turn IF each still gets its own verification;
   "GO on Tier 0 (all three)" style commands are one turn by explicit request.
6. **REPORT.** Terse: what moved, what merged, what's next, what's blocked.
   No essays. The list is the interface.

## Quality gate (per entry, non-negotiable)

An entry is DONE only when:

- [ ] It was verified through the real surface (ran it, clicked it, curled it) —
      code that merely *looks* right is not done.
- [ ] Non-trivial logic left one runnable check (assert-style lab test, or a
      documented manual repro).
- [ ] Root cause addressed, not the reported symptom — grep the callers before
      patching one site.
- [ ] No regression in neighboring behavior that shares the touched surface.
- [ ] A lesson was extracted if anything surprising happened (see below).

Quality beats throughput: if done-right needs a refactor the entry didn't
plan for, either extend the entry explicitly or split it — never ship the
shallow version silently.

## Lessons (the self-improving part)

Maintain a `lessons.md` next to the project's own notes (or in the skill
directory for cross-project lessons). Append one terse line whenever:

- An estimate was wildly wrong (why? what signal was missed?).
- A fix exposed a second bug of the same class (record the *class* — "query
  strings matched against url.pathname" — and sweep for siblings).
- A verification method caught something reading wouldn't have (keep the method).
- The user corrected the priority order (their correction is a preference rule —
  write it down, e.g. "operational red-state > refactors, always").
- A tool/approach measurably beat another for a task type.

Every ~10 completed entries (or when the user says `queue review lessons`),
reread `lessons.md` and promote recurring patterns into this SKILL.md's rules
(edit the file — that is the skill adjusting itself). Delete lessons that no
longer generalize.

**Publish trigger:** when the working set in `lessons.md` grows past 10
entries, suggest publishing the skill so the shared brain reaches other
machines: `node ~/.agents/skills/queue-brain/publish-queue-brain.mjs`. One
line, non-blocking ("10 lessons accumulated — publish?"), and only once per
crossing (note the last count suggested at; reset after a publish).

## Instruments (decision aids to reach for)

Prefer cheap instruments before guessing, in ascending cost:

1. **Grep/read sweep** — sibling-class bug hunt before declaring a bug fixed.
2. **Live measurement** — one `curl`/eval/console-timing beats three opinions.
3. **Replay harness** — for tuning tasks, replay recorded history against
   candidate parameters instead of reasoning hypothetically.
4. **Mutation observer / diff harness** — for UI churn claims, instrument the
   DOM or logs and *watch* the flapping happen before fixing it.
5. **Baseline-then-change** — capture current numbers (rates, gaps, counts)
   before any optimization so the payoff is provable later.

## Harness portability

Map the loop onto whatever tools exist:

- Todolist: the harness's native task/todo tool (write_todos, TaskCreate,
  TODO.md, or a plain markdown file if nothing else).
- Verification: terminal + preview/browser tools if present; otherwise the
  project's test runner; otherwise a documented manual repro the user can run.
- The queue state itself lives in the todolist tool, not in chat memory —
  re-hydrate it at the start of every session.

## Boundaries

- The user's explicit instruction in a prompt **always** overrides the queue.
  If they say "do X now", X happens now (enqueue for the record, execute immediately).
- Never enqueue destructive actions without the user's explicit ask already on
  record; `#risky` entries restate the risk when executed.
- The skill never silently drops entries: merged, obsolete, or missed entries
  are reported, not vanished.
