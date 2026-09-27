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
argument-hint: "[on|off|go|auto|review|stop]"
license: MIT
metadata:
  author: neoOpus
  version: "1.2.0"
  repository: https://github.com/neoOpus/agent-skills
  homepage: https://www.skills.sh/neoopus/agent-skills/queue-brain
---

# Queue Brain

#knowledge-management #task-management #priority-routing #verification

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
- **stop / batch (register-only)** — every prompt is REGISTERED ONLY: one entry
  written as outcome + tags, acknowledged in one line, nothing executes. On the
  batch keyword (`STOP!`), run one batched DEDUPE + reality-pass + RE-RANK over
  everything and deliver a single clean ranked todolist. Built for users who
  fire many prompts in a row and want one adjudicated plan.

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
   When a new prompt smells like an existing entry, register it anyway but
   attach a **dedupe flag** naming the merge candidate and what is genuinely
   new ("dedupe flag: this is #12's outcome plus a watch leg — merge, keep the
   watch leg"). Resolution defers to the batch/DEDUPE pass; the flag makes it
   a one-line merge later instead of a re-read of everything.
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
   - **Adjacency without merging:** same-surface entries run adjacently and
     share one scan/sweep, but stay separate entries — each keeps its own
     verification and evidence (merging hides per-tool proof).
   - **Run collapse:** N variants of "run the suite to green" become ONE run
     whose checklist names every predecessor's proof — one capture wall serves
     all claimants; five full runs are four wasted walls.
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

- [ ] It was verified through the real surface (ran it, clicked it, curled it,
      or watched the live preview console) — code that merely *looks* right
      is not done. Rendered-page verification beats syntax checks: a scope
      bug that parses clean still crashes the DOM.
- [ ] Non-trivial logic left one runnable check (assert-style lab test, or a
      documented manual repro).
- [ ] Root cause addressed, not the reported symptom — grep the callers before
      patching one site.
- [ ] No regression in neighboring behavior that shares the touched surface.
- [ ] A new CHECK whose failure mode is silence (an analyzer, a monitor, a
      regression gate) ships with a POSITIVE CONTROL: inject the bug it hunts
      into a copy, watch it catch, delete. An unproven 'clean' is unverified.
- [ ] A lesson was extracted if anything surprising happened (see below).

Quality beats throughput: if done-right needs a refactor the entry didn't
plan for, either extend the entry explicitly or split it — never ship the
shallow version silently.

## Promoted rules (recurring classes, distilled from lessons.md)

Promoted after they kept recurring across projects in the working set. Each
one cost real time before it was written down.

1. **A readout must not be able to lie quietly.** A metric that can degrade to
   a plausible constant (a regex miss falling back to "1 errors"), a tool that
   writes an all-zero report when its input tree is missing, a counter that
   only rises — all read as health while lying. Count the things themselves,
   never a summary string; refuse non-empty input on a missing tree; verify a
   report's own counters, not just its exit code. When one counter is found
   wrong, grep every reader of it before calling the class fixed — the same
   wrong axis survives in a second readout more often than not, and the
   reporter is where it hurts most.
2. **A positive control must fail for the right reason, through the right
   layer.** A control that passes because a *different* guard caught the bug
   proves nothing — disable the mechanism under test, not its neighbors. Drive
   both the old and the new rule over recorded history so the fixture
   reproduces the real failure, and assert on the surface that failed in
   production, not on the fix's return value.
3. **Machine-local state: `present + wrong = FAIL`, `absent = skip`.** A check
   that FAILs for absent input (state files, gitignored artifacts, machine-only
   caches) is a red card nobody can act on — and it is how people learn to
   ignore gates. Same class: a metric keyed on a gitignored build artifact is
   machine-dependent, so the gate lies on any other checkout; derive it from
   source, and let a missing surface say `skip` with the command that produces
   the input.
4. **Gate budgets are measured, not guessed — and a timeout is not a verdict.**
   A timeout is a FAIL whose cause is the machine, not the subject. Budget
   per-file passes from the file count, measure the loaded number (it is the
   one the nightly will actually see), prefer a bigger cap + visible duration
   to weakening the check, and report an overrun as `unverified` — escalating
   to FAIL only when the same gate overruns on consecutive runs. Never "fix" a
   slow-but-correct check by weakening it.
5. **Never sleep-poll a long job; the machine parallelizes fine.** Launch
   detached with a log file, start the next entry immediately, and read the
   log as a side effect of the next command. A wait is justified only when the
   NEXT step needs the result — and then it must ride inside a command that
   also does useful work.
6. **Fix the class, not the site.** A wrong pattern found once (a wrong
   progress axis, an unguarded generator overwriting shared output, a torn-file
   parse, a counter reading only one status) is a sweep instruction, not a
   one-line fix. And fix data contracts at the WRITER, verified against the
   output — a reader-side default that infers a missing field schedules wrong
   work forever the moment a new producer appears.
7. **Rank every suggestion against the user's stated goal, and say which ones
   the goal rejects.** A suggested idea is not an accepted one: tag queue
   entries with the goal they serve, mark off-goal work `postponed`, and   open each session by re-reading the goal, not the queue.
8. **Shared-state mutations go through surgery, not ad-hoc writes.** Any tool
   that rewrites statuses in a shared queue/state file snapshots the
   before-state, mutates under the file lock, writes atomically, and journals
   one line per CHANGED entry ({at, reason, before, after}) — an audit trail
   any tool can replay (reference implementation: queueSurgery(), sider-clone
   60-tools/lib/queue.mjs). Dry-run = a counting pass that mutates nothing;
   after the real run the journal's changed-count must equal the tool's
   claimed count (the lying-readout rule applied to mutation tools). Hand-rolled
   status rewrites were the class that destroyed records.

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

**AUTOMATED CHECK — runs itself, do not rely on memory.** The trigger's history
is a warning relied on session memory and never fired: the marker sat at 137
while the file grew to 173. A checker now does the comparison mechanically:
`node ~/.agents/skills/queue-brain/publish-trigger.mjs` compares the live
working-set count against the marker and prints the one-line publish prompt at
each new 10-entry crossing (moving the marker itself, so one crossing warns
exactly once; a publish resets it). Run it at session start, right after the
lessons re-read — if it prints the line, surface it to the user verbatim and
move on; silence means nothing to do. Selftest: `--selftest`.

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
6. **Transient-FAIL triage** — an infra check (timeout class) that fails once
   under concurrent load is retried before it is investigated; two clean
   reruns downgrade it to noise, a repeat failure makes it real. AVOIDS:
   chasing ghosts while the real red state hides behind them.

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
