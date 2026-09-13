#!/usr/bin/env node
// sync-queue-brain.mjs — keep queue-brain installed across all agent harnesses.
//
// Canonical copy: ~/.agents/skills/queue-brain (edit THIS one; it's the brain).
// On this machine the other harness dirs are NTFS junctions to it
// (link-others.ps1 built them), so they never drift. But junctions are
// machine-local: a new machine, a harness installed later, or a harness that
// doesn't follow junctions needs real copies. This script handles both cases:
//   - target is a junction pointing at the canonical dir → OK, skip
//   - target missing → try junction first (no admin needed); --copy to force a real copy
//   - target is a real dir with identical SKILL.md → OK, skip (--copy to refresh)
//   - target is a real dir that DIVERGED → warn, skip unless --overwrite
//
// Usage:  node sync-queue-brain.mjs [--copy] [--overwrite] [--add <dir>]
//   --copy        copy files instead of junctioning new installs
//   --overwrite   allow overwriting diverged real copies (with canonical content)
//   --add <dir>   add another harness skills dir to the managed set (persisted
//                 to sync-targets.json next to this script)

import { readdirSync, statSync, readFileSync, writeFileSync, existsSync, mkdirSync, cpSync, readlinkSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const HERE = dirname(fileURLToPath(import.meta.url));
const CANON = HERE; // this script ships inside the canonical copy
const SKILL = join(CANON, 'SKILL.md');
const TARGETS_FILE = join(CANON, 'sync-targets.json');

const DEFAULT_TARGETS = [
  join(process.env.USERPROFILE || process.env.HOME || '', '.claude', 'skills', 'queue-brain'),
  join(process.env.USERPROFILE || process.env.HOME || '', '.gemini', 'skills', 'queue-brain'),
  join(process.env.USERPROFILE || process.env.HOME || '', '.cursor', 'skills', 'queue-brain'),
  join(process.env.USERPROFILE || process.env.HOME || '', '.cursor', 'skills-cursor', 'queue-brain'),
  join(process.env.USERPROFILE || process.env.HOME || '', '.codex', 'skills', 'queue-brain'),
];

const args = process.argv.slice(2);
const COPY = args.includes('--copy');
const OVERWRITE = args.includes('--overwrite');
const addIdx = args.indexOf('--add');
const addDir = addIdx >= 0 ? args[addIdx + 1] : null;

function loadTargets() {
  let extra = [];
  try { extra = JSON.parse(readFileSync(TARGETS_FILE, 'utf8')); } catch { /* first run */ }
  return [...new Set([...DEFAULT_TARGETS, ...extra])].filter(Boolean);
}

function saveTarget(t) {
  let extra = [];
  try { extra = JSON.parse(readFileSync(TARGETS_FILE, 'utf8')); } catch { /* first run */ }
  if (!extra.includes(t)) { extra.push(t); writeFileSync(TARGETS_FILE, JSON.stringify(extra, null, 2)); }
}

function isJunctionTo(p, target) {
  try {
    const st = statSync(p);
    if (!st.isDirectory()) return false;
    // Windows junctions surface as reparse points; readlink resolves them
    const resolved = readlinkSync(p).replace(/\//g, '\\');
    return resolved.toLowerCase().includes('queue-brain');
  } catch { return false; }
}

function skillHash(p) {
  try { return readFileSync(join(p, 'SKILL.md'), 'utf8').length + ':' + readFileSync(join(p, 'SKILL.md'), 'utf8').split('\n').length; }
  catch { return null; }
}

const canonHash = skillHash(CANON);
let ok = 0, fixed = 0, warn = 0;

for (const t of loadTargets()) {
  if (t === CANON) continue;
  const name = t.split(/[\\/]/).slice(-3).join('/');

  if (!existsSync(t)) {
    mkdirSync(dirname(t), { recursive: true });
    if (!COPY) {
      try {
        execFileSync('cmd', ['/c', 'mklink', '/J', t, CANON], { stdio: 'pipe' });
        console.log(`junctioned  ${name} (new)`);
      } catch {
        cpSync(CANON, t, { recursive: true });
        console.log(`copied      ${name} (junction failed — real copy)`);
      }
    } else {
      cpSync(CANON, t, { recursive: true });
      console.log(`copied      ${name} (new, --copy)`);
    }
    fixed++; continue;
  }

  if (isJunctionTo(t, CANON)) { console.log(`ok junction ${name}`); ok++; continue; }

  const h = skillHash(t);
  if (h === canonHash) { console.log(`ok copy     ${name}`); ok++; continue; }

  if (OVERWRITE) {
    cpSync(CANON, t, { recursive: true, force: true });
    console.log(`overwrote   ${name} (diverged, --overwrite)`);
    fixed++;
  } else {
    console.log(`DIVERGED    ${name} — real copy differs from canonical; rerun with --overwrite to replace`);
    warn++;
  }
}

if (addDir) {
  saveTarget(addDir);
  console.log(`added target: ${addDir} (rerun to sync it)`);
}

console.log(`\n${ok} in sync · ${fixed} fixed · ${warn} need attention${warn ? ' (rerun with --overwrite)' : ''}`);
