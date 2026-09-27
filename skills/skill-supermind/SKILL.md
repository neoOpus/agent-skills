---
name: skill-supermind
description: Build, validate, index, query, and connect large collections of Agent Skills. Use for a skills-of-skills router, hierarchical skill discovery, hashtag-based knowledge graphs, skill deduplication, dependency routing, catalog maintenance, or millions-scale skill search. Also use when deciding which existing skills should compose a task before creating a new one.
license: MIT
compatibility: Requires Python 3.10+ for the bundled indexer. SQLite FTS5 is used when available, with a slower standard-library fallback.
metadata:
  author: neoOpus
  version: "1.0.0"
  tags: "skill-management, knowledge-management, graph, routing, second-brain"
---

# Skill Supermind

A compact control plane for finding, validating, composing, and improving other skills. It treats a skill collection as a versioned knowledge graph—not a folder of prompts.

## Core invariants

1. **Standard first:** a skill remains a valid Agent Skills directory with `SKILL.md` as its source of truth.
2. **Search before creation:** reuse or compose existing skills before proposing a new one.
3. **Load minimally:** return a small candidate set; read full skills only after selection.
4. **Separate facts from routing:** search evidence, graph edges, and user constraints remain distinct.
5. **Preserve provenance:** every index row records path, content hash, and source metadata.
6. **Preserve execution evidence:** journal decisions, outcomes, and notes in a separate append-only, redacted store with verifiable hashes.
7. **Improve from executions:** change routing rules only after repeated evidence, never from one anecdote.
8. **Fail closed:** malformed metadata, duplicate IDs, broken edges, stale index state, and unverifiable journal history block confident routing.

## Workflow

### 1. Frame the outcome

Write the task as: desired outcome, constraints, risk, evidence of completion, and a time budget. Ask only for a decision that materially changes the result.

### 2. Build or refresh the index

From this skill directory, run:

```bash
python scripts/skill_graph.py index /path/to/skills --db /path/to/skill-brain.sqlite3 --manifest /path/to/graph.json
```

The index is transactional and deterministic. Re-index after skill or graph changes. Use the content-hash refresh when only a small portion of the catalog changed:

```bash
python scripts/skill_graph.py index-incremental /path/to/skills --db /path/to/skill-brain.sqlite3 --manifest /path/to/graph.json
```

Incremental refresh reuses unchanged `SKILL.md` rows, reparses changed/new files, removes deleted skills, updates tags/FTS/edges, and atomically replaces the valid snapshot only after validation. A full `index` remains the recovery and integrity baseline. Before routing, run `check` when the source set is available:

```bash
python scripts/skill_graph.py check /path/to/skill-brain.sqlite3 /path/to/skills --manifest /path/to/graph.json
```

A non-zero result means the index is stale. Never route from a stale index when the source set is available.

### 3. Retrieve a small candidate set

```bash
python scripts/skill_graph.py query /path/to/skill-brain.sqlite3 "task wording" --limit 8 --min-coverage 2 --explain
```

Add `--tag`, `--domain`, and `--min-confidence` only when they improve precision. Retrieval text should preserve the user's real nouns, verbs, constraints, and technology names.

### 4. Expand through the graph

```bash
python scripts/skill_graph.py neighbors /path/to/skill-brain.sqlite3 skill-name --depth 2
```

Use typed edges, not hashtag similarity alone:

- `parent` — specialization or containment
- `composes` — a workflow orchestrates another skill
- `requires` — a skill cannot work correctly without another
- `validates` — one skill checks another skill's output
- `alternative-to` — interchangeable options with different tradeoffs
- `supersedes` — newer canonical replacement
- `related-to` — weak semantic connection

See [graph schema](references/graph-schema.md) before authoring edges.

### 5. Route and compose

For each candidate, record:

- match reason and evidence
- role: lead, support, validator, fallback
- conflicts or missing prerequisites
- confidence and uncertainty

Prefer one lead skill, at most three support skills, and one independent validator. The `route` command applies this bounded role policy from direct typed graph edges; it does not load the whole catalog. Do not load every related skill. If no candidate clears the quality bar, propose a new narrowly scoped skill and link its parent and relations.

### 6. Verify and learn

After execution:

1. Record the route decision before execution, including the index identity, selected roles, constraints, and evidence.
2. Record the outcome as a child event; use `success`, `partial`, `failure`, or `abstain` in the payload and keep the evidence concise.
3. Verify the journal before using historical evidence for routing or calibration.
4. Run or update a small evaluation case whenever routing behavior changes.
5. Capture false positives, missed matches, conflicts, and unnecessary context.
6. Add a candidate lesson to [the execution log](assets/execution-log.md); do not rewrite routing policy yet.
7. Promote only repeated, evidence-backed patterns into the index manifest or this skill.
8. Run validation and tests before accepting the change.

Journal commands keep evidence separate from the index:

```bash
python scripts/skill_graph.py journal-init /path/to/execution-journal.sqlite3
python scripts/skill_graph.py journal-record /path/to/execution-journal.sqlite3 decision '{"query":"...","lead":"..."}' --provenance '{"index":"index.sqlite3"}'
python scripts/skill_graph.py journal-record /path/to/execution-journal.sqlite3 outcome '{"status":"success","evidence":"..."}' --parent EVENT_ID
python scripts/skill_graph.py journal-verify /path/to/execution-journal.sqlite3
```

Secrets, authorization headers, tokens, email addresses, and explicitly named keys are redacted before storage. The journal is SQLite-backed, append-only, transactional, and hash-chained; a failed append does not add a partial event.

Generate a read-only outcome report by skill and typed relation:

```bash
python scripts/skill_graph.py journal-evaluate /path/to/execution-journal.sqlite3
```

The report verifies the journal chain, attributes child outcomes to the decision's lead/support/validator/fallback roles, and reports success, partial, failure, and abstention counts and rates globally, by skill, by relation, and by skill–relation pair. It also reports unlinked outcomes and whether the journal artifact remained unchanged.

Automatic route journaling is opt-in. Without `--journal-opt-in`, route performs no journal access and stores nothing. With opt-in, the default event stores a minimized route, a query hash, and `[WITHHELD]` instead of task text. Storing task content requires both `--privacy-reviewed` and `--store-task-content`; secrets and configured keys are redacted before the event is written. The route response reports whether content was stored, withheld, or redacted.

```bash
python scripts/skill_graph.py route INDEX.sqlite3 "task wording" \\
  --journal execution.sqlite3 --journal-opt-in

python scripts/skill_graph.py route INDEX.sqlite3 "task wording" \\
  --journal execution.sqlite3 --journal-opt-in \\
  --privacy-reviewed --store-task-content --journal-redact-key customer_id
```

Use the evaluation loop in [decision log](references/decision-log.md).

### 7. Evaluate realistic held-out domains

Use graded relevance judgments for domain-specific semantic routing evaluation. Every case must be marked `split: "heldout"` and provide integer grades from 0 to 3:

```bash
python scripts/skill_graph.py evaluate-domain INDEX.sqlite3 \\
  assets/domain-benchmark.example.json --limit 10 --k 3
```

Grades mean: `0` irrelevant, `1` related, `2` relevant, and `3` highly relevant. The bundled `assets/heldout-evaluation.example.json` adds realistic product, delivery, learning, and no-trigger cases with `group_id` values for repeated-query families. It now also includes adversarial controls for keyword-only bait, product names without intent, generic UI vocabulary, and deployment/queue near misses. The evaluator reports precision@k, recall@k, MRR, MAP, nDCG@k, top-1 accuracy, negative abstention accuracy, false activation rate, per-domain breakdowns, repeated-group consistency, and false-activation IDs grouped by domain and query family. It validates that judged skills exist and rejects training cases or malformed grades. This measures ranking against human-style judgments; it is not a claim that lexical FTS5 equals human semantic understanding.

### 8. Calibrate confidence and measure abstention

Calibration is an offline analysis. It reads verified decision/outcome pairs from the journal, computes observed outcome rates and Brier score, and proposes a threshold only when the minimum sample count is met:

```bash
python scripts/skill_graph.py calibrate JOURNAL INDEX HELDOUT_CASES \\
  --min-samples 5 --target-success-rate 0.8
```

A decision should include a lead skill and numeric confidence, for example:

```json
{"query":"index catalogs","route":{"lead":{"skill_id":"catalog-indexer","confidence":0.92}}}
```

A matching child outcome must use `success`, `partial`, `failure`, or `abstain`. Held-out cases are scored only after thresholds are derived; they must not be used to fit the threshold. Threshold candidates are ranked using the Wilson lower bound after the observed-score and minimum-sample gates, and the selected bound is reported as `selected_wilson_lower`. Calibration now also derives `domain_policies` from the lead domain recorded in each decision. The command reports coverage, selective accuracy, positive hit rate, negative abstention rate, false activation rate, forbidden selection rate, and per-skill/per-domain/global policies. It hashes the index and journal before and after analysis and reports `artifacts_unchanged`, `index_mutated`, `journal_mutated`, and `routing_policy_changed`; it does not mutate the index, journal, or routing behavior.

Temporal monitoring compares the configured recent window (default 30 days) with the preceding baseline window. It reports window cutoffs, sample counts, success-rate deltas, and `temporal_drift`; insufficient samples are reported as `insufficient_data`, never as proof of stability. Configure it with `--temporal-window-days` and `--temporal-drift-threshold`.

Calibration output is a candidate, not an active routing policy. Store it in a versioned policy artifact, require a named approval, promote it explicitly, and retain the prior active version for rollback:

```bash
python scripts/skill_graph.py policy-create .skill-brain/calibration-policy.json calibration-report.json --created-by researcher
python scripts/skill_graph.py policy-approve .skill-brain/calibration-policy.json 1 --approved-by reviewer
python scripts/skill_graph.py policy-promote .skill-brain/calibration-policy.json 1 --actor release-manager
python scripts/skill_graph.py policy-rollback .skill-brain/calibration-policy.json --actor release-manager
```

The artifact records candidate, approved, active, superseded, and rolled-back states, approval metadata, lifecycle events, source fingerprints, and a SHA-256 integrity digest. Use `policy-verify` to validate the artifact. Use `policy-drift ARTIFACT FRESH_REPORT` to compare the active policy with a fresh calibration report; changed thresholds, source fingerprints, or policy structure produce `drift_detected` and a non-zero exit status. Pass the artifact to `route --policy-artifact FILE` to apply only the explicitly active version; candidate, approved-only, and rolled-back versions are never applied.

### 9. Benchmark scale changes

Use the dependency-free synthetic harness before claiming catalog-scale behavior:

```bash
python scripts/benchmark_synthetic.py --sizes 100,1000,10000,100000 \
  --query-count 5 --route-count 2
```

The harness generates deterministic valid skills, indexes them, runs freshness checks, queries, and bounded routes, then emits one JSON report with machine metadata, timings, database size, corpus size, and peak Python allocation. Runs are disposable by default; pass `--work-root PATH` to retain them. Start with smaller sizes, keep free disk under the machine budget, and do not interpret a successful synthetic run as proof of semantic routing quality.

Resource controls are explicit and conservative. `--timeout-seconds` sets a wall-clock budget and `--phase-timeout-seconds` sets a per-phase budget; both are checked before and after each phase, so a single SQLite operation cannot be interrupted mid-call. `--disk-budget-gb` limits the projected working set and `--memory-warning-gb` warns on projected or observed Python allocations. Every report includes `resource_policy`, `resource_assessment`, and an `early_abort_recommendation`; projections are planning estimates, not performance measurements. Add `--abort-on-risk` to stop before allocation when a projection exceeds a configured limit. A timeout or early abort is an explicit failed result, never a pass.

To compare full rebuilds with content-hash refreshes on the same mutated corpus:

```bash
python scripts/benchmark_synthetic.py --compare-incremental \\
  --sizes 10000,100000 --change-ratio 0.01
```

The report includes initial full-index time, full rebuild time, incremental refresh time, speedup, changed/reparsed counts, database sizes, freshness checks, and the same resource-policy assessment as the standard benchmark. The incremental path still copies the prior snapshot before transactional mutation, so it reduces parsing and FTS work but does not claim zero-copy or lock-free operation.

## Commands

```text
skill_graph.py validate ROOT [--strict]
skill_graph.py index ROOT [--db DB] [--manifest FILE] [--strict]
skill_graph.py index-incremental ROOT [--db DB] [--manifest FILE] [--strict]
skill_graph.py check DB ROOT [--manifest FILE]
skill_graph.py query DB TEXT [--tag T] [--domain D] [--limit N] [--min-coverage N] [--explain]
skill_graph.py route DB TEXT [--tag T] [--domain D] [--limit N] [--min-coverage N] [--policy-artifact FILE] [--journal FILE --journal-opt-in] [--privacy-reviewed --store-task-content] [--journal-redact-key KEY]
skill_graph.py neighbors DB SKILL [--depth N] [--relation TYPE]
skill_graph.py evaluate DB CASES_JSON [--limit N]
skill_graph.py evaluate-domain DB DOMAIN_BENCHMARK [--limit N] [--k N]
skill_graph.py journal-init JOURNAL
skill_graph.py journal-record JOURNAL KIND PAYLOAD_JSON [--parent EVENT_ID] [--provenance JSON] [--redact-key KEY]
skill_graph.py journal-show JOURNAL [--limit N]
skill_graph.py journal-verify JOURNAL
skill_graph.py journal-evaluate JOURNAL
skill_graph.py weekly-report JOURNAL [--as-of ISO8601] [--window-days N] [--minimum-samples N] [--drift-threshold N] [--format text|json] [--output FILE]
skill_graph.py calibrate JOURNAL DB HELDOUT_CASES [--min-samples N] [--target-success-rate N] [--limit N] [--temporal-window-days N] [--temporal-drift-threshold N]
skill_graph.py policy-create ARTIFACT CALIBRATION_REPORT [--created-by NAME]
skill_graph.py policy-approve ARTIFACT VERSION --approved-by NAME [--note TEXT]
skill_graph.py policy-promote ARTIFACT VERSION --actor NAME [--note TEXT]
skill_graph.py policy-rollback ARTIFACT --actor NAME [--note TEXT]
skill_graph.py policy-verify ARTIFACT
skill_graph.py policy-drift ARTIFACT CALIBRATION_REPORT
skill_graph.py ci-check DB JOURNAL CASES BASELINE [--limit N] [--minimum-samples N] [--drift-window-days N] [--drift-threshold N]
skill_graph.py stats DB
benchmark_synthetic.py [--sizes N,N,...] [--work-root PATH] [--seed N] [--edge-stride N] [--query-count N] [--route-count N] [--timeout-seconds N] [--phase-timeout-seconds N] [--disk-budget-gb N] [--memory-warning-gb N] [--abort-on-risk] [--keep]
benchmark_synthetic.py --compare-incremental [--sizes N,N,...] [--change-ratio N] [--work-root PATH] [--seed N] [--edge-stride N] [--timeout-seconds N] [--phase-timeout-seconds N] [--disk-budget-gb N] [--memory-warning-gb N] [--abort-on-risk] [--keep]
```

All commands emit JSON on stdout except `weekly-report`, which defaults to a human-readable text report; pass `--format json` for the stable automation contract. Human-readable progress goes to stderr. Exit code `0` means success; `1` means validation or operation failure.

## Quality gates

### Before indexing

- Official `name` and `description` constraints pass.
- `name` matches its parent directory.
- IDs are unique.
- Manifest targets exist and are not self-edges.
- Graph schema and relation types are valid.

### Before routing

- Index is newer than all source files and its manifest.
- Query returns evidence, not only names.
- Filters do not hide a required prerequisite.
- Selected skills have compatible instructions and risk levels.
- The composition has a clear lead and bounded context.

### Before publishing a change

- Unit tests pass.
- `check` reports a current index when the source set is available.
- A realistic fixture indexes and queries successfully.
- Journal events are redacted, parent-linked, append-only, and pass hash-chain verification.
- Calibration thresholds meet minimum-sample requirements and are fitted only from verified journal outcomes.
- Held-out cases are scored independently and include positive, no-trigger, and adversarial keyword-bait controls.
- Trigger and no-trigger cases were checked.
- Changed routing behavior is supported by at least two independent executions or one safety-critical failure.
- Weekly report action items are reviewed as human-owned signals; they never mutate policy automatically. Dashboard acknowledgements are stored in a separate local overlay and never rewrite source reports. Reopen is an explicit operator action requiring a note, optionally identifying the actor; its persisted `reopened` status is exposed as effective `open` without losing the operator history.
- Dashboard weekly freshness compares the report period end, report file modification time, and journal head timestamp; stale or unknown comparisons remain visible review signals.
- Dashboard operational report discovery either uses a validated versioned explicit report manifest or skips recognized benchmark artifact trees; benchmark work trees are not allowed to crowd out curated operational reports. Manifest paths are unique safe relative JSON files, remain authoritative across benchmark-style directories, and are surfaced with their digest and selection mode in health diagnostics.
- Curated operational reports and benchmark reports use separate dashboard API paths. Benchmark discovery scans top-level benchmark JSON and configured/recognized benchmark trees with its own lock, traversal statistics, limits, and no shared operational-cache counters; benchmark-typed documents are separated from curated report summaries.
- Skipped benchmark-tree inventory measures only root metadata and immediate child file bytes, reports direct entry classes and exclusion sources, and never opens or recursively measures nested contents. The dashboard must label these values as shallow rather than total tree size.
- Dashboard scan limits are explicitly configurable, validated as positive integers, and reported by the health endpoint. Per-request benchmark overrides are context-scoped, ceiling-bounded, reported alongside configured limits, and bypass the shared report cache to prevent cross-shape contamination. The dry-run scan endpoint classifies every enumerated path as included, skipped, capped, or rejected without mutating cache counters, and explicitly reports when entry limits prevent unseen paths from being enumerated. The overview health panel uses `/api/health` as its source of truth and keeps effective limits and benchmark exclusions visible to operators.
- Dashboard report discovery uses a metadata-validated cache for unchanged directories; optional SHA-256 content validation detects metadata-preserving replacements of already cached report files without claiming that directory additions are discoverable without directory metadata changes. Cache checks, lifetime hit rate, invalidation reasons, last rebuild time, and freshness remain explicit in API diagnostics and the overview cache panel. Manual cache invalidation is loopback-only, clears only volatile report-scan state, and never rewrites source artifacts or acknowledgement state.
- CI quality gates use a versioned baseline and fail closed on routing regressions, invalid journal chains, missing positive/no-trigger coverage, or detected calibration drift.
- README and source notes are updated when interfaces change.

## Scale boundaries

SQLite is appropriate for millions of metadata rows and typical skill collections. Keep the hot path in SQLite FTS5; avoid loading catalogs into agent context. A single `SKILL.md` should normally stay below 500 lines. Split deep references rather than creating one mega-skill. If writes become multi-writer, move the indexer to a transactional service; do not share a live SQLite database over an unreliable filesystem.

## Human parallel practice

The same architecture should support the user's own learning without turning every note into a database row. Use:

1. one active question,
2. one compressed explanation,
3. one concrete example,
4. one contrast or connection,
5. closed-book recall,
6. a spaced review.

Templates live in [assets/](assets/). The evidence-informed rationale and guardrails are in [learning system](references/learning-system.md).

## References

Load only when needed:

- [Architecture and threat model](references/architecture.md)
- [Graph schema](references/graph-schema.md)
- [Auditable decision log and test matrix](references/decision-log.md)
- [Human learning system](references/learning-system.md)
- [Sources and update policy](references/sources.md)
