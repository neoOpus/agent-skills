# Skill Supermind

`skill-supermind` is a dependency-free Agent Skill for turning skill collections into a searchable, hierarchical, evidence-bearing graph. It provides a lean router in `SKILL.md` plus a Python/SQLite indexer designed for large collections.

## Why this exists

Normal skill discovery is usually “load every name and description.” That works until a collection grows, overlaps, or develops dependencies. This skill adds:

- deterministic indexing and content hashes;
- an append-only, redacted execution journal for route decisions and outcomes;
- full-text search plus tag/domain filters;
- typed graph relationships and bounded neighbor expansion;
- validation against the current Agent Skills specification;
- an evaluation loop that improves routing from real executions;
- a separate, low-friction human learning routine.

## Quick start

```bash
# Validate a collection without writing an index
python scripts/skill_graph.py validate /path/to/skills

# Build or atomically refresh an index
python scripts/skill_graph.py index /path/to/skills \
  --db .skill-brain/index.sqlite3 \
  --manifest assets/registry.example.json

# Reuse unchanged content hashes when only a small part changed
python scripts/skill_graph.py index-incremental /path/to/skills \
  --db .skill-brain/index.sqlite3 \
  --manifest assets/registry.example.json

# Retrieve candidates with ranking explanations
python scripts/skill_graph.py query .skill-brain/index.sqlite3 \
  "build an accessible React checkout" --limit 8 --explain

# Select one lead plus bounded support, validator, and fallback roles
python scripts/skill_graph.py route .skill-brain/index.sqlite3 \
  "build an accessible React checkout" --min-coverage 2

# Optional route journaling; task text is withheld unless explicitly reviewed
python scripts/skill_graph.py route .skill-brain/index.sqlite3 \
  "build an accessible React checkout" \
  --journal .skill-brain/execution-journal.sqlite3 --journal-opt-in

# Apply only the explicitly active, approved calibration policy version
python scripts/skill_graph.py route .skill-brain/index.sqlite3 \
  "build an accessible React checkout" \
  --policy-artifact .skill-brain/calibration-policy.json

# Store redacted task content only after privacy review
python scripts/skill_graph.py route .skill-brain/index.sqlite3 \
  "build an accessible React checkout" \
  --journal .skill-brain/execution-journal.sqlite3 --journal-opt-in \
  --privacy-reviewed --store-task-content

# Detect stale source files or graph changes
python scripts/skill_graph.py check .skill-brain/index.sqlite3 skills \
  --manifest skills/skill-supermind/assets/registry.example.json

# Measure positive and no-trigger routing cases
python scripts/skill_graph.py evaluate .skill-brain/index.sqlite3 \
  skills/skill-supermind/assets/eval-cases.example.json

# Score realistic held-out domain queries with graded relevance judgments
python scripts/skill_graph.py evaluate-domain .skill-brain/index.sqlite3 \
  skills/skill-supermind/assets/domain-benchmark.example.json --limit 10 --k 3

# Evaluate repeated realistic query families and no-trigger controls
python scripts/skill_graph.py evaluate-domain .skill-brain/index.sqlite3 \
  skills/skill-supermind/assets/heldout-evaluation.example.json --limit 10 --k 3

# The held-out corpus includes adversarial keyword-bait and near-miss controls;
# inspect false_activation_rate and false_activation_analysis in the JSON report.

# Create and verify a separate append-only execution journal
python scripts/skill_graph.py journal-init .skill-brain/execution-journal.sqlite3
python scripts/skill_graph.py journal-record .skill-brain/execution-journal.sqlite3 \
  decision '{"query":"build a checkout","lead":"react-best-practices"}' \
  --provenance '{"index":"index.sqlite3"}'
python scripts/skill_graph.py journal-verify .skill-brain/execution-journal.sqlite3

# Report verified success, partial, failure, and abstention rates
python scripts/skill_graph.py journal-evaluate .skill-brain/execution-journal.sqlite3

# Render a human-readable weekly operations report
python scripts/skill_graph.py weekly-report .skill-brain/execution-journal.sqlite3 \
  --output .skill-brain/weekly-report.txt

# Emit the same report as a machine-readable automation artifact
python scripts/skill_graph.py weekly-report .skill-brain/execution-journal.sqlite3 \
  --format json --output .skill-brain/weekly-report.json

# Open the local dashboard, including the weekly action queue
python scripts/dashboard.py --db .skill-brain/index.sqlite3 \
  --journal .skill-brain/execution-journal.sqlite3 --reports .skill-brain

# Fail CI on routing regressions, journal tampering, or calibration drift
python scripts/skill_graph.py ci-check .skill-brain/index.sqlite3 \
  .skill-brain/execution-journal.sqlite3 \
  skills/skill-supermind/assets/eval-cases.example.json \
  .skill-brain/ci-baseline.json --minimum-samples 5 \
  --drift-window-days 30 --drift-threshold 0.15

# Derive confidence thresholds from verified outcomes and score held-out cases
python scripts/skill_graph.py calibrate .skill-brain/execution-journal.sqlite3 \
  .skill-brain/index.sqlite3 skills/skill-supermind/assets/heldout-cases.example.json \
  --min-samples 5 --target-success-rate 0.8 \
  --temporal-window-days 30 --temporal-drift-threshold 0.15

# Create, approve, promote, verify, and monitor a versioned calibration policy
python scripts/skill_graph.py policy-create .skill-brain/calibration-policy.json \
  calibration-report.json --created-by researcher
python scripts/skill_graph.py policy-approve .skill-brain/calibration-policy.json 1 \
  --approved-by reviewer
python scripts/skill_graph.py policy-promote .skill-brain/calibration-policy.json 1 \
  --actor release-manager
python scripts/skill_graph.py policy-verify .skill-brain/calibration-policy.json
python scripts/skill_graph.py policy-drift .skill-brain/calibration-policy.json \
  fresh-calibration-report.json

# Inspect typed relationships
python scripts/skill_graph.py neighbors .skill-brain/index.sqlite3 \
  skill-supermind --depth 2

# Benchmark deterministic synthetic corpora at increasing scale
python scripts/benchmark_synthetic.py --sizes 100,1000,10000,100000 \
  --query-count 5 --route-count 2

# Compare full rebuilds with content-hash refreshes
python scripts/benchmark_synthetic.py --compare-incremental \
  --sizes 10000,100000 --change-ratio 0.01

# Bound a large benchmark and stop before allocation if projections are unsafe
python scripts/benchmark_synthetic.py --sizes 10000,100000 \
  --timeout-seconds 600 --phase-timeout-seconds 120 \
  --disk-budget-gb 8 --memory-warning-gb 1 --abort-on-risk
```

Replace `/path/to/skills` and the database path as needed. Python 3.10+ is the only runtime dependency. SQLite FTS5 is detected automatically; without it, search still works through a compatibility fallback and reports reduced ranking quality.

Calibration uses Wilson lower-bound ranking for threshold selection, derives per-skill and per-domain policies from verified outcomes, and reports recent-versus-baseline temporal drift. Domain policies are selected only when the routed lead has a recorded domain; otherwise the global policy remains the fallback.

The `ci-check` command is a read-only, fail-closed quality gate. It requires a versioned baseline containing `routing.metrics` (`hit_rate`, `forbidden_rate`, and `no_trigger_false_activation_rate`) plus `calibration_drift.status` and `calibration_drift.drift_detected`. It fails if routing metrics regress, the journal hash chain is invalid, current drift is detected, required positive/no-trigger coverage is missing, or an input database changes during the check. The command emits JSON and exits `1` on any failure, making it suitable for CI steps.

The weekly report is read-only and combines verified outcome rates, abstention reasons, failed or unselected routing records, temporal calibration drift, and a prioritized `action_items` queue. Action items are recommendations for human review, never automatic policy mutations. Use `--format json` to feed the same report into dashboards, CI, or scheduled review tooling. The local dashboard discovers the newest bounded set of report JSON files and presents the latest weekly action queue with open/acknowledged/resolved status and priority indicators. Its report APIs expose scan diagnostics including entries visited, depth and file caps, skipped links or oversized files, parse errors, truncation status, elapsed time, and the number/names of benchmark artifact trees excluded from the curated operational scan. Benchmark tree names beginning with `bench-`, `benchmark-`, `incremental-`, `resource-`, `calibration-check`, or `route-journal-` are skipped automatically; pass repeatable `--benchmark-tree PATH` options for other artifact trees. Scan limits are configurable with `--scan-max-entries`, `--scan-max-depth`, `--scan-max-files`, and `--scan-max-file-bytes`; the effective values and benchmark exclusions are returned by `/api/health`. For request-scoped benchmarking without restarting, `/api/overview`, `/api/calibration`, `/api/benchmarks`, `/api/weekly`, and `/api/health` accept the corresponding query parameters `scan_max_entries`, `scan_max_depth`, `scan_max_files`, and `scan_max_file_bytes`, for example `/api/weekly?scan_max_entries=25000&scan_max_depth=6`. Overrides apply only to that request, are reported as both effective and configured limits, and bypass the shared report-directory cache so one benchmark shape cannot contaminate another. Duplicate, non-integer, non-positive, or above-ceiling values are rejected; hard maxima are 100,000 entries, depth 32, 20,000 files, and 100,000,000 bytes per file. Report-directory scans also use a lightweight in-memory metadata cache. By default, unchanged directories produce a fresh cache hit; changed directory/file metadata records explicit invalidation reasons and rebuilds the scan. Pass `--cache-content-hash` when metadata-only validation is insufficient. The optional mode computes SHA-256 hashes for cached report files when building the cache and rehashes them after metadata validation on every cache check, detecting content replacements that preserve size and modification time at the cost of additional report-file read I/O. It does not replace directory validation: newly added or removed paths still require observable directory metadata changes or manual invalidation. If an operator replaces report artifacts externally while preserving all observed metadata, send an empty-body `POST /api/cache/invalidate` to clear only the in-memory report cache. The loopback-only endpoint records the `operator_request` reason, retains lifetime hit/miss/invalidation counters, and reports that the next complete scan will be counted as a miss and rebuild the cache; it does not modify reports, SQLite files, acknowledgement state, or benchmark trees. Cache status, freshness, validation method, hashed-file count, check/hit/miss counts, computed hit rate, last rebuild time, and last invalidation metadata are included in report scan diagnostics and `/api/health`. The overview's compact **Report cache** panel surfaces the lifetime hit rate (`hits / checks`), latest invalidation reasons, event counters, validation mode, and last rebuild timestamp. Its **Dashboard health** panel is populated from `/api/health` and shows the effective report root, entry/depth/file/byte limits, all effective benchmark-tree exclusions, explicitly configured exclusions, automatic benchmark prefixes, and cache validation mode. Each weekly response also includes a freshness comparison between the report period end, report file modification time, and the latest journal event timestamp; the dashboard marks the report stale when either source timestamp is behind the journal head and unknown when a timestamp cannot be compared. Treat drift and failure counts as review signals; validate any policy change against held-out cases first.

For explicit operational curation, start the dashboard with `--report-manifest PATH`. The versioned manifest is authoritative: only listed files are eligible, unlisted JSON files are ignored, and listed files remain eligible even when they sit under a benchmark-style directory. Manifest order is priority order when entry or file caps apply. Paths must be unique, normalized `/`-separated relative paths under the report root, use no `.`/`..` components, and end in `.json`; absolute paths, backslashes, and traversal are rejected. Symlink/junction components are skipped. The manifest is validated and loaded at startup, so restart the dashboard after changing it. `/api/health` exposes its path, SHA-256, schema version, selection mode, and complete allowlist.

```json
{
  "schema_version": 1,
  "kind": "skill-supermind-curated-report-manifest",
  "reports": [
    "weekly.json",
    "operations/daily.json",
    "bench-smoke/operational-report.json"
  ]
}
```

Report browsing is split into two explicit API contracts. `GET /api/curated-reports` uses the operational manifest/prefix scan, returns non-benchmark report summaries, and reports how many benchmark-typed documents were separated. `GET /api/benchmarks` performs its own bounded scan of top-level benchmark JSON plus recognized/configured benchmark trees; it does not reuse the operational report cache or its counters. Its response identifies `scope: benchmark_reports`, lists effective benchmark roots and missing roots, and includes independent entries/files/directories/skipped/capped/error/timing statistics. Both endpoints accept the same per-request scan limit overrides, and `/api/overview` includes compact summaries and both independent scan statistic objects.

`GET /api/skipped-benchmark-trees` inventories recognized and configured benchmark roots without recursively traversing them. For each root it reports the operating system's root metadata size, immediate file bytes, direct file/directory/link counts, modification time, exclusion sources, active/inactive state, and read errors. `shallow_size_bytes` is explicitly defined as root metadata bytes plus immediate child file bytes; nested directory contents are never opened or measured. The dashboard's **Skipped trees** view presents these shallow statistics and labels inactive manifest-mode roots rather than claiming they are excluded by prefix curation.

`GET /api/scan/dry-run` accepts the same request-scoped limit parameters and returns a read-only explanation of the current scan decisions without changing cache contents or hit/miss counters. Its `paths` object sorts every enumerated path into four buckets: `included` for valid JSON objects admitted within all caps, `skipped` for symlinks/junctions, benchmark trees, and non-report extensions, `capped` for paths omitted by entry/depth/file limits, and `rejected` for oversized, unreadable, malformed, non-UTF-8, or non-object JSON files. Each decision includes a stable reason and applicable limit/size details. If `max_entries` stops traversal, `truncated` is true and `unseen_paths_enumerated` is false; the report does not claim to enumerate paths that were never visited. With an explicit manifest, `unlisted_paths_enumerated` is false because discovery examines the allowlist directly rather than walking unrelated report-root paths.

The dashboard's **Mark acknowledged** and **Mark resolved** controls write only to a versioned local overlay at `<reports>/.dashboard-action-state.json` by default. An explicit **Reopen** control is available for acknowledged or resolved actions; it requires a non-empty operator note (up to 2,000 characters) and accepts an optional actor identity (up to 256 characters). Reopen persists the operator status as `reopened` while presenting the effective weekly status as `open`, with the note, actor, and update timestamp retained for review. The overlay is keyed by the report's stable relative path/period identity and action ID, is replaced atomically, and is merged into the read-only weekly response. Weekly report JSON, SQLite indexes, and the execution journal are never rewritten. The write endpoint is available only when the server binds to loopback; use `--action-state PATH` to choose a different local overlay. A corrupt or unsupported overlay is surfaced as an error and is not overwritten. The action queue can filter by priority, status, report period, and affected skill; the active view and filters are persisted in the URL query string so a review session can be bookmarked or shared locally.

Benchmark resource controls are cooperative: wall-clock and phase timeouts are checked before and after phases, while disk and memory projections are reported before allocation. The JSON report distinguishes completed, early-aborted, and timed-out results; `--abort-on-risk` makes projection failures fail before work begins. Memory measurements use Python's `tracemalloc`, not process RSS, and disk/memory projections are conservative planning estimates rather than measured performance claims.

## Repository example

The bundled `assets/registry.example.json` connects the skills in this repository. To use it from the repository root:

```bash
python skills/skill-supermind/scripts/skill_graph.py index skills \
  --db .skill-brain/index.sqlite3 \
  --manifest skills/skill-supermind/assets/registry.example.json
```

The generated `.skill-brain/` directory should normally be ignored by source control.

## Files

```text
skill-supermind/
├── SKILL.md                         # router and non-negotiable workflow
├── README.md                        # human-facing quick start
├── assets/
│   ├── daily-learning-loop.md       # 60–90 minute learning session
│   ├── execution-log.md             # append-only routing evidence
│   ├── eval-cases.example.json      # positive and no-trigger routing cases
│   ├── domain-benchmark.example.json # held-out graded domain relevance benchmark
│   ├── weekly-review.md             # weekly consolidation loop
│   ├── dashboard.html                # local dashboard UI with filters and operator action controls
│   └── registry.example.json        # typed graph overlay
├── references/
│   ├── architecture.md              # data flow, scale, failure modes
│   ├── decision-log.md              # auditable decisions and test matrix
│   ├── graph-schema.md              # authoring and edge semantics
│   ├── learning-system.md           # cognition and daily practice
│   └── sources.md                   # external sources and update policy
├── scripts/
│   ├── benchmark_synthetic.py      # deterministic scale benchmark harness
│   ├── dashboard.py                # local dashboard server, read APIs, action overlay, and cache invalidation
│   └── skill_graph.py              # index/query/route/journal/calibrate/evaluate/validate/neighbors/stats
└── tests/
    └── test_skill_graph.py          # dependency-free unit tests
```

## Design promises

- **Standards-compatible:** no required extension to other skills.
- **Progressive disclosure:** the agent loads candidates, not the whole catalog.
- **Deterministic:** stable IDs, ordering, hashes, and atomic refreshes.
- **Portable:** Python standard library only; no package installation.
- **Auditable:** JSON output, explicit graph schema, validation, and tests.
- **Evidence-safe:** execution events are separately stored, recursively redacted, append-only, and hash-verifiable.
- **Policy lifecycle:** calibration candidates are versioned, explicitly approved, promoted, rolled back, and checked for drift.
- **Private by default:** automatic route journaling is opt-in and withholds task content unless privacy review and storage are both explicit.
- **Outcome-aware:** verified journal reports break down success, partial, failure, and abstention rates by skill and typed relation.
- **Calibrated:** offline thresholds require minimum samples, are scored on independent held-out cases, and report before/after artifact fingerprints to prove no mutation.
- **Held-out realistic:** graded labels, repeated query families, no-trigger controls, and adversarial lexical-bait cases expose ranking quality and false activation separately.
- **Fail-closed retrieval:** a negative-evidence gate abstains when broad FTS overlap lacks an action, explicit skill name, or sufficiently specific content anchor; reports include the gate reason and evidence counts.
- **Measurable:** routing is evaluated with precision-oriented positive and no-trigger cases.
- **Semantically auditable:** held-out domain judgments grade relevance from 0–3 and report precision, recall, MAP, MRR, and nDCG.
- **Stale-safe:** source and manifest hashes can be checked before routing.
- **Incrementally efficient:** unchanged content hashes can be reused while preserving atomic snapshot replacement.
- **Incrementally better:** policy changes require evidence and regression tests.

## Scaling notes

For up to roughly one million skills, keep one source file per skill, index metadata in SQLite, and enable FTS5. Keep bodies searchable but avoid returning them in query results. Partition by corpus only when write contention, corpus-specific permissions, or operational ownership require it.

Do not put volatile runtime state inside `SKILL.md`. Keep learning logs outside the routing contract, promote only stable lessons, and version graph manifests alongside meaningful routing changes.
