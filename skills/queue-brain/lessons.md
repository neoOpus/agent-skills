# Queue Brain — Lessons

Cross-project lessons extracted from queue-brain sessions. Promoted patterns
get rewritten into SKILL.md rules; everything here stays terse (1–2 lines).

<!-- format: - YYYY-MM-DD · project · lesson -->

## Working set

<!-- publish trigger: last suggested at 0 · reset after running publish-queue-brain.mjs -->

- 2026-09-13 · all · SESSION START: re-read ~/.agents/skills/queue-brain/lessons.md before the first re-rank — cross-harness lessons only load if the file is actually read (SKILL.md rule added 09-13 after the junction setup made sharing possible but not automatic)
- 2026-09-13 · all · DEDUPE-BY-REALITY BEATS DEDUPE-BY-TEXT: the queue's dominant corruption is not rephrased duplicates but work ALREADY DONE sitting as backlog — SKILL.md now mandates a reality pass ('is the outcome already true?') before ranking, plus a batched verify-then-close sweep at 20+ entries or cold session start [PROMOTED 09-13 → DEDUPE rule]
- 2026-09-13 · all · POSITIVE CONTROL: analyzer/check reporting 'clean' is unproven until it catches an injected bug — applies to any check whose failure mode is silence [PROMOTED 09-13 → Quality gate: positive-control checkbox]
- 2026-09-13 · all · PREVIEW = REAL SURFACE: rendered-page verification caught a scope bug that parsed clean — beats syntax checks, every time [PROMOTED 09-13 → Quality gate: verification checkbox extended]
- 2026-09-13 · all · TRANSIENT FAIL = RETRY BEFORE INVESTIGATION: infra check failing once under concurrent load is noise until it repeats twice clean; chasing ghosts hides the real red state [PROMOTED 09-13 → Instruments #6]

## Promotion log

- 09-13 · DEDUPE reality pass + verify-then-close sweep → SKILL.md DEDUPE rule (from STALE-QUEUE DRIFT + DEDUPE-BY-REALITY)
- 09-13 · Positive control for silent checks → SKILL.md Quality gate checkbox (from POSITIVE CONTROL)
- 09-13 · Rendered-surface verification → SKILL.md Quality gate verification checkbox (from PREVIEW = REAL SURFACE)
- 09-13 · Transient-FAIL retry triage → SKILL.md Instruments #6 (from FLAPY CHECKS RESOLVE ON RETRY)
