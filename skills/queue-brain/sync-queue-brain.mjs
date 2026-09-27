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

import { readdirSync, statSync, lstatSync, readFileSync, writeFileSync, existsSync, mkdirSync, cpSync, realpathSync, mkdtempSync, rmSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
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

// Compare two Windows paths for identity rather than resemblance.
//
// `\\?\` is the NT object-manager prefix a junction's readlink often carries and
// never appears in a path the user typed; trailing separators are not a
// difference. Case is not a difference on NTFS. Getting this wrong does not
// crash — it reports a correct junction as diverged, or worse, reports a wrong
// one as correct.
const samePath = (a, b) => normPath(a) === normPath(b);
function normPath(p) {
  return String(p).replace(/^\\\\\?\\/, '').replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
}

// Is `p` a junction/symlink that lands on `target`?
//
// THE DEFECT THIS FIXES. The parameter `target` was never read. The old body
// asked only whether the resolved link path CONTAINED the string 'queue-brain',
// so any junction to any other queue-brain-shaped directory — a stale install, a
// second checkout, a different user's profile, a backup someone restored —
// reported `ok junction` and was never content-checked. The check was a
// substring test standing in for a path comparison, and the parameter meant to
// make it a comparison was dead code.
//
// WHY realpath AND NOT readlink. `readlink` returns the link's IMMEDIATE target,
// which for a junction-to-a-junction is the middle of the chain, not the place
// the files actually live. `realpath` resolves all the way through, so a target
// that reaches the canonical directory by any number of hops still compares
// equal. Comparing a resolved link against a resolved canonical is also immune
// to the `\\?\` and separator differences that make string comparison brittle.
function isJunctionTo(p, target) {
  try {
    // lstat, not stat: stat() follows the link and would report a plain
    // directory, which is how a real copy could pass as a junction.
    if (!lstatSync(p).isSymbolicLink()) return false;
    return samePath(realpathSync(p), realpathSync(target));
  } catch {
    // A dangling junction, or a canonical that does not exist. Either way this
    // is not a verified link to the target, and the caller falls through to the
    // content check, which is the safe direction.
    return false;
  }
}

// A CONTENT digest, not a shape.
//
// THE DEFECT THIS FIXES. The old fingerprint was `byteLength + ':' + lineCount`.
// That is a property of the file's GEOMETRY, not its content, so the whole class
// of same-length edits passed as in sync: a swapped version number, `8082` for
// `8091`, `bravo` for `BRAVO`, a changed path in an example, an inverted
// condition. Each of those keeps the byte count identical and the line count
// identical, so `h === canonHash` and the script printed `ok copy` for a file
// that had drifted — which is the one thing this script exists to prevent. It
// also read SKILL.md twice to compute a number that one pass would do.
//
// sha256 over the bytes, so any edit at all changes the fingerprint.
//
// SCOPE, deliberately unchanged: this hashes SKILL.md only, which is the contract
// the header documents ("a real dir with identical SKILL.md"). README.md and
// lessons.md are copied by --copy/--overwrite but are NOT part of the equality
// test, so they can still drift silently. Widening the fingerprint to the whole
// directory is a one-line change, but it changes what counts as DIVERGED for
// every existing install, so it is a decision rather than a bug fix.
function skillHash(p) {
  try {
    return createHash('sha256').update(readFileSync(join(p, 'SKILL.md'))).digest('hex');
  } catch { return null; }
}

// ---- controls -------------------------------------------------------------
// Both functions above had a defect that a test written to match the code would
// have passed. These are written to FAIL on the old bodies, and two of them are
// labelled PLANT for that reason: the equal-length edit and the look-alike
// junction are the exact two cases the old code got wrong, so they are the only
// two worth being sure about.
//
// Junctions, not symlinks: `mklink /J` needs no elevation (a symlink does), and
// the script's own install path uses junctions, so the fixture matches reality.
function mkjunction(link, dest) {
  execFileSync('cmd', ['/c', 'mklink', '/J', link, dest], { stdio: 'pipe' });
}

export function selftest() {
  let pass = 0, fail = 0;
  const ok = (c, name, detail = '') => { if (c) { pass += 1; console.log('  ok  ', name, detail); } else { fail += 1; console.log('  FAIL', name, detail); } };

  const root = mkdtempSync(join(tmpdir(), 'qb-selftest-'));
  const cleanup = () => { try { rmSync(root, { recursive: true, force: true }); } catch { /* windows lingers on junctions */ } };
  try {
    const dir = (name, body) => { const d = join(root, name); mkdirSync(d, { recursive: true }); writeFileSync(join(d, 'SKILL.md'), body, 'utf8'); return d; };

    // ---- skillHash -------------------------------------------------------
    const a = dir('a', 'alpha\nbravo\n');
    const b = dir('b', 'alpha\nBRAVO\n');   // SAME byte length, SAME line count
    const c = dir('c', 'alpha\nbravo!\n');  // one byte longer
    const d = dir('d', 'alpha\nbravo');     // no trailing newline -> one fewer line

    ok(skillHash(a) === skillHash(dir('a2', 'alpha\nbravo\n')),
      'identical content hashes identically');
    ok(skillHash(a) !== skillHash(b),
      'PLANT: a same-length, same-line-count edit is NOT in sync — the exact case the old length:lineCount fingerprint called equal');
    ok(skillHash(a) !== skillHash(c), 'a one-byte-longer edit is not in sync');
    ok(skillHash(a) !== skillHash(d), 'a dropped trailing newline is not in sync');
    ok(/^[0-9a-f]{64}$/.test(skillHash(a)), 'the fingerprint is a sha256 hex digest', skillHash(a).slice(0, 16) + '…');
    ok(skillHash(join(root, 'does-not-exist')) === null, 'an absent SKILL.md is null, not a hash of nothing');
    // The old fingerprint's own values, restated: equal, which is why it failed.
    const geom = (s) => s.length + ':' + s.split('\n').length;
    ok(geom('alpha\nbravo\n') === geom('alpha\nBRAVO\n'),
      'PLANT: the OLD geometry fingerprint really did call these two files equal — the defect, demonstrated rather than asserted');

    // ---- isJunctionTo ----------------------------------------------------
    // A decoy canonical that is NOT `target`. Its path deliberately ends in
    // 'queue-brain', because that is the substring the old check looked for.
    const decoy = dir(join('decoy', 'queue-brain'), 'decoy\n');
    const fake = join(root, 'fake-link');
    mkjunction(fake, decoy);
    const good = join(root, 'good-link');
    mkjunction(good, a);
    const plain = dir('plain', 'alpha\nbravo\n');   // a REAL dir, not a link

    ok(isJunctionTo(good, a) === true, 'a junction pointing AT the target is recognised');
    ok(isJunctionTo(fake, a) === false,
      'PLANT: a junction to a different queue-brain-shaped dir is NOT a junction to the target — the old substring check called this one ok');
    ok(isJunctionTo(plain, a) === false, 'a real directory is not a junction, even when its content matches');
    ok(isJunctionTo(join(root, 'nope'), a) === false, 'a missing path is not a junction');
    // Case and separator noise must not defeat a correct link.
    ok(samePath('C:\\Dev\\qb', 'c:/dev/qb/'), 'path comparison ignores case, slash direction and a trailing separator');
    ok(samePath('\\\\?\\C:\\Dev\\qb', 'C:\\Dev\\qb'), 'the NT \\\\?\\ prefix does not make one path a different path');
    ok(!samePath('C:\\Dev\\qb', 'C:\\Dev\\qb2'), 'a shared PREFIX is not identity — qb2 is not qb');
  } finally { cleanup(); }

  console.log(`\n${pass} pass, ${fail} fail`);
  return fail === 0 ? 0 : 1;
}

if (process.argv.includes('--selftest')) process.exit(selftest());

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
