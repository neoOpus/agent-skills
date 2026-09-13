# queue-brain

[![Install with Skills CLI](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fwww.skills.sh%2Fapi%2Fsearch%3Fq%3Dqueue-brain&query=%24.skills%5B%3F(%40.id%3D%3D'neoopus%2Fagent-skills%2Fqueue-brain')%5D.installs&label=skills.sh%20installs&suffix=%20installs&color=blue)](https://www.skills.sh/neoopus/agent-skills/queue-brain)
[![skills.sh](https://img.shields.io/badge/registry-skills.sh-black)](https://www.skills.sh/neoopus/agent-skills/queue-brain)

Prompt-to-queue intake and priority brain for AI coding agents.

Every incoming prompt becomes a todolist entry instead of immediate work;
entries are re-ranked continuously (blockers rise, red-state failures outrank
features, timed entries decay, obsolescence is flagged); execution happens
only on an explicit `GO` (or `auto` mode). Quality-gated: entries are done
only when verified through the real surface, with lessons extracted to a
shared `lessons.md` that gets promoted back into the skill's rules over time.

Works in any project and any agent harness — Codebuff/Freebuff, Claude Code,
Gemini/Antigravity, Cursor, Codex.

## Install

```bash
npx skills add neoOpus/agent-skills@queue-brain -g
```

Listed on the [skills.sh registry](https://www.skills.sh/neoopus/agent-skills/queue-brain).

Or manually: copy the `queue-brain/` directory into your harness's skills
directory (`~/.agents/skills/`, `~/.claude/skills/`, `~/.gemini/skills/`,
`~/.cursor/skills/`, `~/.codex/skills/` — whichever your harness reads).

## One brain, many harnesses

The canonical copy lives in `~/.agents/skills/queue-brain/`. On Windows, run
`link-others.ps1` once to junction the other harness dirs to it, so every
harness shares one `lessons.md` and one SKILL.md. `sync-queue-brain.mjs`
maintains installs across machines and new harnesses:

```bash
node sync-queue-brain.mjs              # check/repair all installs
node sync-queue-brain.mjs --overwrite  # replace diverged real copies
node sync-queue-brain.mjs --add <dir>  # register another harness dir
```

## Use

- `/queue-brain` or "queue mode" — activate; prompts enqueue, nothing runs
- `go [entry]` — execute top (or named) entry, verify, re-rank
- `auto` — enqueue + execute top entry each turn
- `review` — print the ranked list, no work
- `queue review lessons` — promote recurring lessons into SKILL.md rules

## Files

- `SKILL.md` — the skill: intake/dedupe/re-rank loop, quality gate, instruments
- `lessons.md` — the shared learning brain (edit freely; one line per lesson)
- `sync-queue-brain.mjs` — multi-harness install maintenance
- `link-others.ps1` — Windows junction builder for the canonical copy

MIT license.
