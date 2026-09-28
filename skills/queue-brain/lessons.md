# Queue Brain — Lessons

Cross-project lessons extracted from queue-brain sessions. Promoted patterns
get rewritten into SKILL.md rules; everything here stays terse (1–2 lines).

<!-- format: - YYYY-MM-DD · project · lesson -->

## Working set

<!-- publish trigger: last suggested at 189 · reset after running publish-queue-brain.mjs -->

## 2026-09-27 — publish-flow lessons (v1.3.0 ship)

- 2026-09-27 · sider-clone · **Committing an untracked directory bypasses per-file path discipline**: `git add <dir>` shipped 4 `__pycache__/*.pyc` bytecode files to a public repo because the ignore class didn't exist yet. The ignore class ships BEFORE the first add, not after the first incident — an explicit-path list can't protect what it doesn't enumerate.
- 2026-09-27 · sider-clone · **A version field that lives in N places needs one writer**: metadata.json said 1.3.0 while the shipped SKILL.md frontmatter still said 1.2.0 — two versions of truth in one package. Fix at the writer: the publish script now bumps frontmatter and metadata in lockstep, and the dry-run proves the delta.
- 2026-09-27 · sider-clone · **A quiet push hides its own receipt**: `-q` on `git push` suppressed the confirmation, and the next push range made my own commit look like an interloper's. Match the commit message before diagnosing a foreign pusher; suspect the instrument (a silent flag) before the world.
- 2026-09-27 · sider-clone · **A resolution must be attached to the thing it resolves**: the phantom handback's RESOLVED pointer was appended at the ledger tail but reported as "appended to :160" — the intent's line number, not the bytes' landing site. An append-only file grows at the tail; only a line-anchored insert puts the closure where a sweeping reader will meet the invitation. Verify the landing site of any "appended at :N" claim before reporting it.

- 2026-09-23 · sider-clone · DRY-RUN MUST BE THE TOOL'S OWN MODE: queueSurgery always rewrote the queue, so a "I only counted" callback leaked its in-memory mutations to disk — added dryRun:true (full read+mutate+diff cycle, never writes queue or journal; proved byte-identical under deliberate dirtying). A dry-run simulated by a careful caller over an always-writing tool is a real run waiting for a careless callback.
- 2026-09-13 · all · SESSION START: re-read ~/.agents/skills/queue-brain/lessons.md before the first re-rank — cross-harness lessons only load if the file is actually read (SKILL.md rule added 09-13 after the junction setup made sharing possible but not automatic)
- 2026-09-13 · all · DEDUPE-BY-REALITY BEATS DEDUPE-BY-TEXT: the queue's dominant corruption is not rephrased duplicates but work ALREADY DONE sitting as backlog — SKILL.md now mandates a reality pass ('is the outcome already true?') before ranking, plus a batched verify-then-close sweep at 20+ entries or cold session start [PROMOTED 09-13 → DEDUPE rule]
- 2026-09-13 · all · POSITIVE CONTROL: analyzer/check reporting 'clean' is unproven until it catches an injected bug — applies to any check whose failure mode is silence [PROMOTED 09-13 → Quality gate: positive-control checkbox]
- 2026-09-13 · all · PREVIEW = REAL SURFACE: rendered-page verification caught a scope bug that parsed clean — beats syntax checks, every time [PROMOTED 09-13 → Quality gate: verification checkbox extended]
- 2026-09-13 · all · TRANSIENT FAIL = RETRY BEFORE INVESTIGATION: infra check failing once under concurrent load is noise until it repeats twice clean; chasing ghosts hides the real red state [PROMOTED 09-13 → Instruments #6]
- 2026-09-14 · neo-taskbar-mod · VERIFY WITH THE TARGET COMPILER BEFORE HANDOFF: a 2.2k-line mod accumulated nested-function brace damage across many edit turns; Windhawk ships clang locally — `"C:/Program Files/Windhawk/Compiler/bin/clang++.exe" -fsyntax-only -DWH_MOD -DUNICODE -includeC:/Program Files/Windhawk/Compiler/include/windhawk_api.h -Wall -Wextra mod.cpp` catches in seconds what editor diagnostics mask (its real-surface = its compiler)
- 2026-09-14 · neo-taskbar-mod · IsWindow(TRUE) ≠ OUR WINDOW: after off-thread destruction the OS recycles hwnd values, so class-name comparison (GetClassNameW vs known class) is the only cheap recycle detector — periodic heartbeat checks must test class, not just validity
- 2026-09-14 · neo-taskbar-mod · WINDHAWK DIAGNOSIS FROM OUTSIDE: mod logs are memory-only (invisible to external agents) and ModsSource is admin-protected — mirror lifecycle events to a file (FileLog) and sync via EditorWorkspace (writable) + user clicks Compile; external probes that ARE reliable: Get-Process .Modules residency, FindWindow/EnumChildWindows ground truth, SendMessageTimeout WM_NULL responsiveness, per-mod HKLM registry; probes that LIE: .NET thread StartAddress (generic stub for all threads) and RegisterWindowMessage atoms (your own call registers them)
- 2026-09-17 · sider-clone · GREP-FILTER SELF-DECEPTION: my archive-pass filter excluded dash-server.mjs ('too big, obviously referenced') and hid that it spawns unlock-cascade.mjs — dash-server SPAWNS scripts by string-joined paths (`join(HERE,'x.mjs')`), so grep for the bare filename, never for `x.mjs` literals; classify spawn sites by reading them, not by pattern-match volume. Restored the file before finishing.
- 2026-09-17 · sider-clone · DEAD-ONE-OFF PROOF = RE-QUERY THE DATA, not mtime: backfill/repair scripts looked stale but proving them dead took one query (0 queue entries left in scope) — date-only archiving risks deleting a converging sweep mid-run; data-state beats file-age.
- 2026-09-17 · sider-clone · PACKAGE TYPE LIES: package.json said commonjs while every script is ESM .mjs — harmless until a tool trusts it (node:test resolution, bundlers); one-line audit, check once per project.
- 2026-09-17 · all · ARCHIVE, NEVER DELETE, with a dated subfolder (_archive/YYYY-MM-DD-context/): 43 items moved, one restore needed within the hour — non-destructive cleanup makes the recovery cost zero and the revert path a plain mv.
- 2026-09-17 · all · PID-FILE GUARDS MULTIPLY ACROSS TARGETS: a target-scoped supervisor (pid lock at a fixed path) blocks booting a DIFFERENT target's supervisor, and AUTO-mode guardians resurrect the old one — multi-target designs need the lock to carry the target identity, and target switches need a documented kill-and-relaunch order (kill old supervisor → repoint project.json → relaunch via the stack).
- 2026-09-17 · all · KNOB-FILE DOC AS THE GATE: documenting every _work/*.json with writer-reader pairs (grep-verified at write time) turns the knob-shipped-but-never-read class into a self-auditing table - a future knob file that cannot name its reader is not done; the doc IS the positive control.
- 2026-09-17 · sider-clone · PORTABILITY RUN PAYOFF DATA: MetaMask (webpack chunks) drained ~120 modules/pass with zero infra FATALs after the 6 contract fixes — the portable pipeline now covers esbuild AND webpack bundle families (demethodify pre-transform was the unlock); future targets = fetch-crx → capture → deobfuscate.mjs, expect contract bugs only in new bundle formats.

- 2026-09-27 · sider-clone · PIPED EXIT CODES LIE: `node gate --selftest | tail` measures tail's exit, not the suite's — a 1-FAIL selftest printed FAIL and reported exit 0. Verify selftest exits with the redirect pattern (`> log 2>&1; echo $?`), never through a pipe.
- 2026-09-27 · sider-clone · A CONTROL PINNED TO THE LIVE TREE'S VERDICT INVERTS WHEN THE TREE HEALS: self-host's exit-1 subprocess control hardcoded main-only-audit as its subject, so the audit going clean made the control red on health. Fixture subjects (hermetic file whose own exit is pinned in the fixture) never rot. Recurred 2x more the same day — gate-suite's LIVE cross-check control pinned rate-degradation by name (fixed → inverted), and gate-telemetry's 1e6 modules/s floor had no contention headroom (pooled 500-module run measured 860k → red on health). Fix at the writer: hermetic fixtures, assert findings against the predicate, floors with measured headroom.

- [2026-09-24] Before chasing measurement nondeterminism, measure the ENVIRONMENT's cadence: a capture pair that had been byte-identical for four runs flipped the moment an env restart introduced a per-minute watchdog sweep spawn cadence — the inputs were provably unchanged (`find -newermt` empty) and the variance localized to surfaces with async mock flows. And a gate whose retry keys on exit≠0 cannot see an exit-0 record that flipped its numbers — pair identity (or a numeric delta vs the previous record) is the retry condition for capture-class checks.
- [2026-09-26] A FIXTURE SHRINK SILENTLY PRODUCES A DIFFERENT TEST UNLESS ITS DEFINING PROPERTY IS ASSERTED. module-count-drift's selftest spent 81-133s writing ~210,000 real module files to test a PURE function (`compareCounts` takes two count Maps — its own header says so). Moving the comparison controls onto Maps and cutting the disk fixtures to 1/10th scale gave 3.6-3.9s at 41/41. The trap: `WIDE(1688)` was "a mode change" only because every bundle moved, and at 1/10th scale that stopped being true by accident — so control 4 now ASSERTS that all 22 ratios sit outside the tolerance band, and the walk fixture asserts it is still 7-dead-of-22 with the median intact. Proof it kept its teeth: 5 mutations of a COPY (median discriminator removed, countModules stops excluding metadata, share guard removed, on-disk fixture shrunk to 11 dead, mode fixture with one bundle in band) each turned the suite red through the control that owns that bug — and the first harness run SKIPped a mutation whose anchor text had gone stale, reporting "stale, not passing" instead of counting it. (Re-transcribed verbatim from the session diff after the canonical was clobbered; see the 2026-09-27 sync-direction incident.)

- [2026-09-27] A BLIND COPY ACROSS MIRRORS IS A DESTROYING WRITE: copying repo→canonical to "fix sync" clobbered tail lessons another lane had appended mid-session (recovered only via Freebuff HTTP-cache forensics; nothing lost in the end because 00-docs/LESSONS.md carried the same lessons). Every mirror sync must diff BOTH sides first and refuse on unexplained divergence — the sync script's own --overwrite guard exists for exactly this and was bypassed by a raw cp. When two ledgers can both receive writes, neither is canonical until a tool says so.
- [2026-09-27] LOST FILE STATE LIVES IN THE APP'S HTTP CACHE: Freebuff's Cache_Data blobs retained recent file reads, session text and even a cached diff output; recovery = grep Cache_Data for ASCII anchors, then buffer-safe JSON-string termination (scan for unescaped quote, utf8-decode, JSON.parse) — byte-wise unescape mojibakes multibyte chars, and shell-quoted node -e mangles backslashes, so write the extractor as a file.
- [2026-09-27] THE CARRIED ROOT-CAUSE IS A HYPOTHESIS: resuming a wall's 3 transient reds, the prior session's "DEGRADED banner → exit 1 by design" theory died in ten minutes of reading — the banner only prints on --apply (never in a selftest), the exit-1 path (checkExitCode) cannot count degraded skips, and solo runs under 8 load-spinners exited 0. Re-derive from the code before fixing the "mechanism"; only then spend the fix.
- [2026-09-27] A CRASH VERDICT MUST CARRY THE CRASH'S WORDS: the wall reported "exit 1 with no FAIL line — a crash" for 3 gates with the children's stderr in hand and dropped, so diagnosis cost a re-run. classify() now extracts the Error/Exception line (not a trailing stack frame — first draft picked the frame and the new control caught it) into the detail. Symmetric rule: a child's test server sockets need error listeners (AGENTS day-one) — a socket reset without one is an uncaughtException AFTER the verdict printed, i.e. the exact exit-1-no-FAIL shape.

## Promotion log

- 09-21 · 7 recurring working-set classes promoted to SKILL.md "Promoted rules": lying readouts (silent-zero / degrade-to-constant / count-the-things), right-layer positive controls, absent=skip, measured gate budgets, no sleep-polling, class-not-site + fix-at-the-writer, goal-ranking every suggestion (from the 09-16..09-21 working set).
- 09-13 · DEDUPE reality pass + verify-then-close sweep → SKILL.md DEDUPE rule (from STALE-QUEUE DRIFT + DEDUPE-BY-REALITY)
- 09-13 · Positive control for silent checks → SKILL.md Quality gate checkbox (from POSITIVE CONTROL)
- 09-13 · Rendered-surface verification → SKILL.md Quality gate verification checkbox (from PREVIEW = REAL SURFACE)
- 09-13 · Transient-FAIL retry triage → SKILL.md Instruments #6 (from FLAPY CHECKS RESOLVE ON RETRY)
- 09-14 · SendMessage hook-marshaling: one-shot hook procs must unhook ONLY on the target message — any unrelated message racing in consumes the hook, the real message lands in the original wndproc with sent==1, and 'delivered' lies. Verify via hook-consumed state, not the SendMessage return.
- 2026-09-16 · sider-clone · CSS-COLUMNS MASONRY = POLL SHUFFLE: column-span:all forces a column break and any height change re-balances every column — cards visibly appear/disappear each poll. Dense CSS grid (auto-fill + grid-auto-flow:dense) gives stable slots + gap backfill; measure with rect-overlap + wasted-height probes, not vibes
- 2026-09-16 · sider-clone · KNOB FILE ON DISK ≠ KNOB WIRED: daemon-test.json existed but nothing read it — config files must be traced to a reader before counting as shipped (same class as 'endpoint added but server not restarted')
- 2026-09-16 · sider-clone · WORKER postMessage DROPS CUSTOM ARRAY PROPS: structured clone of an Array keeps indices, not expando props (anchorCount etc.) — envelope must post stats explicitly and rebuild on the main thread
- 2026-09-16 · sider-clone · PLACEHOLDER/TITLE ≠ ACCESSIBLE NAME: inputs need label-wrap or aria-label; audit live with labels.length + aria-label filter, not grep
- 2026-09-17 · all · PORTABILITY BUGS LIVE IN HIDDEN CONTRACTS, NOT LOGIC: flag-vs-positional argv, flat-vs-nested dir layouts, provider-word lists hardcoded in one file. Stress test = run the real chain on a SECOND target; every mismatch surfaces in minutes. (MetaMask run: 6 bugs, all of this class, zero logic bugs.)
- 2026-09-17 · all · WRITER/READER LAYOUT DISAGREEMENT: fix the writer (one site), not the readers (N sites) — or normalize on disk with a one-off sweep for already-written data.
- 2026-09-17 · sider-clone · GREP-FILTER SELF-DECEPTION: my archive-pass filter excluded dash-server.mjs ('too big, obviously referenced') and hid that it spawns unlock-cascade.mjs — dash-server SPAWNS scripts by string-joined paths (`join(HERE,'x.mjs')`), so grep for the bare filename, never for `x.mjs` literals; classify spawn sites by reading them, not by pattern-match volume. Restored the file before finishing.
- 2026-09-17 · sider-clone · DEAD-ONE-OFF PROOF = RE-QUERY THE DATA, not mtime: backfill/repair scripts looked stale but proving them dead took one query (0 queue entries left in scope) — date-only archiving risks deleting a converging sweep mid-run; data-state beats file-age.
- 2026-09-17 · sider-clone · PACKAGE TYPE LIES: package.json said commonjs while every script is ESM .mjs — harmless until a tool trusts it (node:test resolution, bundlers); one-line audit, check once per project.
- 2026-09-17 · all · ARCHIVE, NEVER DELETE, with a dated subfolder (_archive/YYYY-MM-DD-context/): 43 items moved, one restore needed within the hour — non-destructive cleanup makes the recovery cost zero and the revert path a plain mv.
- 2026-09-17 · sider-clone · PORTABILITY RUN PAYOFF DATA: MetaMask (webpack chunks) drained ~120 modules/pass with zero infra FATALs after the 6 contract fixes — the portable pipeline now covers esbuild AND webpack bundle families (demethodify pre-transform was the unlock); future targets = fetch-crx → capture → deobfuscate.mjs, expect contract bugs only in new bundle formats.
- 2026-09-17 · all · FRAGILITY = IMPACT x UNTESTED x CENTRALITY: rank untested code by how many outputs depend on it and how silent a wrong-result failure is, not by file size — 174 lines of transfer machinery carrying 25k modules beat 1.7k lines of dashboard. Also: TEST FIXTURES FAIL LIKE PRODUCTION — naive replaceAll corrupted string literals/keywords in the fixture itself (g→runIt hit "lit-arg"), the same corruption class the code under test guards against; word-boundary renames always.
- 2026-09-17 · sider-clone · PREVIEW RELEASE KILLS REGISTERED PID: every preview replace/registration cycle terminated the registered dev-server pid — restarting with the PS Start-Process detach recipe and NEVER calling replace:true again is the workaround; treat preview detach/attach churn as server-lethal
- 2026-09-17 · all · PROXY CATCH-ALL MOCKS: a Proxy-based chrome.* stub (known-table + auto-default per unknown path, `on*`=event stub, log-once) boots ANY extension without per-extension edits — hand-tuned stubs were the reason a second extension needed mock rewrites
- 2026-09-17 · sider-clone · EXTENSION PAGES IN PLAIN TABS: obfuscated MV3 bundles boot with runtime.id + getManifest + storage seed, but their login-gated API layer (cookie -> Authorization header) renders null until BOTH the cookie jar AND the gate's loading flags resolve; the render gate hides in `return b||p?null:` destructured from a storage-sync hook, not an obvious `if`
- 2026-09-17: web_search silently failed repeatedly on generic long queries ("X vs Y 2026 status"); retried with short noun queries returned full results. Query class: keep search terms <6 words, drop meta-words (status, 2026, best).

## sider-clone — version-watch / delta session (2026-09-18)

- Silent-zero class: a tool that still writes a report (all zeros) when its input
  tree is missing reads EXACTLY like "nothing changed". 5.32.4..5.32.9 delta
  reported bundlesScanned 0 and shipped. Rule: refuse non-empty input, exit
  non-zero, and have the caller verify the report's own counters — not the exit
  code alone.
- Windowed heuristics on generated code rot on the next build: esbuild emitted the
  second lazy-init factory at statement 154 instead of 7, so a "first 12 statements"
  scan refused EVERY bundle of one release. When the shape is distinctive, scan the
  whole body and filter by shape.
- Version identity from the store redirect (5.32.9.0) vs the manifest dir (5.32.9)
  must be compared normalized, or the watcher re-downloads and re-captures the same
  release on every cycle, forever. Normalize trailing zero segments both sides.
- Housekeeping wired to "an update happened" never runs if the run dies mid-chain:
  orphan-CRX cleanup and fingerprint refresh must fire from durable state (does a
  capture's meta.json name this file?), on every run, regardless of detection.
- Cheap measurement beats reading: an oxc-parser probe that listed factory-shaped
  declarations + call-site counts pinpointed the unpacker bug in one run, where
  three rounds of source reading had guessed wrong.

## Standing rule (user correction, 2026-09-18)

- NEVER sleep-poll a long job. Launch detached with a log file, start the next
  entry immediately, and read the log as a side effect of the next command.
  `sleep 45 && tail log` in a loop is the top time-waster reported by the user;
  the machine parallelizes fine (22-bundle unpack + 3k-module delta + LLM stack
  at once). Rule of thumb: a wait is only justified when the NEXT step needs the
  result, and then it must ride inside a command that also does useful work.

- [2026-09-18] Boot-harness portability: a "generic" mock is only generic if every
  URL it hands the extension is DERIVED from where the extension is served
  (location.pathname), never configured. A single hardcoded base (getURL -> "/orig/")
  silently mis-routes every OTHER extension's assets + i18n to the wrong tree, and
  the symptom looks like "the second extension is broken".
- [2026-09-18] Extension entry HTML uses root-absolute refs because in
  chrome-extension://<id>/ the origin root IS the extension root. Any HTTP host that
  serves extensions under a prefix must re-root those (HTML refs AND fetch/XHR), or
  it 404s at the server root.
- [2026-09-18] Some walls are architectural, not gaps: MetaMask's LavaMoat/Snow
  scuttling replaces globalThis.chrome, so a tab-level chrome mock cannot drive it.
  Instrument the page (mock hooks window.onerror -> "uncaught <msg> @file:line:col")
  to localise a boot hang in one run instead of guessing; then classify each stop as
  MOCK GAP vs HOST CEILING before "fixing" it.
- [2026-09-18] Positive controls are cheap and were decisive: re-injecting the exact
  bug a new gate hunts (hardcoded base) proved the gate fails as intended, then
  restore. An unproven gate reads as green forever.

- [2026-09-18] Migration acceptance must be measured, not eyeballed AND like-for-like:
  the first WXT-vs-clone diff looked wrong only because the two panes were fed
  different mocks (different seeded storage). Make the harness able to inject the
  SAME mock into every pane (?mock=clone) before comparing, then diff mechanically
  (identical innerText + element/interactive counts). The residual delta was script
  placement (head vs body) — benign for deferred modules; name it instead of "fixing" it.
- [2026-09-18] A positive control must break the RIGHT layer: appending a root-absolute
  ref to a page proved nothing (the re-root correctly rewrote it, so the gate passed).
  Disable the re-root itself, then watch the gate fail — that is the control.
- [2026-09-18] Hand-scaffold beats an interactive CLI when the CLI is a template picker:
  package.json + config + entrypoints/ is the same artifact, deterministic, reviewable,
  and it states exactly which files exist.

- [2026-09-18] Marker paths are CONTRACTS between a writer and a reader. Moving one
  without the other fails silently: done-detection stays false forever, so the pipeline
  redoes finished work (here: webcrack re-ran over every bundle >=200KB each run, and
  version-watch undercounted done work). After any layout refactor, verify against the
  CORPUS (count on-disk trees whose marker resolves), not against the code.
- [2026-09-18] A/B against the un-mocked page is the decisive instrument for "is the mock
  the cause?": raw died on the extension's own "only in a browser extension" guard, mocked
  passed it and loaded 29 scripts + rendered its splash. Same errors in both = extension's
  environment assumptions, not mock gaps.
- [2026-09-18] Fixture labs must not assume which branch the system picks. The meta-chain
  lab first asserted a webcrack layout for a bundle the chain legitimately sent down the
  esbuild path (a FALSE FAIL). Select targets by evidence on disk (tree exists, no twin),
  then assert the layout the contract names for the branch actually taken.

- [2026-09-18] Portability has TWO halves, and the second was ungated: machine-absolute
  paths (scanned since 09-17) and BAKED-IN TARGET IDENTITY (a script defaulting to one
  extension/version keeps working but silently operates on the wrong project after a move
  — how the dashboard served Sider state for a MetaMask checkout). Gate both.
- [2026-09-18] Test the doc, not just the code: the relocation drill asserts RELOCATE.md
  still names every tree a copy needs AND the things a copy cannot carry (scheduled tasks,
  the WXT build, ledger re-basing). Doc drift is invisible until relocation day — it found
  a wrong project.json location and two missing sections on the first run.
- [2026-09-18] When a new gate goes red, classify before "fixing": every hit here was
  either a comment/prose mention (report as INFO, do not fail) or a pinned lab fixture
  (allow-mark with its reason). An assert that flags comments generates false reds and
  trains people to ignore the gate.
- [2026-09-18] A metric that can DEGRADE TO A PLAUSIBLE CONSTANT is worse than no metric: `tsErrors()` fell back to `1` when its summary-line regex missed, so a 296-error run and a 10,830-vs-7,135 divergence both printed "1 errors" and looked like parity. Count the things, never a summary string, and if a fallback returns a number, make it 0-or-error, not a smaller-sounding truth.
- [2026-09-18] Benchmark numbers on this host are load-dominated: same tool+input medians moved 2.6s -> 4.0s -> 11.0s across three runs while the deobfuscation pipeline drained in the background. Record cold+best+median+worst into an append-only history file and quote RANGES; a single-run ms figure is noise with a decimal point.
- [2026-09-18] "Same error count" is not parity: tsc 5.9 and tsc 7.0.2 both reported 296 on the clone while disagreeing on 2 sites, and by 3,695 diagnostics on generated code. Assert parity on the SET of flagged sites, and pin known divergences in a file so the gate fails only when the set changes.
- [2026-09-18] Autofix "safety" is per-RULE, not per-context: Biome's safe fixes rewrote `(function(){ "use strict"; … })()` into an arrow IIFE in Chrome content scripts and deleted `"use strict"` from classic scripts. Always diff what `--write` actually did before trusting it — in browser-extension code the same fix that is safe in an app silently changes semantics.
- [2026-09-18] Adopting a linter on a codebase that never had one is a WORK ITEM: 190 diagnostics, and `check --write` was a 57-file/3,600-line reformat. Split by group (format vs assist vs rule), apply only the tiny safe subset, and ship the rest as a recorded ratchet (baseline JSON + a gate that fails on growth) so cleanup is visible and regressions are still caught. A "0 problems" linter adoption is usually rules switched off, not code fixed.
- [2026-09-18] Applying import sorting without the formatter leaves a stray blank line at every vacated import site; they are one coupled operation. Measure the coupling before shipping either half.
- [2026-09-18] A mock that answers only promise-style chrome APIs hangs any caller that uses the callback form (`chrome.cookies.get(details, cb)` inside a Promise — the webextension-polyfill shape). Both sides look fine: the mock's promise resolves, the caller's promise just never settles. Symptom: UI stuck on a loading gate, ZERO errors, empty in-flight list. Fix at the host layer (pop the trailing callback in the call wrapper, invoke on settle) so every extension benefits; never patch the one call site.
- [2026-09-18] "Nothing is pending" is a RESULT, not a dead end: an in-flight call register that shows zero unresolved API calls while the UI is still blank means the hang is in the caller (callback/message), not the API. Build the register before you need it — a 200-entry trace cap hid the exact window where the gate stalled; 1000 entries and a per-call stack fixed the visibility.
- [2026-09-18] When a doc says "this pane is a documented ceiling, it renders a shell", re-verify it after any host fix: minutes after the callback fix the same pane rendered its full chat UI. Ceilings written from symptoms become permanent excuses.

## 2026-09-18 — scuttled-extension QA (MetaMask / LavaMoat)
- "X is not a function" in a LavaMoat-scuttled extension is NOT automatically a mock gap. Instrument reads vs invocations separately: MetaMask's early code READ the mock (runtime.id/getManifest/getURL/offscreen) while zero methods were ever INVOKED, and its read of `management.getSelf` never reached the mock at all. A scuttle pass keeps data, drops callables — so the extension's own boot guard passed while every API call failed. Class: "partial visibility looks like a broken provider".
- Diagnostics must survive the failure mode they diagnose. After scuttling, every globalThis read from the QA console throws ("inaccessible under scuttling mode") — exactly when the trace matters. Fix: republish state into the DOM (`document.documentElement.dataset.*`), which is not scuttled, and read it from the parent frame.
- Name metrics for what they measure. `calls: TRACE.length` conflated uncaught-error trace lines with method invocations, so a scuttled run "reported calls" while making none. Split into `mockCalls` vs `traceEntries`; mismatch found within one load.
- A mock's own self-test must not pollute its counters: the read-back probe invoked `getURL` and inflated the invocation count by exactly 1. Gate probe calls behind a flag (`probing`) or every reading is off by the probe's own activity.

- Chrome-API mocks: a trailing-callback heuristic CANNOT be used on event objects. `addListener(fn)` popped `fn` as a completion callback and ran it with `undefined` — the extension's own listeners threw (`Object.entries(undefined)`) and were never registered, while every call still "succeeded". Fix = name guard (`NEVER_CALLBACK`) + shape guard (`isEvent`), and a headless contract test (`node:vm`, no browser) that fails when either is reverted.
- A permissive mock hides half its own contract: with `runtime.lastError` never set, every failure reads as success and the extension's error branch is dead code. Make it a getter with callback-scoped lifetime, and add a `__chromeFailOnce(path)` hook — an error path nobody can trigger is an error path nobody has tested.
- Dead event stubs and no-op `storage.set` are the same bug class as promise-only answers: the extension waits for something real Chrome would deliver. Wire events to real listener sets and let writes emit `changes` — measure "subscribers vs deliveries" in the diagnostic mirror (`subscribed` non-empty + `emits` empty = nothing dispatches; both empty = nobody subscribed).
- Copying a live tree with `cpSync` races the pipeline's own lock/tmp files: `names-map.json.lock.lock` vanished mid-walk and surfaced as `ENOENT`/`runner exit null` in a portability drill. Exclude `*.lock*`/`*.tmp` and retry once on ENOENT; the same failure in self-check read as two unrelated gate failures (`relocateDrill`, `toolchainParity`) once the machine was loaded.

## 2026-09-18 — CAS store: a "fast path" that was not running
- **A doc line that contradicts the tool's own log is a bug, not a slow path.** `cas-manifest.json` was written as `{ version: MANIFEST_VERSION, ...manifest }` and the manifest it spread ALSO carried `version` (the extension's, `"5.32.3"`), so the string overwrote the schema number and `readManifest` returned `null` for every correct file on disk. Nothing threw: every run silently rehashed 59k files and a 9-minute `--verify` read as "the corpus is big". Fix: schema under its own key, plus legacy-read so the fix costs no rewrite. Class to sweep for: **two different meanings under one field name, spread-ordered so the later one wins silently.** The tool printed `0 from manifests, 59075 read` the whole time — read the counter you just printed.
- **Budget per-file passes from the file count, not the mode name.** Measured floor on this box: ~1.8 ms per file (Windows + Defender) for a pure `statSync` pass, so any pass over 60,834 files costs ~1–2 min no matter how "lightweight" the mode is. That number also explained the 9-minute run: 5× the floor = it was reading bytes, not stats.
- **Verify the parity of an optimisation, then report the speed honestly even when it is 1.1×.** The manifest fast path removed 100% of corpus reads from `version-delta` (`28770/28770 from manifests, 0 read`) and its reports were byte-identical to `--rehash` — but wall-clock moved 83s→77s, because the real cost is the AST shape pass. Kept it (free, exact, scales with file count) and recorded "1.1×" instead of the flattering "100% fewer reads". An optimisation sold by its mechanism and not its effect is a future wrong decision.
- **Dedupe safety is the write-once invariant of the tree you link.** Before hardlinking 21,859 files, grep every writer for a target inside `modules/` — not the intent, the code. It held (only `_archive/` scripts touch that path), and the guard is enforced from the other side too (`assertLinkable()` refuses any path outside a `modules/` tree).
- **Gitignored derived stores need a one-line reason in the repo, not in someone's head.** `.cas/objects` is hash-named derived data AND git stores its own full blob per name, so the hardlink savings cannot transfer into the repo; the per-bundle manifests are the precise opposite — small, reviewable, and the index every cheap pass reads — so they stay committed.

## 2026-09-18 — qa-server liveness gate; the pass case was the one lying
- **A watch whose exit code is not the watched thing's exit code.** The gate started the server through `Start-Process -PassThru` and watched the PowerShell process: it returns in ~200 ms, so `child.exitCode != null` broke the poll loop on the first tick and the gate reported FAIL while the server it had just launched was already answering 200. Only a DIRECT child can report a failed launch. Class to sweep for: **launcher exits are not daemon exits** (any `Start-Process`/`nohup`/`&` wrapper).
- **Prove every branch by hand, in both directions, before wiring a check into the nightly run.** Three branches, three manual firings: up → `ok`; killed → `ok (started qa-server pid N)` with the port 200 again; foreign listener holding the port → `FAIL … answers http 404 — not the qa-server`. The third exists because "something is listening" and "our server is listening" need different fixes, and a retry loop against a foreign listener never converges.
- **Gate ordering is part of the design, not an accident of placement.** The new liveness gate runs BEFORE compare-harness because the harness reuses a live server and starts none of its own — healing first is what keeps the later gate meaningful.
- **Self-healing gates beat reminders.** "Remember to launch it detached" was written in the runbook and still failed twice in one day (a child of a dead session; a session start that never relaunched). The gate that probes-and-starts costs ~1.5 s when healthy and turns a discovered-by-hand failure mode into a nightly non-event.

## 2026-09-18 — the gate's own contract needed its own lab
- **A module that is *imported* has obligations a script that is *run* does not.** Self-check calls `(await import('./lib/qa-server-gate.mjs')).qaServerGate()`. When it healed, the launcher child handed its pipes to the server it started, so the importing process never exited — in the nightly run: no summary line, no dashboard marker, a check that hangs silently forever. The standalone runner hid it because it calls `process.exit()` itself. Fix: destroy the launcher's pipes and `unref` it in a `finally`. Class to sweep for: **any spawn inside a module that a long-running check imports**, and in general: does your process still exit if this code runs? Test the call shape the CALLER uses, not the shape you happen to run by hand.
- **`detached: true` on Windows is not free.** A detached PowerShell silently failed to launch the server at all (no process, nothing in either redirect file) — three separate failing sub-experiments pointed at it. It was also unnecessary: `Start-Process` is what detaches. Remove the flag, re-measure.
- **A launcher's exit code is not the daemon's.** `Start-Process -PassThru` returns in ~200 ms, so watching it called a healthy restart a failure. Sweep for this in anything that supervises a wrapped start (nohup, `&`, Start-Process, shell scripts).
- **Give the test its own port rather than killing the user's server.** `QA_PORT` now overrides qa-server's port, so the lab heals/verifies on 8915 while the instance in the Preview tab stays up on 8914. A test that has to destroy the artifact a human is looking at will eventually be skipped.
- **Positive-control the harness, not just the subject.** The lab asserts "the importing process exits"; the control proves the detector WOULD catch a hang by running a snippet that never exits and requiring the timeout to kill it. Otherwise a green result could just mean the detector is inert.

## 2026-09-18 — gate timeouts are false-red generators
- **A timeout is a FAIL whose cause is the machine, not the subject.** `casStore` called a store "broken" because `dedupe-modules --verify` took 296 s while the pipeline drained, against a 64 s idle run and a 300 s cap. The output was `FAIL verifier exit null` — `null` was the kill signal being reported as a mysterious status. Raise the cap (900 s), print elapsed seconds in the gate line, and name the timeout in the failure (`killed by SIGTERM after Ns`).
- **Never "fix" a slow-but-correct check by weakening it.** The cost is realistic (one stat per file, ~1.8 ms × 60,834). Prefer: bigger cap + SLOW prefix past 240 s + a visible duration. A check that red-cards a busy machine is a check people learn to ignore, and then real failures vanish into the noise.
- **Budget per-file passes from the file count.** Idle vs loaded differed 4.6× on identical input. Any gate whose runtime scales with a corpus needs headroom measured under load — the loaded number is the one the nightly run will actually see, because the pipeline runs at night.

## 2026-09-18 — carry-over rounds, and a ledger that killed every module
- **A status field that implies a missing one is a landmine.** `version-delta --align` marked carried modules `transferred` without `rounds`; the driver's legacy default (transferred→1) then scheduled 203 carried modules for LLM review (~1.4M tokens) and crashed them. Fix at the WRITER: stamp the true value, VERIFIED against the output, never inferred by the reader. Any reader-side "if rounds missing, assume N" heuristic is a bug waiting for a new producer.
- **Counting a plan is cheaper than reading a diff.** The whole bug surfaced in one line of `humanify-batch --dry-run` (`LLM rounds pending: 239` vs the expected 45). Always capture the tool's own plan line before letting it spend: baseline-then-change, one command, zero tokens.
- **`existsSync(p) ? JSON.parse(read(p))` is not a guard — it is a crash with a delay.** A killed writer truncating names-map.json to 0 bytes made EVERY module fail AFTER its LLM call had been paid for (37 modules, identical error). Torn-state handling belongs in ONE shared reader that returns a status, plus an atomic (tmp+rename) writer. Same class as the earlier `.lock.lock` race: shared mutable file + non-atomic write = silent correlated failure.
- **Verify a fix on the exact failing input, not a fresh one.** Re-running the module that failed at 14:07 (`record-background-modules/754.js`) proved the ledger fix in one command; a green smoke test elsewhere would have proved nothing.
- **Idempotency is part of correctness for any repair tool.** The first carry stamp re-stamped 113 entries it had already judged — which would erase a failing audit's retry state every align. Guard on a per-output verdict (`carriedBytes`), assert the second run touches nothing.
- **A positive control must be able to fail for the right reason.** The carry lab re-injects the status-only stamp and reads the DRIVER's plan (not the fix's return value); the names-map lab runs the old inline parse against the real 0-byte file. Assert on the surface that failed in production, or the lab is theater.

## 2026-09-19 — surface registry: two defects a "green" gate was hiding
- **A metric keyed on a gitignored build artifact is machine-dependent, so the gate and its tests lie on any other checkout.** `clone.coverage` read `.output/chrome-mv3/*.html`; `.output/` is gitignored, so a fresh checkout reported `0 built, 2 source` and both `--check` and the test failed there while green here. Fix: decide coverage from our own source tree (`entrypoints/<id>/index.html` -> 'entrypoint', `src/<id>.html` -> 'source'), keep the build artifact as an informational flag only. Positive control: hide `.output/` and require identical coverage.
- **Same class in a path field: `join()` produces Windows backslashes inside a committed JSON registry.** The test caught `entrypoints\sidepanel\index.html` where the assertion expected `/`. Normalize to POSIX at the write site — the repo already has this rule (`60-tools/lib/cas.mjs` refuses a backslash manifest key).
- **Metadata nobody asserts drifts.** `generatedFor.captureId` held a hand-typed 20-hex "5.32.9 build id" that grep proved was a *different extension's* webpack chunk hash (it appears in MetaMask's `home.html`). Provenance now comes from the capture's own `meta.json` and the test asserts version/date/fileCount against it, so a future hardcoded constant fails loudly.
- **A test that mutates a committed artifact corrupts it on interruption.** The registry test regenerated the tracked `surfaces.json` (and mid-way wrote another version's data). Added `--out <path>`; tests now generate into a temp file and only ever `--check` the repo copy read-only.
- **`html.length` is not `bytes` when the file has non-ASCII.** Swapped for `Buffer.byteLength` — the same "name the metric for what it measures" rule as the `calls` vs `traceEntries` lesson.

## 2026-09-19 — Tier 0: ghosts, silent filter drops, and console windows
- **Side effects that run before validation create residue nothing owns.** `deobfuscate.mjs` did `mkdirSync(targetDir)` above the `if (!existsSync(capDir)) exit 1` guard, so every typo'd id and every nightly lab probe left an empty `30-deobfuscate/<extId>/<ver>/`. Grep for the *consumer* before trusting a guard: `--status` skips queue-less dirs, so the ghost was invisible exactly where it would have shown. Rule of thumb: in a command with a pre-flight guard, nothing that touches disk may sit above it.
- **A residue gate needs a "in progress" class or it red-cards honest work.** A `-esm`/`-modules` directory without its marker is a stage-1 run in flight (nightly unpack overlapping the 08:00 check); only *nothing at all* is a ghost. Splitting the classes is what makes the FAIL trustworthy.
- **First draft of the target scanner flagged `.cas/objects` and `<ext>/diffs`.** A directory walk over `<a>/<b>` treats every pair as a target. Pin the shape (`^\d+(\.\d+)*$`, skip dot-dirs) before shipping the gate — measured against the real tree, not imagined.
- **`filter(platform === X)` on a registry is a silent un-watch.** The Edge rows were registered, never probed, and never reported — indistinguishable from healthy. Return *entries* and let each entry's platform select a probe; a platform with no probe must print a line that says so. Check the gate's own number moved (self-check `watched` went 1 → 4) or the fix is unproven.
- **Task Scheduler actions are their own popup surface: `windowsHide` does not reach them.** Three tasks ran `node.exe` directly and flashed a console in the interactive session daily. Fix is architectural — a GUI-subsystem launcher (`wscript.exe` + `.vbs` with window style 0) — and the launcher should resolve bare `node`/script names itself so the task XML carries no machine path. Verify by reading back `Get-ScheduledTask … .Actions`, and by triggering one and confirming the real child is running with no wrapper left.
- **A grep-based audit is not an audit.** The first pass reported three *comment* lines as findings and missed a `windowsHide` that sat 12 lines below its spawn. Strip comments/strings, capture the balanced call, and give the scanner a documented escape (`popup-ok:`) rather than a central allowlist that rots.
- **A positive control catches the spec's own bugs, not just the code's.** The popup-scanner control failed twice — first because the marker window was so wide it excused the bare spawn above it, then because it was too narrow to cover the call below it. Both were defects in the *rule*, found before the guard was ever wired into the nightly run.

## 2026-09-19 — registry ownership: a generator that overwrites its own output
- **A tool that writes a per-subject registry must check who owns the file before writing it.** `surface-inventory.mjs` writes `surfaces.json`, which describes ONE extension; a stray `--ext <other>` replaced the whole inventory (surfaces, css/font hashes, provenance) and the only hint was the surface list. Guard reads `generatedFor.extId` from the existing file and refuses (exit 3), naming the two escape hatches (`--out` to keep both, `--force` to replace deliberately). Class to sweep for: any generator whose default output path is shared across subjects.
- **Prove the guard with `--force`, not just with the refusal.** "exit 3" alone is indistinguishable from an unrelated error; the control asserts the same command WITH `--force` exits 0 and the file really changes. That is what separates a working guard from a broken write path.
- **Wrong-owner must be reported as its own problem, not as "stale".** The staleness compare would have been technically true and useless — the fix is a different command, not a re-run. Ordering problems by *the action they imply* is what makes a gate readable.
- **`existsSync(p) ? JSON.parse(readFileSync(p))` was sitting inside the new guard's own neighbourhood.** Made the read tolerate a torn file and report it as a finding instead of throwing out of `--check`. Same class as the names-map ledger; third occurrence in this repo.

## 2026-09-19 — generated entrypoints + the watchable half of a verification
- **A registry→generator→build chain needs its cross-check in the harness, not in the generator.** The generator and the registry cannot disagree (one writes the other), so the real question is whether the BUILD emitted and MOUNTED each surface. `lab/compare-harness` now fetches `/next/qa:<id>.html` for every registry surface and asserts built+served+mock+mount-anchor — the only place that can see the build. Positive control: move one built html aside and the lab FAILs naming it.
- **HTTP-level PASS is not the same as watchable.** "All 20 surfaces mount" was true and asserted, yet the compare page still showed one surface. A picker fed by the SAME registry (new `/surfaces.json` route) made the claim human-checkable and immediately caught that `options` renders the real UI while the other 18 show honest placeholders. Prefer a surface the user can drive over a green checkmark.
- **Redefine a metric when its meaning gets diluted by your own change.** \"Coverage\" meant \"has an entrypoint\"; generating 20 entrypoints made every surface read as written. It now means what BACKS the surface (implemented/shell/source/missing) — a metric that your change makes uniformly true is measuring the wrong thing.

## 2026-09-19 — vendored theme: silent fallbacks, twin trees, and the preview pid trap
- **A vendored stylesheet's `chrome-extension://__MSG_@@extension_id__/…` urls are a SILENT failure.** Every `@font-face` behind that scheme 404s outside a real extension and the page just falls back to the browser default serif — no console error the eye catches, no broken layout, only a wrong typeface. Rewriting to stylesheet-relative paths is the fix, and the count belongs in the manifest so a release that adds another reference is visible. Class to sweep for: any asset reference that is absolute to an origin you are not serving from.
- **The same bug was on the ORIGINAL side and looked like "the original renders in Times New Roman".** When a comparison pane looks wrong, check whether the ASSET loads before blaming the app. Fixing the server's CSS rewrite made the original pane's typeface right too, which is what makes a look-diff meaningful at all.
- **Two copies of the same file exist here: `sider-lite/<page>.html` and `sider-lite-wxt/src/<page>.html`, and the migration depends on them being byte-identical.** Editing only the WXT copy made the compare panes diverge while every test stayed green. Before editing shared source, `diff` the twin; after editing, re-`diff` to prove the invariant survived.
- **`register_preview` with `replace: true` KILLS the registered pid.** Replacing after a manual restart killed the very server being registered when the pid happened to be the same live process, and the failure reads as "server stopped responding". Safe order: stop the old server yourself, start the new one, confirm the URL answers, then register once with the NEW pid.
- **A screenshot that never composites is not a reason to skip verification.** `preview_screenshot` failed every attempt in this environment; `preview_evaluate` reading computed styles, loaded stylesheets and `document.fonts.check()` proved more than the picture would have.

## 2026-09-19 — auditing checks for machine-local state
- **A check that FAILs for ABSENT input is worse than no check.** On the box that has run for weeks the state is always there; on a fresh checkout none of it is. Eleven checks here read "FAIL for absence" before this audit — a red card nobody can act on, and the mechanism by which people learn to ignore red cards. The rule to apply everywhere: `present + wrong = FAIL`, `absent = skip` with the command that produces the input.
- **"skip" and "ok" are not the same, and the difference is testable.** Asserting the state-dependent checks read `skip` (not `ok`) is what proves they skipped *because* the input was absent, rather than passing vacuously. Without that assertion a fix that silently passes everything would look identical to a fix that classifies correctly.
- **The control is a check that must still fail.** Injecting a crash trap and a stale heartbeat into the otherwise-clean copy is what separates "correctly skips absence" from "blanket suppression". Run A alone (clean ⇒ no FAILs) is satisfied by a check that never fails.
- **Baseline before change paid for itself twice.** The pre-change run showed gateway/daemon/backend timing out at 2500 ms while the store verify was running and all three services were in fact alive — evidence that the service probes needed a retry, which reading the code would not have revealed.
- **Reproduce absence in a COPY, never by moving live files.** Renaming a log or pid file that a live process holds open fails on Windows, and moving a store out from under a draining pipeline is destructive. A filtered copy (`cpSync` + a predicate) is safe, read-only against the machine, and small enough to run twice.
- **An absence fix can expose a dependency that was hidden by presence.** The portability-dry lab only ever ran on the installed box; in a state-free copy it crashed on a missing npm parser and the check reported it as a pipeline contract failure. Fixing the verdict (skip) required fixing the lab (preflight its deps) — the shell that reported it was not the thing that was broken.
- ESM resolves the entire module graph before a script's first statement, so a "preflight SKIP" written INSIDE a suite cannot prevent an uninstalled-checkout crash: the guard belongs in the runner, matching the `Cannot find package 'x'` banner and only when the package is actually absent. (Fixed the class for 24 suites in one place instead of 24.)
- A "present + broken = FAIL, absent = SKIP" rule needs BOTH halves of the evidence or it becomes a silencer: the name must be bare (a broken relative import stays FAIL) AND the package missing from disk (installed-but-unimportable stays FAIL). Pin both controls in the helper, not in prose.
- Two harnesses marked "serial on purpose (suites bind ports)" really do collide: local + copy `run-all-labs` at once produced `ladder FAIL stub exited 1` — my instrumentation, not the code. Before reading a red card from a suite that spawns servers, check for a second instance of the harness.
- Reuse the copy a lab already builds (`lab/clean-state --keep`) instead of writing a second harness: the state-free tree was the whole fixture for auditing 24 unrelated suites.
- A red card whose NUMBER drifts between runs (35, 37, 41 distinct inodes for the same 42 files) is a measurement bug, not a code bug: suspect the instrument before the store. Root cause here was comparing NTFS file ids as doubles — ids exceed 2^53, so `statSync().ino` rounds two distinct files together. Compare inodes as BigInt; keep a `Number(b) === Number(b+1n)` control in the lab.
- When absence (uninstalled checkout) is fixed by matching a child process's crash banner, remember the banner often dies WITH the child: a suite that spawns pipeline scripts shows `FAIL 15/92 checks passed` and nothing else. The suite itself must preflight its own dependencies; the runner cannot infer it.
- "Exit 0 with a SKIP line" must be mapped to SKIP by every runner, or the honest skip silently becomes a pass. Check both directions when adding a skip path: self-check mapped it, run-all-labs did not until this audit.

## 2026-09-19 — RUNBOOK claim checker (checksummed doc verification)
- A doc is the artifact that rots WITHOUT failing: extract its claims (headings/fenced commands/routes), verify them against the repo, and pin each to the sha256 of its own text. Green means nothing; "an old green cannot survive new words" is the property that matters.
- Identity of a check is its TEXT, never its line number. First version compared lines too, so inserting one paragraph reported 32 phantom failures — a checker that fails on unrelated edits gets disabled within a week.
- A gate that can FAIL on a thing the operator is allowed to change must also offer the recording path, or it deadlocks: the heading-set check blocked `--apply`, so adding a legitimate section could never be recorded. Split the reds — repo conflict = fix the doc (blocks apply); "edited since blessed" = review, then apply.
- Prove a doc-checker on a COPY of the doc plus a negative control, not only by reading it green: broken script name, invented route, inserted paragraph, appended heading — four controls, two must fail and two must not.
- Wire the checker's own selftest FIRST inside its gate: a checker that silently stops detecting anything is the one failure no claim verdict can reveal.

## 2026-09-19 — pane fidelity seeding + look-diff
- A comparison harness is only as good as its reference: seed the reference's real user state (dismissed promos, history, a model list that satisfies the bundle's own indexing) or every mock gap reads as a defect in the thing being compared. Instrument first: the mock's chrome-call trace named the exact keys/slots that were missing in one read.
- A message the panel WAITS for must be answered the way the real background answers it (a separate onMessage broadcast), not with sendMessage's return value — resolving the promise leaves the slot mounted-but-unresolved, the same class of hang as a promise-only callback mock.
- Seed shaping is a requirement, not decoration: `filter(level === 2 && enable)[1].name` needs TWO matching rows. Read each seeded list's consumer before writing it, and pin the requirement with a control that throws on a short list.
- Give the seed a knob (`?profile=fresh`) so the seeding can be DEMONSTRATED as a one-line diff instead of asserted in prose.
- "They look different" is not a finding: compare named regions plus text lines and element counts, output only the differences, and make the diff runnable from the page (`?diff=1`, `await __paneDiff()`) so a human can reproduce it without the agent.
- Durable measurement records do not belong in a pruned/ignored state dir (_diffs/): put the catalogue next to the lab that produces it.

## 2026-09-19 — second doc, same guarantee (claims gates)
- When a second artifact needs the same check as the first, move the check into a lib and call it per artifact; copying the block is how one copy silently loses the controls.
- Derive names from the artifact (doc --doc -> <doc>-claims.lock.json) instead of adding a flag: it removes the class of bug where one doc inherits another's record.
- A gate's own control must pin BOTH directions: no record = skip (never ok), a recorded claim the repo contradicts = FAIL, and a healthy artifact = ok. "Always fails" is as useless as "always passes", and only the third case proves you have neither.
- Keep the control hermetic and tiny (fixture doc written to a temp dir, one command, no network): a control that costs a minute gets dropped from the nightly.
- Write the control's fixture from a claim that is REALLY valid — a fixture built on `--selftest` of a file that has no `--selftest` produced a red card the checker was right about.
- A timeout is not a verdict. Sweeping every gate's budget against a MEASURED loaded duration found the real bug was semantic, not numeric: a starved box answers nothing at all (dashboard: no HTTP answer in 20s while the port connected in 15ms), so an HTTP probe false-reds whatever the budget. Report a budget overrun as `unverified` (warn), and escalate to FAIL only when the same gate overran on the previous run — one busy night is weather, two is a hang.
- Measure "loaded" with a deliberate load generator, not by hoping. `--loaded` with cores-1 CPU burners + one disk hammer gave idle→loaded multipliers of 1.1x-2.4x for spawn gates but INFINITY for HTTP probes; guessing would have raised numbers and fixed nothing.
- Personal lesson, cost real time: a `Date.now()` captured inside a `try` but used in the `catch` throws `ReferenceError` on a path that only a loaded machine reaches — idle runs all pass. Anything that only runs when the box is busy is untestable by accident; give it a deterministic knob (env-forced 1ms budgets) and a scratch output path so the control cannot pollute the real log.
- Deterministic control knobs beat waiting for a busy night: SELF_CHECK_PROBE_MS / SELF_CHECK_GATE_MS = 1 exercise every overrun branch in seconds, and running it twice proves the escalation. Exclude any gate whose own control cases must see a real FAIL from the blunt sweep.
- [2026-09-19] A heal probe must re-verify through the real surface, never trust the launcher's exit 0: the nightly's guardian heal "succeeded" while the wrapper it started had died in milliseconds (adoptive wrapper owns no child; unref'd timer is not a handle). A process that daemonizes needs spawnDetached, not runLauncher — waiting on a never-exiting service can never report a repair.

## 2026-09-20 — the stall axis, duplicate guardians, and fixture replay

- A PROGRESS METRIC THAT INCLUDES A RETRY/CHURN POOL IS NOT A PROGRESS METRIC. `overnight-run.mjs` tested `workLeft = pending + failed + needsRounds`, so a pass that claimed 21 modules and failed them read as "no progress" (FATAL) while a module merely moving failed->poisoned reset the stall counter — the same reshuffle decided both ways. Fix: measure the axis only work can move (pending + needsRounds), and say what the driver reported in the FATAL. Class: any "is it advancing?" signal built by summing buckets a retry loop writes to.
- WHEN A TRAP'S OWN FIXTURE CLAIMS "THE OLD RULE WAS WRONG", DRIVE **BOTH** RULES OVER THE RECORDED PASSES. The stall lab replays four real windows; the pre-fix rule must reproduce every logged trap (matching the logged modules-left number and second proves the transcription), and the fix must fire only where the queue was genuinely frozen. A fixture whose old rule does NOT reproduce the historical failure proves nothing.
- RECORDED TOTALS ARE THE CHEAPEST WAY TO IDENTIFY WHICH DEFINITION A PROCESS WAS RUNNING. Every logged modules-left number equalled pending + failed exactly, which is how we learned `needsRounds` contributed 0 and that the retry pool was the entire disagreement — no code archaeology needed.
- A CRASH TRAP THAT KEEPS RE-ARMING AFTER YOU CLEAR IT HAS A LIVE PRODUCER — FIND IT BEFORE CLEARING. `dash-server.crash.log` refilled because two `dash-forever.mjs` guardians were running for one port (the pid file can only name one, so the nightly healed in a second it could not see) and one missed HTTP probe was treated as the board's death. Clearing alone would have hidden it; `ps`-level evidence (two wrappers, same second, ADOPTING and taking-over interleaved) named it in minutes.
- A STABILITY/BACKOFF THRESHOLD THAT EQUALS THE CHILD'S OWN GIVE-UP WINDOW IS A BACKOFF THAT CAN NEVER THROTTLE. `STABLE_MS` 5 min vs listen-retry's 5 min gave 306s children that always looked "stable", resetting the delay to 2s forever. When a supervisor decides "was that crash stable?", that constant must sit strictly outside the child's own timeout windows.
- THE SAME WRONG PROGRESS AXIS SURVIVES IN A SECOND READOUT, so fix the CLASS, not the site. Hours after the supervisor's stall trap was moved onto the work axis, the nightly's own stall WARN was still judging progress by `done`/`transferred` — counters that CANNOT move on a completed queue — so a finished 3038-module queue emitted `queue stalled: done 51 unchanged for 0.3h` on every run, and re-reviewing a canonical (rounds 2->3, stays `done`, not a transfer) would have triggered it through real work. Grep the old counter's name across every reader (warn, ETA, health card, analytics script) before declaring the fix done; the reporter is where a wrong metric hurts most, because nobody re-derives it.
- A DRAINED QUEUE AND A STUCK ONE ARE INDISTINGUISHABLE TO A COUNTER THAT ONLY RISES. The discriminator is whether UNSATISFIED work remains (`pending + needsRounds > 0`), and the completion case belongs in the test as a POSITIVE CONTROL — the drained 5.32.9 counters sit in `stallWarnFor`'s selftest next to the stranded-54 shape that must still warn.
- A GUARD ADDED TO ONE GENERATOR IS A CLASS, NOT A SITE — sweep every writer of a shared output before calling it fixed. The registry guard (`--ext <other>` silently replacing one extension's `surfaces.json` with another's) had two unguarded siblings in the same repo, both writing a path shared between owners: the vendored theme (whose manifest ALREADY recorded `generatedFor`, so the guard was one read away) and the generated `entrypoints/` tree (which recorded no owner at all, so there was nothing to compare — record the owner FIRST, then guard). Sorting every writer by "is this path shared, and does the artifact name its owner?" turns a hunt into a table: owner-scoped paths (per ext/version/clone) and deliberately multi-owner ledgers (entries namespaced `extId:hash`) need no guard, and saying so is part of the deliverable.
- A GUARD'S OWN CONTROL MUST PROVE `--force` REACHES THE WRITE, not just that the refusal exits 3 — "exit 3" is otherwise indistinguishable from any unrelated crash, and an over-eager guard that refuses forever looks identical to a working one. With refuse/--check/--force all pinned, an over-eager guard is caught the moment an honest run is refused (the "no recorded owner = stand down" case is what keeps that honest).
- A SHARED OUTPUT WITH NO RECORDED OWNER CANNOT BE GUARDED — recording the owner is the first half of the fix, not bookkeeping. The generated entrypoints tree had no owner anywhere in its 40 files, so the guard had nothing to compare; stamping `for <extId>@<version>` into the banner made the check possible AND made the tree self-describing for the next reader.
- A SCREENSHOT IS EVIDENCE ONLY WITH ITS RECIPE. "One stylesheet retints everything, screenshot both side by side" needs the URL, viewport, colour scheme and browser written down next to the PNG, or the picture is an anecdote nobody can re-derive. And the scheme is part of the proof: in dark mode both themes are near-black, so the retint is a few percent of tint — capture in LIGHT, where the accent sits on white.
- AVERAGING IS THE WRONG INSTRUMENT FOR A SMALL SATURATED ACCENT. Three measures failed before one worked: the pane mean hides it (a few percent of a mostly-neutral surface), the mean of the most chromatic pixels washes the hue out (frost's pane read #7e8888, chroma 10, while the teal accent was on screen — a mean of mixed hues is not a hue), and subpixel antialiasing makes every glyph edge a pure-R/G/B fringe, i.e. the most chromatic thing in a text-heavy pane. What works is a RATIO over hue-bucketed chromatic pixels (violet 1625 vs teal 73 -> teal 518 vs violet 68) plus a large uniform area for the surface tint.
- A PICTURE CHECK NEEDS ITS OWN CONTROL, AND THE CHEAPEST ONE IS A REAL CHOICE IN THE UI. `?theme=none` renders the fourth pane with no theme — two identical panes — and the checker must then FAIL (it did: identical bucket counts, unmoved tint, 3 FAIL, exit 1). Without that, "the retint is visible" is a claim about a PNG that cannot fail. Make "none" a real option in the picker rather than a special case, so the control runs through the same code path as the proof.
- A RATCHET MUST NAME ITS TREE, BECAUSE CODE MOVES BETWEEN TREES. The clone had a lint baseline and a nightly ratchet; the migrated tree it is being ported INTO had neither, so every module that crossed over left the covered tree and its lint state went unwatched — the blind spot appears exactly at the migration front, not at the start. Fix the class: one comparison rule in a shared module, one baseline per tree beside its own config, one gate per tree in the nightly, and per-tree control runs that prove the gates are INDEPENDENT (injecting `eval()` into a port-only file failed `portLint` while `cloneLint` stayed green). A baseline file with no gate watching it, or a gate whose tree is unnamed in its failure message, is half a ratchet.
- RANK EVERY SUGGESTION AGAINST THE USER'S STATED GOAL BEFORE WORKING ON IT, AND SAY WHICH ONES THE GOAL REJECTS. This user's goal was fixed from the first prompt: make the clone LOOK like the original and behave the same, on the LATEST captured version (so its new features come along), and only then implant. Every polish idea (a retinted theme, a toolchain pilot, a CAS store, extra labs) got queued and then executed on its own merits because none was ever compared back to that sentence — the user watched twenty green side-projects accumulate while the one thing they asked for stayed unstated in the queue. A suggested idea is not an accepted one: put it in the queue tagged with the goal it serves, mark it `off-goal/postponed` if it serves none, and open each session by re-reading the goal, not the queue.
- A CHECK THAT PINS LINE LAYOUT TESTS THE FORMATTER, NOT THE CODE. The deferred format pass turned two green labs red without touching behaviour: `pane-diff` read the seeded model list a LINE at a time (`split('\n')` + `^\s+\{ name: ...`) and `compare-harness` required `"function" ? args.pop()` on one line. Both silently found zero matches after a reflow, and the model-row case reported the WRONG cause ("the seed has no level-2 models"). Fix by pinning the shape: match braces to find the row's real extent, allow `[\s\S]{0,60}?` between tokens. When any formatter lands, re-run every check that greps source text — they are the ones that can break with zero code change.
- A CHILD CONFIG'S FILE SCOPE DOES NOT NARROW AN EXTENDED PARENT'S `files.includes`. Trying to share Biome rules via `extends` while giving the port its own scope silently WIDENED the check to 201 files (including `.output/`: 1,507 errors, 24,320 warnings). Extended globs are merged and win. If a shared-rules/own-scope split is needed, write a standalone config and have a check assert the two files are equal except for the scope key — an invariant a machine can see beats an inheritance rule nobody can predict.
- IF THE PROOF HAS NOTHING TO COLOUR, THE ELEMENT THAT CARRIES THE TOKEN IS PART OF THE FIX. The stub surfaces' status line became an accent chip, because a thin shell with no accent-bearing element retints to a few percent of background tint — invisible at a glance. Say plainly which surfaces the proof still does NOT cover (here: the clone's own components, which do not consume the tokens yet) instead of letting one green pane stand for all twenty.
- A NON-GLOBAL REGEX IN A `while ((m = RE.exec(s)))` LOOP SPINS FOREVER. A `/g` regex advances `lastIndex` per exec; without it, exec always returns the first match and the loop never ends — a class-checker hung twice on this before it ever scanned a live file. Rule for any regex-driven scanner: define exec-loop patterns with `/g` at the declaration site, and assert at least one selftest case exercises the loop's exit (a scanner that hangs in its own selftest is caught there, not in the nightly). Sibling sweep: every `while (RE.exec` in the repo must have a `/g` flag.
- A CLASS-CHECK EARNS ITS KEEP ON ITS FIRST LIVE RUN. The verdict-hygiene scan was written to catch future machine-state verdicts — and immediately found two real hits in self-check.mjs itself (exit-0 SKIP lines rendered as `ok (...)`), the same file that would host its gate. Build the class check, then let it scan its own host file FIRST: the repo you are scanning includes the tool you scan with.
- ALWAYS LAUNCH BACKGROUND/INTERNAL POWERSHELL HIDDEN, AND RE-AUDIT SCHEDULED TASKS PERIODICALLY. The user works interactively on this machine; any console-window spawn (plain `powershell -Command`, unshimmed schtasks action, `Start-Process` without `-WindowStyle Hidden`) pops a window and steals focus mid-work. Standing rule: every agent-initiated background/internal op goes through the hidden recipe (wscript + run-hidden.vbs for tasks, `-WindowStyle Hidden` for direct launches), and the periodic check for "any scheduled task not doing that" already exists as 60-tools' taskLaunchers + popupSpawns gates — green there means no popup class is regrowing. (2026-09-22, user preference rule.)
- [2026-09-24] Before chasing measurement nondeterminism, measure the ENVIRONMENT's cadence: a capture pair that had been byte-identical for four runs flipped the moment an env restart introduced a per-minute watchdog sweep spawn cadence — the inputs were provably unchanged (`find -newermt` empty) and the variance localized to surfaces with async mock flows. And a gate whose retry keys on exit≠0 cannot see an exit-0 record that flipped its numbers — pair identity (or a numeric delta vs the previous record) is the retry condition for capture-class checks.

- [2026-09-26] A FIXTURE SHRINK SILENTLY PRODUCES A DIFFERENT TEST UNLESS ITS DEFINING PROPERTY IS ASSERTED. module-count-drift's selftest spent 81-133s writing ~210,000 real module files to test a PURE function (`compareCounts` takes two count Maps — its own header says so). Moving the comparison controls onto Maps and cutting the disk fixtures to 1/10th scale gave 3.6-3.9s at 41/41. The trap: `WIDE(1688)` was "a mode change" only because every bundle moved, and at 1/10th scale that stopped being true by accident — so control 4 now ASSERTS that all 22 ratios sit outside the tolerance band, and the walk fixture asserts it is still 7-dead-of-22 with the median intact. Proof it kept its teeth: 5 mutations of a COPY (median discriminator removed, countModules stops excluding metadata, share guard removed, on-disk fixture shrunk to 11 dead, mode fixture with one bundle in band) each turned the suite red through the control that owns that bug — and the first harness run SKIPped a mutation whose anchor text had gone stale, reporting "stale, not passing" instead of counting it.

- [2026-09-27] A CHECK WHOSE SAMPLES ARE WRITTEN BY ITS OWN TEST SUITE NEVER ARMS, AND EVERY CONTROL STAYS GREEN. The content gate's rate-degradation check had been reporting "only 0 comparable run(s) so far" on every live run: four `runGate` calls inside its own selftest inherited the default `rateFile`, so 132-module and 1655-module FIXTURE samples were evicting the 13,628-module live baseline from a twelve-slot window — and `baselineFor` matches module counts EXACTLY, so the live runs were never comparable. Every behavioural control passed, because every fixture run behaved exactly as specified; the defect was about WHERE the bytes landed, which no behaviour assertion can see. First fix was to digest both production files at the top of the suite and again at the end — and that fix is its own lesson: it went red the moment an unrelated live run touched either file during the suite, because a digest cannot tell WHO wrote the file. A control that cries wolf is a control people learn to skip. The durable form is a guard at the boundary (`MCG_FIXTURE_RUN=1` makes `runGate` REFUSE a run that has not named its own state files) plus a control that asserts the refusal, not a before/after observation. Generalise: any state a test writes must be structurally unreachable from production, and prove it by proving the refusal.

- [2026-09-27] A READOUT MUST BE PINNED ON THE SHAPE THE CALLER BUILDS. `formatRateLine` read `v.run.ms` to print modules/s and had a passing control for it — but the control rendered what `judgeRate` RETURNS (which carries `run`), while the gate built its own summary object without it. Every live run therefore printed "rate ok — no rate" directly above a real measurement, and the file stayed green. Same shape as the dropped `modules` field: a field no control supplies is a field no control checks, and the symptom is a plausible line rather than an error. Two controls fixed it — one for the flat `{modules, ms}` shape the gate builds, one through the real printer in the gate's own suite — and the fix was proven by reverting the two fields and watching 109 become 108 with the literal text `rate DEGRADED — no rate`.

- [2026-09-27] "NO MUTATION WENT RED" HAS EXACTLY TWO EXPLANATIONS: THE CONTROL IS VACUOUS, OR THE MUTATION NEVER EXECUTED. Both happened in one harness run. M1 folded the rate verdict into `exitCode: drifted.length ? 1 : 0` and the suite stayed green — because a CLEAN tree returns EARLY, three lines above, and never reached the mutated line. M5 gated `if (saved.ok) live.rate = rate` on the verdict, which only touches the REPORTED copy; the state file was written either way, so the invariant ("the window is written even on a skip") was never actually broken. Classify before concluding: read the mutant's own output, and when the suite is green ask which of the two it is. Also: assert the unmutated copy is green BEFORE mutating (the first version of this harness never did, so "the control turned red" could have meant "the copy was already broken"), match control labels with `includes` not `startsWith` (a claim in the middle of a sentence is not a vacuous control), and let a mutation assert `mustNotPass` when the expected failure is a LOUD crash rather than a FAIL line.

- [2026-09-27] TWO ROOTS SHARING ONE PRUNED CACHE FILE TAKE TURNS EVICTING EACH OTHER, SO EVERY RUN READS COLD. The hash store prunes to the files the run actually saw (correct for a nightly: it bounds the store to the live tree). Point two different trees at one store and each run deletes the other's entries on save, so the cache hit rate is 0 forever and regime is permanently `cold` — which matters here because a baseline only matches within one regime, so the rate check skips every run and the cost line reports every module as freshly hashed. The live gate has exactly one root, which is why it never showed up in production. In a suite, one cache file per root, and one rate file for all fixture roots.

- [2026-09-27] A HASH SIDECAR KEYED BY PATH + MTIME + SIZE IS A CORRECTNESS-SENSITIVE OPTIMISATION, NOT JUST A SPEEDUP. Measured on the 13,628-module corpus: `stat` 336ms warm against read+normalise+sha256 824ms warm; gate end-to-end 4.50s cold → 0.68-1.05s warm (0 hashed, 13,628 served from cache, 2.67MB store). `mtime + size` is a HEURISTIC, so it ships with two defences that a naive cache does not: a `NORMALISER_ID` fingerprint (edit the normaliser and the whole store is discarded, not merged — otherwise a weakened normaliser silently keeps answering the old question), and a canary that re-hashes every 64th hit and marks the store suspect on mismatch (212 re-hashed per run here). A suspect store is never trusted for gating and never written back with entries — the first version refused to write it at all, which meant the next run re-trusted the same lying store.

- [2026-09-27] A `const` THE SELFTEST TOUCHES MUST BE DECLARED ABOVE THE `--selftest` DISPATCH — the TDZ trap, hit TWICE in one session. The `--selftest` branch runs the suite from the module body, so a `const` declared further down the file is still in its temporal dead zone when the suite asks for it: `ReferenceError: Cannot access 'X' before initialization`. First cost me `FIXTURE_RUN_ENV` in lib/rate-degradation.mjs, then `VERDICT_TAGS` in update-watch-check.mjs — and both times the failure was a CRASH, not a FAIL line, so a suite that "passes 111/111" one minute and dies the next is a suite whose green was never in doubt but whose structure is. The durable fix is to move the dispatch block to the very bottom of the file, after every declaration; the cheap fix is the hoist, and the hoist is not obvious enough to be worth rediscovering. Function DECLARATIONS hoist and are safe — only `const`/`let`/`class` bite.

- [2026-09-27] A STATIC FINDER CAN BE RIGHT AND STILL NAME THE WRONG LINE — probe the crash, do not patch the finding. The main-only audit flagged `ratio.toFixed()` on two lines of lib/rate-degradation.mjs as an unguarded nullable format. That line cannot throw (`NaN.toFixed()` is the string `"NaN"`); the real crash was one line earlier, on `base.medianMs.toFixed(0)`, reachable only because `minSamples` is a CALLER-TUNABLE option, so `{minSamples: 0}` stepped past the early return and divided by a null baseline: `TypeError: Cannot read properties of null (reading 'toFixed')` — a crash with no verdict, which is the exact incident the integration guide's REGIME triage row exists for, reproduced inside the checker written to prevent that class. Two lessons: a tunability knob must not be able to switch an invariant off (the fix is a null-baseline contract, not a toFixed guard), and when a finder points at line N, run the thing and find the line that actually throws. Also worth knowing: the audit's nullable pass flagged a local `const ratio` only because the function RETURNS a `ratio` property that is null on skip paths — one identifier meaning two things in one function, so renaming the local (`ratioNow`) both silenced the false positive and removed the real shadowing hazard.

- [2026-09-27] A CONTROL CAN CATCH ITS OWN FIXTURE, AND THAT IS THE POINT. Three times in one afternoon, a control went red on a bug in the code I had just written rather than in the code it was written for: `--limit=` (an unset shell variable expands to a blank flag, `Number('')` is 0, and `slice(-0)` is `slice(0)`, so the flag meaning "zero" printed the WHOLE ledger); a token column asserted with a thousands separator the code did not add; and a fixture built by calling the line RENDERER instead of constructing the row object, so the promotion line printed `undefined (registry undefined)`. Each was a real hole — the first two in the fix itself, the third in the control. The habit that catches all three: write the control against the SHAPE production passes, and read a red control's own detail string before assuming the production code is at fault. Corollary, now a standing rule in the files I own: a rendering function never emits the literal `undefined` — an unmapped tag, a missing version pair, or an absent number renders as a named condition instead.

- [2026-09-27] `cmd | tail -2; echo "exit=$?"` REPORTS TAIL'S STATUS, NOT THE COMMAND'S. A sweep script built this way printed `exit=0` for a selftest that had actually crashed before printing its summary, which is how two suites were recorded as green in a log I then cited as evidence. Use `${PIPESTATUS[0]}` (and do not run an `async` selftest through a `node -e` that forgets to `await` — `Promise.ok` is `undefined`, so `r.ok ? 0 : 1` takes the failure branch for the wrong reason, or reads as green if the ternary is inverted). A sweep is a gate like any other: if it cannot fail, its green is decoration. This box has now produced three separate verification-method defects in a row, all of which pointed at the code instead of the method.

- [2026-09-27] AN `unref()`'d TIMER PLUS A TOP-LEVEL AWAIT IS A SUITE THAT SILENTLY DOES NOTHING AND EXITS 0. Node prints "Detected unsettled top-level await" and ends the process with a success code, so every control in the file is skipped and the gate is green. It bit `watchdog.mjs` the moment its port-probe controls started awaiting a promise whose only pending work was the probe's own deliberately-unref'd timeout. The `unref()` is CORRECT (a port probe must never hold a process open) and the control's await is correct; the two are individually right and jointly a no-op. The fix is a ref'd keeper timer around the await, and the tell is the warning line in the output — so a selftest log containing that phrase means "0 controls ran", not "0 controls failed". Related, from the same edit: adding `export` to a function that lives INSIDE another function (`portBound` was nested in `main()`) is a SyntaxError at import, and the message names no file, because the failure surfaces while the importing module graph is being compiled.

- [2026-09-27] A BOOLEAN THAT MERGES TWO OPPOSITES IS A BUG WAITING FOR ITS NEXT CALLER. `watchdog.mjs`'s `portBound()` returned `false` for ECONNREFUSED (definitive: nothing is listening) and for ETIMEDOUT (inconclusive: something IS listening and not accepting) alike. The launcher happened to consult netstat first, which bounded the damage to 464 wasted spawns instead of a night of them — but the workaround lived at the CALL SITE, so the next caller would have inherited the original defect with no comment to warn it. Fixed by carrying the reason in the return value (`{bound, how}`) rather than by fixing the one caller, and pinned with four controls over a fake socket so all four arms are reachable on a box where they are not. The general move: when a function's boolean is load-bearing for a safety decision, ask what the `false` actually MEANS, and if the honest answer is "two different things", return the reason instead.

## A redirect you cannot read back is half a redirect, and the lying half is the one tests trust (2026-09-27)
`lib/gate-telemetry.mjs` honoured `GATE_TELEMETRY_FILE` on the WRITE path only; `readTelemetry()`'s
default parameter went straight to the production ledger. So a test that isolated its writes into a
temp jsonl then read *production* rows. Nothing threw. My replica's "empty ledger is not a red card"
case was silently checking whatever the nightly run had last appended — it failed on a day the
pipeline had run and would have passed on a day it hadn't. The assertion's outcome depended on the
machine's mood, which is the signature of a check that is not a check.

Rule: **an isolation knob must cover every read and every write, or the tests that use it are
measuring production.** When a default parameter is the thing that breaks the isolation, write the
regression control against the *default* (`readTelemetry()` with no argument), not against an
explicit path — an explicit path was never the bug.

Second half of the same lesson, from the sibling fixture: a **fixture whose NAME decides the
verdict** is not testing the thing it claims. My "gate is wired and reporting" case wrote a stub file
called `already-wired.mjs` next to a ledger row for `module-content-gate`; the coverage half matches
wired sources to rows by stripping `.mjs`, so the case was in fact exercising the *never-reported*
path and passing for the wrong reason. Name the fixture after the identity the check compares on, or
the case silently stops being the case you wrote.

Third, cheap and generalisable: **rounding is not disagreement.** The real cost line prints
`151,976 modules/s` and the row holds `151975.68`. Compare `Math.round(row)` on both sides or the
check false-reds every single night and gets disabled by the second operator who sees it.

## A gate that names a callee is a gate that will be wrong about the next callee (2026-09-27)
`lab/import-guard/detector.mjs` decided "is this `--selftest` read actually launching a
child?" from a NAME LIST — `spawnSync|spawn|execFileSync|execFile|execSync|fork|runNode`.
So `lib/self-host.mjs:282`, which passes the flag to a child through its own
`selfHostSubprocess({ …, args: ['--selftest'] })` helper, was reported as a leak
indefinitely. Adding the wrapper name would have made the list wrong again the next
time somebody wrote another wrapper.

The replacement asks a question the callee's identity cannot answer: **what is the
flag's syntactic ROLE?** Passing it puts it as an element of a list
(`args: ['--selftest']`); testing it puts it as a call argument
(`argv.includes('--selftest')`). Which bracket is open at the token tells them
apart, and that holds for a wrapper nobody has written yet. No parser needed.

**Then the gate caught my own rule being too permissive, which is the part worth
remembering.** I also exempted any flag read inside a function body, reasoning that a
function body does not execute at import. True — and useless, because a top-level
`main()` call DOES execute at import, so `function main(){ if (argv.includes(...)) … }
main();` leaks exactly as badly. The gate immediately reported two correctly-guarded
files (`headroom-compress`, `headroom-probe`) as "stale baseline entry: is guarded
now", which is what over-reach looks like from the outside.

The fix that survived: **depth is necessary but not sufficient; the exemption also
requires positive evidence that the file gates its entry point.** Both files do —
they dispatch `main()` from a `pathToFileURL(process.argv[1])` guard at the *bottom*,
which is why the evidence has to be a whole-file read and not a lookback window. Absent
that evidence the finding stands.

Two general rules:
  1. **A structural exemption needs a pinned case it must still REJECT.** A rule that
     can only return "clean" is not a rule; it is a gate that has stopped working and
     is now reporting green. Every new exemption gets a negative control, and the
     negative control is the one that matters.
  2. **A per-line window cannot answer a whole-file question.** My first depth rule
     read a 3-line window (correct for guards, which sit adjacent) and so always
     concluded "top level" for a function whose brace was 80 lines up — the rule
     silently never fired on the exact lines it was written for, and the suite was
     green. Computing the state once per file and threading it in is not an
     optimisation; it is the difference between the rule existing and not existing.

## "That file is clean" and "the gate never looked at that file" print the same thing (2026-09-27)
A mesh reported 3 findings in `lib/module-count-drift.mjs` at lines 252/271/293, all
`treeRatio.toFixed(...)`. The live audit reported **zero** findings in that file. Before
concluding the mesh was wrong, I planted the exact shape it described — a bare
`.toFixed` on a possibly-null ratio — into the real file and re-ran the audit:

    nullable-numeric-format :139 — treeRatio can be null here and .toFixed() is unguarded

The gate saw it immediately. So its silence was a TRUE clean, not a blind spot, and the
file was restored byte-for-byte. **Silence from a source-scanning gate is only evidence
after you have seen that gate catch the thing.** One plant-and-rerun (two minutes)
converts "it says clean" into "it can see this class, and this file is clean".

The mesh's three sites were already `ratioDetail(v, digits)` — the fix I had made for
precisely this class — and the quoted line numbers pointed at unrelated lines. A quoted
finding with a line number is still a claim about a *specific run*.

## The roster a gate prints in prose is only as fresh as the run that produced it
The same mesh listed 9 files for the audit's "argv[1].endsWith(...) guard" note. The live
note says **7 branches in 9 files** but names none of them. Reading the roster out of the
audit's own `--json` (`_work/argv-only-roster.mjs`) showed only **2 of the 9** were on it,
while 5 live files were missing from the quote — including `update-watch-check.mjs` (mine)
and `lib/claims-gate.mjs` (imported twice by self-check).

Do not reconstruct a gate's roster by grepping for the token in its message. I did, found
ZERO, and nearly reported the gate as broken. The note reports a per-file *tier*
(`tiers.filenameOnly`) — a classification of a BRANCH, not a text search for `endsWith`.
`node lib/main-only-audit.mjs --json` prints the report and THEN exits 1, so
`execFileSync` throws with the JSON already complete on `err.stdout`; treating that as a
harness failure is the second way to get this wrong.

## A probe with no positive control reports "safe" for every file in the repo
Testing whether the argv-only files leak into a self-check importer, my first probe said
LEAK for all six. It was wrong twice over:
  1. `node -e "…" --selftest` sends the flag to **NODE**, not `process.argv` — node answers
     "bad option", which is a broken probe wearing the costume of a leak.
  2. A bare absolute path on Windows has scheme `c:`, and the ESM loader rejects it with
     ERR_UNSUPPORTED_ESM_URL_SCHEME — a probe failure that reads like a crash in the file
     under test.
Both produced confident wrong answers. The probe needs a **file** (argv pushed BEFORE the
dynamic import, target as a `file://` URL) and a **positive control** — a module that prints
then `process.exit(0)` — or its "safe" verdicts are indistinguishable from having no probe.
Result once fixed: all 11 files safe, guard effective in both directions (importer-safe AND
still runs standalone).

## Closing a "known blind spot" is three bugs wearing one trench coat (2026-09-27)
`lab/import-guard/detector.mjs` documented a permanent blind spot: a backtick span ran
to the next backtick, so `${…}` was swallowed as string and a self-execution site
written inside an interpolation was invisible. The header said the direction was safe
(a missed site is one line of defence). It was safe about the FALSE POSITIVE and
exactly wrong about the FALSE NEGATIVE, and this gate's job is the false negative.

**The blind spot was reachable.** A module whose body is `const label = \`gate:
${run()}\`` where `run()` exits on `--selftest` really does self-execute on import.
Proven by driving the shape through a real importer, not by reading it.

Three bugs, in order, each looking like the fix:
1. **Cleared `quote` but not `state.inTemplate`.** The backtick branch had set
   `inTemplate = true`; clearing only `quote` left it set, so every character after
   `${` fell into the cross-line template block and hit its bare `continue`, freezing
   `out` at `${`. Found by LOGGING `out` at the top of the loop — after reading the
   code four times, each time concluding "looks right".
2. **Kept the depth counter per-line.** A `${JSON.stringify(\n foo \n)}` spanning
   lines left the `}` at its end looking like a fresh interpolation, re-opening an
   already-open template and latching `inTemplate` true FOR THE REST OF THE FILE. The
   damage was not a missed warning: it made a baselined PROTECTED file
   (`lab/pane-diff/role-scan.mjs`) report CLEAN, and the gate then told the operator
   to **delete that file's baseline entry as stale** — an exemption removed on the
   strength of a scanner bug. Found by asking why a protected file had become clean.
3. **Widened an exemption to cover the case in front of me.** "Is there a call before
   the span?" also excused `const FLAG = '--selftest'`, which a long-standing control
   pins as a LEAK. The control caught it. Narrowed to the ternary-selection shape.

Two general rules:
  - **A cross-line construct needs cross-line state.** A depth counter re-seeded to
    zero each line is not a counter, it is a guess — and the failure is a scanner that
    is *more* confident than before, which is worse than the bug it replaced.
  - **"This file is now clean, prune its exemption" is a DANGEROUS message**, and a
    gate that emits it must be trusted more than usual, not less. Any scanner change
    that makes a baselined entry go stale should be treated as a finding about the
    CHANGE until the file is read by hand. It was, and the file had not been fixed.

Corollary on the state itself: the first fix for #1 was found by instrumenting `out`
at the top of the loop, after four readings of the diff all said the handler was
correct. **When a fix that looks right changes nothing, log the value at the boundary
rather than reading the code again** — a reader confirms what it expects.

## One flag, two formats: a reader cannot tell "nothing happened" from "never JSON" (2026-09-27)
`lib/loopback-probe.mjs --trace=FILE` meant two different things. Loop mode appended
`JSON.stringify(sample)`; single-shot appended the formatted verdict LINE. Same flag,
same filename convention, two formats — so a file's format depended on how it was
invoked, and a consumer had to know the invocation to parse it.

The reason it survived is worth stating, because it is the general shape:
**a reader that maps-and-filters turns "malformed" into "absent."** The lib's
`readTrace` does `map(parse → null on failure)` then `.filter(Boolean)`, so a
TEXT trace reads as an EMPTY trace — not as a wrong one. A text trace and a
missing file are indistinguishable to it. Both of my teeth controls failed until
I noticed my own harness had the same reader minus the `.filter(Boolean)`, and
was therefore counting a malformed line as a row: asserting the opposite of the
truth. If your harness reimplements the reader, copy the reader's *error
handling*, not just its parse call.

Fix: one exported `traceRecord({ mode, sample, verdictLine })` and one
`writeTraceLine(file, record)`, used by both modes. Three decisions make it a
shared format rather than a lowest common denominator:
  - `mode` is IN the record, so a consumer never infers it from the filename.
  - loop-only fields (`seq`, `windowOpen`, `windows`) are **present-and-null** in a
    once-record. Absent and null are different answers, and JSON.stringify drops
    `undefined` — so a dropped key is literally a different schema, which is the
    failure the change set out to remove. Pinned by round-tripping through JSON.
  - the human `line` became a FIELD rather than the file's format, so stdout is
    byte-identical (the guide documents that output) and a grep for the verdict
    still works.

General rule: **a flag whose output format varies by mode is a schema with no
schema.** Fix the format; do not document the difference — a reader that silently
reads the wrong file as empty will not read the documentation either.

Two harness lessons from the same control:
  - It passed `--trace FILE` and the parser takes `--trace=FILE` and `--loop`;
    the child exited 0, wrote nothing, and every assertion failed on `rows=0`.
    **A control that drives a CLI must use the CLI's documented spelling, and a
    flag the parser does not recognise should be a refusal, not a shrug.** (That
    refusal is a real, separate gap in this file — recorded, not fixed here.)
  - `{ ...r, seq: undefined }` does NOT model a dropped key: spreading keeps the
    key and `Object.keys` still lists it. The drop happens in `JSON.stringify`,
    so the model has to go through JSON.
- [2026-09-27] MULTI-LANE "STILL OPEN" LISTS ARE SNAPSHOTS, NOT STATE: three lanes in one day re-reported closed items (the pool lane's "3 unrunnable", the docs lane's cross-check findings AND its two class-4s, flagged 3x as still-unfixed a flake that was already fixed at the writer with a measured comment). A peer lane's turn starts before the fixes land and drains after; the backlog replays its snapshot on every drain. Before correcting a peer or closing their finding, date-stamp the evidence — wall log mtimes, thread queue position+pause state — and diff their claim against it. Timestamps resolved in seconds what a re-argument would have burned a turn on. Ack with evidence, not with arguments.
- [2026-09-27] A DRAMATIC RESULT DESERVES A CHECK OF THE INSTRUMENT FIRST: three same-day harness bugs almost inverted verdicts — a hijack probe whose subject called the controls itself (shouted HIJACKED while the guard held), auditFile defaulting a missing src to the empty string ("no findings" for every file), and a wrong first-draft detail extractor (picked the stack frame, dropped the Error). Tell: when a result is surprising in the direction that makes you look good (subject broken) OR bad (my fix inverted), re-run against a fixture you can hand-verify before believing it. The instrument is guilty until the fixture proves it innocent.
- [2026-09-27] A PHANTOM DEFECT ATTRACTS A SECOND FIX: two lanes independently proposed the same mechanical "repair" (round/loosen exact float mtime equality, or re-seed the cache after utimesSync) for a defect that did not exist — the pattern looked wrong without the round-trip measurement (2007 values, 0 lossy; stat-vs-stat is exact by construction), and either change would have shipped a stale-hash cache hit on exactly the same-size same-second edit the key exists to catch. When a "fix" targets an INVARIANT, measure whether the invariant is real before touching it, and write the resolution into the ledger where the phantom was filed — the original handback entry still invites a third fixer if nobody closes the loop in place.
- [2026-09-27] THREE FIXTURE FAULTS IN A ROW, LIB RIGHT EVERY TIME (listen-retry selftest): a setTimeout stub that SWALLOWED the callback made 'each retry re-listens' unassertable — an assertion that cannot see the thing cannot fail on its absence, so make stubs invoke, not discard; a `maxMs: 0` budget fired in the same millisecond as t0 fails a `> maxMs` guard by TIMING, not contract — a negative budget is the honest "deadline long past"; and control ORDER matters when the contract reads a module global — the give-up control set gaveUpBinding=true and the reporting control behind it asserted false against the poisoned value, proving nothing. Same-ms Date.now() collisions are the NORM on this box, never assume a control has outrun the clock.
- [2026-09-27] THE INSTRUMENT WAS TESTED ON THE ONLY LINE ENDING THE REPO DOES NOT USE: main-only-audit's guard-alias map split on '\n', so every CRLF line kept a trailing \r that `.` cannot match and non-m `$` cannot span — the map came back EMPTY for every file in the tree and two correctly-guarded files were reported as defects. Every existing control built its fixture with \n, so the gate had only ever been tested on the ending this repo does not use. Fix at the writer (split(/\r?\n/)) + a NEGATIVE control (a genuinely unguarded branch in a CRLF file must STILL fire, or the fix disarms the tier). When a matcher is line-oriented, its fixtures must include the repo's actual line ending.
- [2026-09-27] A CLAIM RECORD MUST NOT BE A FUNCTION OF WHERE THE CLAIM IS PRINTED: `npm install` appears at five RUNBOOK lines as one claim id; lockOf took the LAST occurrence, so the record read ok because a verifying line happened to come after the one that could not (skip@2284). Records now aggregate over a total order least- to most-damning (ok < skip < fail): an absence is never recorded as a success, a real red is never masked by the other occurrences' health. Any per-claim record keyed across repeated text needs a declared aggregation, not last-write-wins.
- [2026-09-27] SILENT MUTATION UNDER ANOTHER NAME: a mutated copy named _g.mjs exited 0 in silence because the gate's MAIN guard was argv[1].endsWith('claims-gate.mjs') — a copy under another name runs nothing and reports success, so the mutation "passed". Mutate IN PLACE with a restore trap. And on a shared tree with 28 foreign node.exe, checksum what you edit: a lane found npm-install output spliced into the middle of a comment in lib/runbook-claims.mjs; repaired exactly, writer unidentified — the claims registry should record the sha a claim holder left the file at, so release detects foreign edits (proposed, not yet built).
- [2026-09-27] APPENDING A SELFTEST BRANCH DOES NOT DISARM THE EXISTING MAIN GUARD: adding the standard branch at the file tail left the original bare-run guard firing FIRST on --selftest — which ran live main() (a real state scan) instead of the controls. When a file already has a bare-run MAIN block, the new --selftest branch needs the old guard to EXCLUDE the flag, and the fixture must prove the flag reaches the controls. And a fixture's "settled canonical" must satisfy the real predicate's full contract (status done/transferred AND rounds>=3) — a plausible-looking status that the predicate rightly rejects scans zero families and every positive control "passes" vacuously in the negative direction.
- [2026-09-27] FOUR SUITES, ONE RED SHAPE, NOT ALWAYS ONE BUG: a wall reported watchdog FAIL (expected refused, saw timeout) and it read as the loopback-probe contention class — fourth "witness". Traced: watchdog's OWN portBound fixture races a 1ms fake-error against a 5ms unref'd budget, and under pool starvation the timeout wins the settled race. Same SYMPTOM (a control failing on contention), different FILE and MECHANISM (separate pre-probe implementation, launcher decision probe). Before folding flaky controls into one class fix, trace at least one witness to its actual line — a shared symptom family can hide several real bugs, and fixing only the famous one leaves the rest. Fixture rule that falls out: make fake sockets fire SYNCHRONOUSLY inside connect() (no timer race at all), or keep fire-delay and budget in different orders of magnitude.
- [2026-09-27] THE tasklist /FI MANGLE IS A BASH-SHELL RULE, NOT A NODE RULE — PRECISION BEFORE A SWEEP: Git Bash rewrites `/FI` into a path, so INTERACTIVE `tasklist /FI` returns nothing (silently — no error). But node's spawnSync('tasklist', ['/FI', ...]) is UNAFFECTED: measured 45-char stdout with the pid row on single-slash, while double-slash //FI from node returns 0 bytes. A lane's broadcast of the //NH workaround would have broken self-check.mjs:498 (the supervisor pid-liveness gate) if applied to node call sites. Before broadcasting a "this call is broken" rule, reproduce it in the caller's own context — shell idiom and child-process argv are different layers, and the fix for one is the bug for the other.
- [2026-09-27] A STATUS LINE COPIED FROM AN EARLIER REPORT IS AN UNMEASURED CLAIM — OWNED BY THE CARRIER, NOT THE WRITER: one lane carried "rate-degradation still unrunnable" through EIGHT-PLUS deliveries after it was fixed, each report re-citing the line; the correcting lane's own rule (re-run the thing before repeating the line — one command) is the operational fix. The structural half stands too: lib/ is untracked, so no two lanes can see each other's state — a claims ledger that records the FILE'S GATE RESULT at claim time (not just who holds it) would make "is it still true?" answerable without a rerun. And the correction itself is worth what it cost: the carrier who finds their own stale line and says so in public, with the count of affected deliveries, is the reason multi-lane trees stay trustworthy.
