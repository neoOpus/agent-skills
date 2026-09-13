# Queue Brain — Lessons

Cross-project lessons extracted from queue-brain sessions. Promoted patterns
get rewritten into SKILL.md rules; everything here stays terse (1–2 lines).

<!-- format: - YYYY-MM-DD · project · lesson -->

## Working set

<!-- publish trigger: last suggested at 0 · reset after running publish-queue-brain.mjs -->

- 2026-09-13 · all · SESSION START: re-read ~/.agents/skills/queue-brain/lessons.md before the first re-rank — cross-harness lessons only load if the file is actually read (SKILL.md rule added 09-13 after the junction setup made sharing possible but not automatic)
- 2026-09-13 · sider-clone · STALE-QUEUE DRIFT: backlog items outlive their need — 13+ of 47 were already shipped; verify-then-close probe pass added as T0 before ranking anything new (signal: entry describes a symptom the UI already answers)
- 2026-09-13 · sider-clone · HAND-ROLLED PARSER TRAP: approximate tokenizer gave 310 false candidates for scope-bug hunting; real parser (@babel, already in node_modules) gave exact 0 — check installed deps before writing analysis tooling from scratch
- 2026-09-13 · sider-clone · POSITIVE CONTROL: analyzer reporting 'clean' is unproven until it catches an injected bug — synthetic pick-class bug added to a copy, caught exactly, deleted; applies to any check whose failure mode is silence
- 2026-09-13 · sider-clone · PREVIEW = REAL SURFACE: the live preview console caught a fresh fmtH-out-of-scope bug (the exact class the new sweep hunts) within one poll; verification through the served page beats node --check, every time
- 2026-09-13 · sider-clone · FLAPY CHECKS RESOLVE ON RETRY: self-check FAIL timeouts on backend/daemon were mid-cycle transients; rerun twice before treating as red — recorded as rule: 'transient FAIL = retry before investigation'
- 2026-09-13 · sider-clone · PROCEDURE AT POINT-OF-RISK: clear-traps runbook procedure condensed into the button tooltip (4 steps, evidence-first) — docs nobody opens at 3am are dead docs; attach the safe path to the dangerous control

## Promotion log

(none yet)
