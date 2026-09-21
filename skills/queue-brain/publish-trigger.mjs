// publish-trigger.mjs — make the SKILL.md publish trigger fire ON ITS OWN.
//
// WHY. SKILL.md says: when the lessons working set grows past 10 entries,
// suggest publishing, once per crossing. But the only thing that ran the
// comparison was a session REMEMBERING to do it — and the ledger proves how
// that goes: the marker sat at 137 while the file held 173 bullets. The trigger
// never fired because nothing was watching. This module is the watcher.
//
// Contract (same counting rule publish-queue-brain.mjs uses, kept in sync by
// that script's reset step):
//   count = every `- ` bullet OUTSIDE the `## Promotion log` section
//   fire  = count >= marker + 10 (the next 10-entry crossing)
//           OR count >= 10 with no marker at all (first crossing)
//   warn once per crossing: on fire, the marker MOVES to the current count, so
//   the same crossing cannot warn twice; the next warning needs ten NEW entries.
//   A publish resets the marker to the post-publish count (a publish IS the
//   reset event) — see publish-queue-brain.mjs step 4.
//
// Output is ONE line, non-blocking, never throws:
//   fired →   "-publish? N lessons accumulated (last suggested at M) — node ~/.agents/skills/queue-brain/publish-queue-brain.mjs"
//   quiet →   "" (empty string, exit 0) — silence IS the healthy state
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

export const CROSSING = 10;

/** Every `- ` bullet outside the Promotion log — the same rule the publish script resets with. */
export function workingSetCount(raw) {
  const sections = raw.split(/^## /m);
  const withoutPromotions = sections.filter((s) => !/^Promotion log/.test(s)).join('## ');
  return (withoutPromotions.match(/^- /gm) || []).length;
}

export function markerValue(raw) {
  const m = raw.match(/<!-- publish trigger: last suggested at (\d+)/);
  return m ? Number(m[1]) : null;
}

/**
 * The pure decision. Returns { fire, count, marker, message }.
 * marker === null means no marker line exists (first crossing counts from 0).
 */
export function decide(count, marker, crossing = CROSSING) {
  const base = marker ?? 0;
  const fire = count >= base + crossing;
  const message = fire
    ? `${count} lessons accumulated (last suggested at ${marker ?? 0}) — publish? node ~/.agents/skills/queue-brain/publish-queue-brain.mjs`
    : '';
  return { fire, count, marker, message };
}

/** Read the canonical lessons.md (or `lessonsPath`), decide, and on fire MOVE the marker. */
export function checkPublishTrigger(lessonsPath) {
  if (!existsSync(lessonsPath)) return { fire: false, message: '', skipped: 'no lessons.md' };
  const raw = readFileSync(lessonsPath, 'utf8');
  const count = workingSetCount(raw);
  const marker = markerValue(raw);
  const d = decide(count, marker);
  if (d.fire) {
    // Move the marker to the CURRENT count: one warning per crossing. If the
    // write fails (read-only mount), the fire is still returned — a repeated
    // warning beats a silently swallowed one.
    const updated = raw.replace(
      /<!-- publish trigger: last suggested at \d+([^>]*) -->/,
      `<!-- publish trigger: last suggested at ${count} · reset after running publish-queue-brain.mjs -->`
    );
    try { writeFileSync(lessonsPath, updated); } catch { /* advisory only */ }
  }
  return { fire: d.fire, count, marker, message: d.message };
}

// --- selftest ----------------------------------------------------------------
// node publish-trigger.mjs --selftest
if (import.meta.url === `file://${process.argv[1]?.replace(/\\/g, '/')}` || process.argv.includes('--selftest')) {
  let pass = 0, fail = 0;
  const ok = (n, c) => { if (c) { pass++; console.log(`PASS  ${n}`); } else { fail++; console.log(`FAIL  ${n}`); } };
  const doc = (bullets, marker) =>
    `# Lessons\n\n## Working set\n\n${marker ? `<!-- publish trigger: last suggested at ${marker} · reset after running publish-queue-brain.mjs -->\n\n` : ''}${Array.from({ length: bullets }, (_, i) => `- 2026-09-21 · p · lesson ${i + 1}`).join('\n')}\n\n## Promotion log\n\n- promoted entry must NOT count\n`;

  ok('count excludes the Promotion log', workingSetCount(doc(3, null)) === 3);
  ok('marker parsed from the comment', markerValue(doc(3, 137)) === 137);
  ok('no marker reads as null (first crossing from 0)', markerValue(doc(3, null)) === null);

  ok('no crossing: 5 new of 10 silent', decide(15, 10).fire === false && decide(15, 10).message === '');
  ok('crossing: 10 new fires', decide(20, 10).fire === true);
  ok('first crossing with no marker: >=10 fires', decide(10, null).fire === true);
  ok('9 total with no marker is silent', decide(9, null).fire === false);

  // once-per-crossing behavior through the file round-trip
  const { mkdtempSync, rmSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const dir = mkdtempSync(join(tmpdir(), 'pubtrig-'));
  const p = join(dir, 'lessons.md');
  const { writeFileSync: w } = await import('node:fs');
  w(p, doc(30, 20));
  const r1 = checkPublishTrigger(p);
  ok('file round-trip: fires at 30 with marker 20', r1.fire === true && /30 lessons/.test(r1.message));
  ok('marker moved to current count after firing', markerValue(readFileSync(p, 'utf8')) === 30);
  const r2 = checkPublishTrigger(p);
  ok('same crossing does not warn twice', r2.fire === false && r2.message === '');
  w(p, doc(40, 30));
  const r3 = checkPublishTrigger(p);
  ok('a NEW 10-entry crossing fires again', r3.fire === true, JSON.stringify(r3));
  rmSync(dir, { recursive: true, force: true });

  console.log(`publish-trigger selftest: ${pass} PASS, ${fail} FAIL`);
  process.exit(fail ? 1 : 0);
} else {
  // CLI: node publish-trigger.mjs [lessonsPath] — print the one-line publish
  // prompt when a crossing fired; print nothing (exit 0) when silent. This is
  // the form session-start and nightly hooks call.
  const { homedir } = await import('node:os');
  const p = process.argv[2] || join(homedir(), '.agents', 'skills', 'queue-brain', 'lessons.md');
  const r = checkPublishTrigger(p);
  if (r.fire && r.message) console.log(r.message);
}
