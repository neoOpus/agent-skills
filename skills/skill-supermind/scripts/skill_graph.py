#!/usr/bin/env python3
"""Index, validate, and query a graph of Agent Skills.

Python 3.10+; standard library only. JSON is written to stdout, diagnostics to
stderr. All source validation happens before index mutation, and a successful
refresh replaces the previous snapshot in one transaction.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TAG_RE = re.compile(r"(?<![\w#])#([a-z0-9][a-z0-9_.-]{0,63})(?=$|[^\w-])", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)
QUERY_STOPWORDS = {
    "a", "an", "and", "are", "build", "can", "create", "current", "for", "get", "help", "in", "is", "it", "make", "need", "of", "on", "or", "please", "short", "should", "the", "to", "use", "want", "with", "write",
}
# Conversational and factual filler terms are not routing evidence. Keeping
# them out of the evidence calculation prevents generic questions from
# becoming accidental skill triggers.
NEGATIVE_EVIDENCE_STOPWORDS = {
    "about", "capital", "city", "france", "is", "morning", "my", "next", "note", "paris", "reflective", "short", "tuesday", "walk", "weather", "what", "when", "where", "which", "who", "why",
}
POSITIVE_ACTION_TOKENS = {
    "audit", "build", "check", "connect", "create", "debug", "deploy", "design", "execute", "find", "fix", "hold", "improve", "index", "make", "optimize", "preserve", "publish", "refactor", "retrieve", "review", "route", "run", "save", "search", "start", "test", "write",
}
POSITIVE_CONTENT_ANCHORS = {"catalog", "catalogs", "index", "indexing", "skill", "skills", "sqlite"}
RELATION_TYPES = {
    "parent",
    "composes",
    "requires",
    "validates",
    "alternative-to",
    "supersedes",
    "related-to",
}
CALIBRATION_OUTCOMES = {"success", "partial", "failure", "abstain"}
JOURNAL_SCHEMA_VERSION = "1"
JOURNAL_REDACTION_VERSION = "1"
JOURNAL_SECRET_KEYS = {
    "access_token", "api_key", "apikey", "authorization", "cookie", "credentials",
    "password", "private_key", "refresh_token", "secret", "session", "token",
}
JOURNAL_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(?:sk|pk|ghp|gho|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)([A-Za-z0-9._%+-]+)@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
)
SKIP_DIRS = {
    ".git",
    ".skill-brain",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
}


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class SkillRecord:
    skill_id: str
    name: str
    description: str
    body: str
    path: str
    sha256: str
    line_count: int
    metadata: dict[str, Any]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value in {"true", "false"}:
        return value == "true"
    return value


def split_yaml_line(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise SkillError(f"expected key: value, got {line!r}")
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise SkillError("empty frontmatter key")
    return key, value.strip()


def parse_frontmatter(text: str, path: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must begin with YAML frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise SkillError("SKILL.md has no closing frontmatter delimiter") from exc

    data: dict[str, Any] = {}
    current_map: str | None = None
    i = 1
    while i < end:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if raw[0].isspace():
            if current_map is None:
                raise SkillError(f"line {i + 1}: unexpected indentation")
            key, value = split_yaml_line(stripped)
            target = data[current_map]
            if not isinstance(target, dict):
                raise SkillError(f"line {i + 1}: nested metadata conflicts with scalar")
            target[key] = parse_scalar(value)
            i += 1
            continue

        key, value = split_yaml_line(stripped)
        current_map = None
        if value in {">", "|", ">-", "|-"}:
            chunks: list[str] = []
            i += 1
            while i < end and (not lines[i].strip() or lines[i][:1].isspace()):
                chunks.append(lines[i].strip())
                i += 1
            separator = " " if value.startswith(">") else "\n"
            data[key] = separator.join(chunks).strip()
            continue
        if value:
            data[key] = parse_scalar(value)
        else:
            current_map = key
            data[key] = {}
        i += 1

    body = "\n".join(lines[end + 1 :]).strip() + "\n"
    return data, body


def normalize_tags(text: str) -> list[str]:
    return sorted({match.group(1).lower() for match in TAG_RE.finditer(text)})


def parse_skill(path: Path, root: Path) -> SkillRecord:
    raw_bytes = path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError(f"SKILL.md is not UTF-8: {exc}") from exc
    try:
        frontmatter, body = parse_frontmatter(text, path.as_posix())
    except SkillError as exc:
        raise SkillError(f"{path.as_posix()}: {exc}") from exc

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        raise SkillError(f"{path.as_posix()}: name and description must be strings")

    metadata = frontmatter.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise SkillError(f"{path.as_posix()}: metadata must be a mapping")

    tags = normalize_tags(body)
    for key in ("tags", "skill-tags", "skill_tags"):
        value = metadata.get(key)
        if isinstance(value, str):
            explicit = re.findall(r"#?([a-z0-9][a-z0-9_.-]{0,63})", value.lower())
            tags.extend(explicit)
    tags = sorted(set(tags))

    rel_path = path.relative_to(root).as_posix()
    return SkillRecord(
        skill_id=name,
        name=name,
        description=description.strip(),
        body=body,
        path=rel_path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        line_count=len(text.splitlines()),
        metadata=metadata,
        tags=tuple(tags),
    )


def discover_skills(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("SKILL.md"):
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in relative_parts[:-1]):
            continue
        if any(part.startswith(".") for part in relative_parts[:-1]):
            continue
        paths.append(path)
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def validate_skill(record: SkillRecord, path: Path) -> list[Issue]:
    issues: list[Issue] = []
    add = issues.append
    if not 1 <= len(record.name) <= 64 or not NAME_RE.fullmatch(record.name):
        add(Issue("error", "invalid-name", record.path, "name must use lowercase kebab-case"))
    if path.parent.name != record.name:
        add(Issue("error", "directory-mismatch", record.path, f"name does not match directory {path.parent.name!r}"))
    if not 1 <= len(record.description) <= 1024:
        add(Issue("error", "invalid-description", record.path, "description must contain 1–1024 characters"))
    if not record.body.strip():
        add(Issue("warning", "empty-body", record.path, "skill has no operating instructions"))
    if record.line_count > 500:
        add(Issue("warning", "oversized-skill", record.path, f"{record.line_count} lines exceeds the 500-line recommendation"))
    if not record.tags:
        add(Issue("warning", "no-tags", record.path, "add a few high-signal hashtags for graph discovery"))
    return issues


def load_records(root: Path) -> tuple[list[SkillRecord], list[Issue]]:
    records: list[SkillRecord] = []
    issues: list[Issue] = []
    seen: dict[str, str] = {}
    for path in discover_skills(root):
        try:
            record = parse_skill(path, root)
        except (OSError, SkillError) as exc:
            issues.append(Issue("error", "parse-error", path.as_posix(), str(exc)))
            continue
        if record.skill_id in seen:
            issues.append(Issue("error", "duplicate-name", record.path, f"name duplicates {seen[record.skill_id]}"))
        else:
            seen[record.skill_id] = record.path
        records.append(record)
        issues.extend(validate_skill(record, path))
    return sorted(records, key=lambda r: r.skill_id), sorted(issues, key=lambda i: (i.path, i.code))


def load_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"schema_version": 1, "skills": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"cannot read manifest {path}: {exc}") from exc
    if data.get("schema_version") != 1:
        raise SkillError("manifest schema_version must be 1")
    if not isinstance(data.get("skills"), list):
        raise SkillError("manifest skills must be an array")
    return data


def normalize_edges(records: list[SkillRecord], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Issue]]:
    by_id = {record.skill_id: record for record in records}
    entries: dict[str, dict[str, Any]] = {}
    issues: list[Issue] = []
    for position, raw in enumerate(manifest.get("skills", [])):
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            issues.append(Issue("error", "invalid-manifest-entry", f"skills[{position}]", "entry requires string id"))
            continue
        skill_id = raw["id"]
        if skill_id in entries:
            issues.append(Issue("error", "duplicate-manifest-entry", skill_id, "manifest entry appears more than once"))
        entries[skill_id] = raw
        if skill_id not in by_id:
            issues.append(Issue("error", "missing-manifest-skill", skill_id, "manifest id has no discovered SKILL.md"))

    edges: list[dict[str, Any]] = []
    for source, entry in entries.items():
        confidence = entry.get("confidence", 1.0)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            issues.append(Issue("error", "invalid-confidence", source, "confidence must be between 0 and 1"))
        parent = entry.get("parent")
        if parent is not None:
            if not isinstance(parent, str) or parent == source or parent not in by_id:
                issues.append(Issue("error", "invalid-parent", source, f"invalid parent {parent!r}"))
            else:
                edges.append({"source": source, "target": parent, "type": "parent", "weight": float(confidence), "note": ""})
        relations = entry.get("relations", [])
        if not isinstance(relations, list):
            issues.append(Issue("error", "invalid-relations", source, "relations must be an array"))
            continue
        for relation in relations:
            if not isinstance(relation, dict):
                issues.append(Issue("error", "invalid-relation", source, "relation must be an object"))
                continue
            relation_type = relation.get("type")
            target = relation.get("target")
            weight = relation.get("weight", 1.0)
            note = relation.get("note", "")
            if relation_type not in RELATION_TYPES:
                issues.append(Issue("error", "invalid-relation-type", source, f"unsupported type {relation_type!r}"))
            if not isinstance(target, str) or target == source or target not in by_id:
                issues.append(Issue("error", "invalid-relation-target", source, f"invalid target {target!r}"))
                continue
            if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
                issues.append(Issue("error", "invalid-relation-weight", source, "weight must be between 0 and 1"))
                continue
            if not isinstance(note, str):
                issues.append(Issue("error", "invalid-relation-note", source, "note must be a string"))
                note = ""
            if relation_type in RELATION_TYPES and target in by_id and target != source:
                edges.append({"source": source, "target": target, "type": relation_type, "weight": float(weight), "note": note})
    return edges, issues


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def create_schema(conn: sqlite3.Connection) -> bool:
    conn.executescript(
        """
        DROP TABLE IF EXISTS skills_fts;
        DROP TABLE IF EXISTS skill_tags;
        DROP TABLE IF EXISTS edges;
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS skills;
        DROP TABLE IF EXISTS meta;
        CREATE TABLE skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            body TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            line_count INTEGER NOT NULL,
            metadata_json TEXT NOT NULL,
            domain TEXT,
            confidence REAL NOT NULL DEFAULT 1.0
        );
        CREATE TABLE tags (tag TEXT PRIMARY KEY);
        CREATE TABLE skill_tags (skill_id TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE, tag TEXT NOT NULL REFERENCES tags(tag) ON DELETE CASCADE, PRIMARY KEY (skill_id, tag));
        CREATE TABLE edges (
            source TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
            target TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            weight REAL NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (source, target, type)
        );
        CREATE INDEX idx_skill_tags_tag ON skill_tags(tag, skill_id);
        CREATE INDEX idx_edges_source ON edges(source, type, target);
        CREATE INDEX idx_edges_target ON edges(target, type, source);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    try:
        conn.execute("CREATE VIRTUAL TABLE skills_fts USING fts5(skill_id UNINDEXED, name, description, tags, body, tokenize='unicode61 remove_diacritics 2')")
        return True
    except sqlite3.OperationalError:
        return False


def refresh_index(root: Path, db: Path, manifest_path: Path | None, strict: bool) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        fail(f"skill root is not a directory: {root}")
    try:
        records, validation_issues = load_records(root)
        manifest = load_manifest(manifest_path)
        edges, manifest_issues = normalize_edges(records, manifest)
    except SkillError as exc:
        fail(str(exc))
    issues = validation_issues + manifest_issues
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors or (strict and any(issue.severity == "warning" for issue in issues)):
        result = {"ok": False, "indexed": False, "issues": [i.as_dict() for i in issues]}
        return result

    manifest_entries = {entry["id"]: entry for entry in manifest.get("skills", []) if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path is not None else ""
    db.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    conn: sqlite3.Connection | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{db.name}.", suffix=".tmp", dir=db.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        conn = connect(str(temp_path))
        conn.execute("PRAGMA journal_mode = DELETE")
        fts_enabled = create_schema(conn)
        with conn:
            for record in records:
                entry = manifest_entries.get(record.skill_id, {})
                conn.execute(
                    "INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.skill_id,
                        record.name,
                        record.description,
                        record.body,
                        record.path,
                        record.sha256,
                        record.line_count,
                        json.dumps(record.metadata, sort_keys=True, ensure_ascii=False),
                        entry.get("domain") if isinstance(entry.get("domain"), str) else None,
                        float(entry.get("confidence", 1.0)),
                    ),
                )
                for tag in record.tags:
                    conn.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?)", (tag,))
                    conn.execute("INSERT INTO skill_tags(skill_id, tag) VALUES (?, ?)", (record.skill_id, tag))
                if fts_enabled:
                    conn.execute(
                        "INSERT INTO skills_fts(skill_id, name, description, tags, body) VALUES (?, ?, ?, ?, ?)",
                        (record.skill_id, record.name, record.description, " ".join(record.tags), record.body),
                    )
            for edge in edges:
                conn.execute("INSERT INTO edges VALUES (?, ?, ?, ?, ?)", (edge["source"], edge["target"], edge["type"], edge["weight"], edge["note"]))
            metadata = {
                "schema_version": "1",
                "source_root": str(root),
                "manifest_sha256": manifest_sha256,
                "indexed_at": utc_now(),
                "skill_count": str(len(records)),
                "edge_count": str(len(edges)),
                "fts5": "1" if fts_enabled else "0",
            }
            conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", metadata.items())
        conn.close()
        conn = None
        os.replace(temp_path, db)
        temp_path = None
        return {
            "ok": True,
            "indexed": True,
            "database": str(db.resolve()),
            "skills": len(records),
            "edges": len(edges),
            "warnings": [i.as_dict() for i in issues],
            "fts5": fts_enabled,
        }
    except (OSError, sqlite3.Error) as exc:
        fail(f"index failed without committing: {exc}")
    finally:
        if conn is not None:
            conn.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _record_from_index_row(row: sqlite3.Row) -> SkillRecord:
    return SkillRecord(
        skill_id=row["skill_id"],
        name=row["name"],
        description=row["description"],
        body=row["body"],
        path=row["path"],
        sha256=row["sha256"],
        line_count=row["line_count"],
        metadata=json.loads(row["metadata_json"]),
        tags=tuple(row["tags"].split(" ") if row["tags"] else ()),
    )


def refresh_index_incremental(root: Path, db: Path, manifest_path: Path | None, strict: bool) -> dict[str, Any]:
    """Refresh a valid snapshot by reusing rows whose content hashes match."""
    root = root.resolve()
    if not root.is_dir():
        raise SkillError(f"skill root is not a directory: {root}")
    if not db.is_file():
        raise SkillError(f"index database does not exist: {db}; run a full index first")
    try:
        manifest = load_manifest(manifest_path)
    except SkillError:
        raise
    old_conn = connect(str(db))
    try:
        old_meta = {row["key"]: row["value"] for row in old_conn.execute("SELECT key, value FROM meta")}
        old_rows = {row["skill_id"]: row for row in old_conn.execute(
            "SELECT s.*, COALESCE((SELECT group_concat(tag, ' ') FROM skill_tags st WHERE st.skill_id=s.skill_id), '') AS tags FROM skills s"
        )}
        old_by_path = {row["path"]: row for row in old_rows.values()}
    except sqlite3.Error as exc:
        raise SkillError(f"cannot read existing index: {exc}") from exc
    finally:
        old_conn.close()
    current_paths = discover_skills(root)
    current_hashes: dict[str, tuple[Path, str]] = {}
    records: list[SkillRecord] = []
    issues: list[Issue] = []
    reparsed: list[SkillRecord] = []
    for path in current_paths:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            current_hashes[path.relative_to(root).as_posix()] = (path, digest)
        except OSError as exc:
            issues.append(Issue("error", "read-error", path.as_posix(), str(exc)))
    seen: dict[str, str] = {}
    for relative, (path, digest) in sorted(current_hashes.items()):
        old = old_by_path.get(relative)
        if old is not None and old["sha256"] == digest:
            record = _record_from_index_row(old)
        else:
            try:
                record = parse_skill(path, root)
            except (OSError, SkillError) as exc:
                issues.append(Issue("error", "parse-error", relative, str(exc)))
                continue
            issues.extend(validate_skill(record, path))
            reparsed.append(record)
        if record.skill_id in seen:
            issues.append(Issue("error", "duplicate-name", record.path, f"name duplicates {seen[record.skill_id]}"))
        seen[record.skill_id] = record.path
        records.append(record)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors or (strict and any(issue.severity == "warning" for issue in issues)):
        return {"ok": False, "indexed": False, "issues": [issue.as_dict() for issue in issues]}
    try:
        edges, manifest_issues = normalize_edges(records, manifest)
    except SkillError as exc:
        raise exc
    issues.extend(manifest_issues)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        return {"ok": False, "indexed": False, "issues": [issue.as_dict() for issue in issues]}
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path is not None else ""
    old_ids = set(old_rows)
    new_ids = {record.skill_id for record in records}
    deleted = sorted(old_ids - new_ids)
    added = sorted(new_ids - old_ids)
    changed = sorted(record.skill_id for record in reparsed if record.skill_id in old_ids)
    unchanged = len(new_ids) - len(added) - len(changed)
    manifest_entries = {entry["id"]: entry for entry in manifest.get("skills", []) if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
    temp_path: Path | None = None
    conn: sqlite3.Connection | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{db.name}.", suffix=".tmp", dir=db.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        shutil.copy2(db, temp_path)
        conn = connect(str(temp_path))
        conn.execute("PRAGMA journal_mode = DELETE")
        fts_enabled = conn.execute("SELECT value FROM meta WHERE key='fts5'").fetchone()
        fts_enabled = fts_enabled is not None and fts_enabled[0] == "1"
        with conn:
            for skill_id in deleted:
                if fts_enabled:
                    conn.execute("DELETE FROM skills_fts WHERE skill_id=?", (skill_id,))
                conn.execute("DELETE FROM skills WHERE skill_id=?", (skill_id,))
            for record in records:
                entry = manifest_entries.get(record.skill_id, {})
                desired = (record.skill_id, record.name, record.description, record.body, record.path, record.sha256, record.line_count, json.dumps(record.metadata, sort_keys=True, ensure_ascii=False), entry.get("domain") if isinstance(entry.get("domain"), str) else None, float(entry.get("confidence", 1.0)))
                old = old_rows.get(record.skill_id)
                if old is not None and tuple(old[key] for key in ("skill_id", "name", "description", "body", "path", "sha256", "line_count", "metadata_json", "domain", "confidence")) == desired:
                    continue
                if fts_enabled:
                    conn.execute("DELETE FROM skills_fts WHERE skill_id=?", (record.skill_id,))
                conn.execute("DELETE FROM skill_tags WHERE skill_id=?", (record.skill_id,))
                conn.execute("DELETE FROM skills WHERE skill_id=?", (record.skill_id,))
                conn.execute("INSERT INTO skills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", desired)
                for tag in record.tags:
                    conn.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?)", (tag,))
                    conn.execute("INSERT INTO skill_tags(skill_id, tag) VALUES (?, ?)", (record.skill_id, tag))
                if fts_enabled:
                    conn.execute("INSERT INTO skills_fts(skill_id, name, description, tags, body) VALUES (?, ?, ?, ?, ?)", (record.skill_id, record.name, record.description, " ".join(record.tags), record.body))
            conn.execute("DELETE FROM tags WHERE NOT EXISTS (SELECT 1 FROM skill_tags WHERE skill_tags.tag=tags.tag)")
            conn.execute("DELETE FROM edges")
            for edge in edges:
                conn.execute("INSERT INTO edges VALUES (?, ?, ?, ?, ?)", (edge["source"], edge["target"], edge["type"], edge["weight"], edge["note"]))
            metadata = {"schema_version": "1", "source_root": str(root), "manifest_sha256": manifest_sha256, "indexed_at": utc_now(), "skill_count": str(len(records)), "edge_count": str(len(edges)), "fts5": "1" if fts_enabled else "0"}
            for key, value in metadata.items():
                conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.close()
        conn = None
        os.replace(temp_path, db)
        temp_path = None
        return {"ok": True, "indexed": True, "incremental": True, "database": str(db.resolve()), "skills": len(records), "edges": len(edges), "added": added, "changed": changed, "deleted": deleted, "unchanged": unchanged, "reparsed": len(reparsed), "warnings": [i.as_dict() for i in issues], "fts5": fts_enabled}
    except (OSError, sqlite3.Error) as exc:
        raise SkillError(f"incremental index failed without committing: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def query_tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1 and token.lower() not in QUERY_STOPWORDS]


def fts_query(text: str) -> str:
    tokens = query_tokens(text)
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:24])


def _negative_evidence(row: dict[str, Any], text: str) -> dict[str, Any]:
    """Return auditable positive-evidence signals for a lexical candidate."""
    query = set(query_tokens(text))
    raw_query = {token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1}
    name = str(row.get("name", "")).lower()
    skill_id = str(row.get("skill_id", "")).lower()
    searchable = f"{row.get('name', '')} {row.get('description', '')} {row.get('body', '')} {row.get('_body', '')}".lower()
    matched = {token for token in query if token in searchable}
    evidence = {token for token in matched if token not in NEGATIVE_EVIDENCE_STOPWORDS}
    actions = raw_query & POSITIVE_ACTION_TOKENS
    normalized_text = " ".join(TOKEN_RE.findall(text)).lower()
    explicitly_named = bool(name and name in normalized_text) or bool(skill_id and skill_id in normalized_text)
    passed = explicitly_named or bool(actions and evidence) or bool(evidence & POSITIVE_CONTENT_ANCHORS and len(evidence) >= 2)
    return {
        "passed": passed,
        "explicitly_named": explicitly_named,
        "matched_tokens": sorted(matched),
        "positive_evidence_tokens": sorted(evidence),
        "action_tokens": sorted(actions),
    }


def _apply_negative_evidence(rows: list[dict[str, Any]], text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    rejected = 0
    for source_row in rows:
        row = dict(source_row)
        evidence = _negative_evidence(row, text)
        row["negative_evidence"] = evidence
        if evidence["passed"]:
            kept.append(row)
        else:
            rejected += 1
    return kept, {
        "enabled": True,
        "passed": bool(kept),
        "candidates_examined": len(rows),
        "candidates_passed": len(kept),
        "candidates_rejected": rejected,
        "reason": "negative_evidence_gate" if rows and not kept else None,
    }


def query_index(
    db: Path,
    text: str,
    tag: str | None,
    domain: str | None,
    min_confidence: float,
    limit: int,
    explain: bool,
    min_coverage: int = 1,
) -> dict[str, Any]:
    if not db.is_file():
        fail(f"index database does not exist: {db}")
    conn = connect(str(db))
    try:
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
        if meta.get("fts5") != "1":
            return fallback_query(conn, text, tag, domain, min_confidence, limit, explain, min_coverage)
        query = fts_query(text)
        if not query:
            return {"ok": True, "results": [], "ranking": "empty query", "fts5": False, "negative_evidence_gate": {"enabled": True, "passed": False, "candidates_examined": 0, "candidates_passed": 0, "candidates_rejected": 0, "reason": None}}
        sql = [
            "SELECT s.skill_id, s.name, s.description, s.path, s.domain, s.confidence, s.body AS _body,",
            "bm25(skills_fts, 0.0, 8.0, 4.0, 5.0, 1.0) AS rank",
            "FROM skills_fts JOIN skills s ON s.skill_id = skills_fts.skill_id",
            "WHERE skills_fts MATCH ?",
        ]
        params: list[Any] = [query]
        filters = []
        if tag:
            filters.append("EXISTS (SELECT 1 FROM skill_tags st WHERE st.skill_id=s.skill_id AND st.tag=?)")
            params.append(tag.lower().lstrip("#"))
        if domain:
            filters.append("s.domain=?")
            params.append(domain.lower())
        filters.append("s.confidence>=?")
        params.append(min_confidence)
        if filters:
            sql.append("AND " + " AND ".join(filters))
        sql.append("ORDER BY rank LIMIT ?")
        params.append(max(limit * 20, 50))
        candidates = [dict(row) for row in conn.execute(" ".join(sql), params)]
        rows, gate = _apply_negative_evidence(candidates, text)
        rows = apply_coverage(rows, text, min_coverage)[:limit]
        return {"ok": True, "results": rows, "ranking": "sqlite fts5 bm25 + coverage + negative evidence", "fts5": True, "explain": explain, "min_coverage": min_coverage, "negative_evidence_gate": gate}
    except sqlite3.Error as exc:
        fail(f"query failed: {exc}")
    finally:
        conn.close()


def apply_coverage(rows: Iterable[dict[str, Any]], text: str, min_coverage: int) -> list[dict[str, Any]]:
    query_set = set(query_tokens(text))
    accepted: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        body = row.pop("body", "") or row.pop("_body", "")
        searchable = f"{row.get('name', '')} {row.get('description', '')} {body}".lower()
        content_tokens = set(query_tokens(searchable))
        row["match_coverage"] = len(query_set & content_tokens)
        if min_coverage <= 1 or row["match_coverage"] >= min_coverage or row.get("name", "").lower() in query_set:
            accepted.append(row)
    return accepted


def fallback_query(
    conn: sqlite3.Connection,
    text: str,
    tag: str | None,
    domain: str | None,
    min_confidence: float,
    limit: int,
    explain: bool,
    min_coverage: int = 1,
) -> dict[str, Any]:
    tokens = query_tokens(text)
    if not tokens:
        return {"ok": True, "results": [], "ranking": "empty query", "fts5": False, "negative_evidence_gate": {"enabled": True, "passed": False, "candidates_examined": 0, "candidates_passed": 0, "candidates_rejected": 0, "reason": None}}
    clauses = ["s.confidence>=?"]
    params: list[Any] = [min_confidence]
    for token in tokens[:24]:
        clauses.append("(lower(s.name) LIKE ? OR lower(s.description) LIKE ?)")
        params.extend([f"%{token}%", f"%{token}%"])
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM skill_tags st WHERE st.skill_id=s.skill_id AND st.tag=?)")
        params.append(tag.lower().lstrip("#"))
    if domain:
        clauses.append("s.domain=?")
        params.append(domain.lower())
    rows = []
    for row in conn.execute("SELECT s.* FROM skills s WHERE " + " AND ".join(clauses), params):
        item = dict(row)
        haystack = f"{item['name']} {item['description']} {item['body']}".lower()
        score = sum((5 if token in item["name"].lower() else 2 if token in item["description"].lower() else 1) for token in tokens if token in haystack)
        item["rank"] = -score
        rows.append(item)
    rows.sort(key=lambda item: (-item["rank"], item["skill_id"]))
    rows, gate = _apply_negative_evidence(rows, text)
    rows = apply_coverage(rows, text, min_coverage)[:limit]
    return {"ok": True, "results": rows, "ranking": "fallback token overlap + coverage + negative evidence", "fts5": False, "explain": explain, "min_coverage": min_coverage, "negative_evidence_gate": gate}


def route(
    db: Path,
    text: str,
    tag: str | None,
    domain: str | None,
    min_confidence: float,
    limit: int,
    min_coverage: int,
    calibration_policy_artifact: Path | None = None,
) -> dict[str, Any]:
    """Select one lead and bounded graph roles without loading a catalog.

    When an artifact is supplied, only its explicitly active version may apply
    abstention; candidate, approved-only, and rolled-back versions are ignored.
    """
    candidates = query_index(db, text, tag, domain, min_confidence, max(limit, 5), True, min_coverage)
    if not candidates["results"]:
        result = {"ok": True, "lead": None, "support": [], "validator": None, "fallback": None, "ranking": candidates["ranking"], "negative_evidence_gate": candidates.get("negative_evidence_gate")}
        gate = candidates.get("negative_evidence_gate") or {}
        if gate.get("reason") == "negative_evidence_gate" or (not candidates["results"] and gate.get("candidates_examined", 0) == 0):
            result = {**result, "abstained": True, "abstention_reason": "negative_evidence_gate" if gate.get("candidates_examined", 0) else "no_candidate"}
        if calibration_policy_artifact is not None:
            artifact = _read_policy_artifact(calibration_policy_artifact)
            if artifact.get("active_version") is None:
                raise SkillError("calibration policy artifact has no active version")
            result = {**result, "abstained": True, "abstention_reason": "no_candidate"}
            result["calibration_policy"] = {"artifact": str(calibration_policy_artifact), "version": artifact["active_version"], "abstention_enabled": False}
        return result
    lead = candidates["results"][0]
    conn = connect(str(db))
    try:
        rows = conn.execute(
            "SELECT source, target, type, weight, note FROM edges WHERE source=? ORDER BY type, weight DESC, target",
            (lead["skill_id"],),
        ).fetchall()
        by_id = {row["skill_id"]: row for row in candidates["results"]}
        for row in conn.execute(
            "SELECT skill_id, name, description, path, domain, confidence FROM skills WHERE skill_id=? OR skill_id IN (SELECT target FROM edges WHERE source=?)",
            (lead["skill_id"], lead["skill_id"]),
        ):
            by_id.setdefault(row["skill_id"], dict(row))
        for edge in rows:
            by_id.setdefault(edge["target"], {"skill_id": edge["target"]})
        summaries = {
            skill_id: {
                key: value
                for key, value in item.items()
                if key in {"skill_id", "name", "description", "path", "domain", "confidence", "match_coverage"}
            }
            for skill_id, item in by_id.items()
        }
        support: list[dict[str, Any]] = []
        validator = None
        fallback = None
        for edge in rows:
            target = summaries.get(edge["target"], {"skill_id": edge["target"]})
            item = {**target, "relation": edge["type"], "relation_weight": edge["weight"], "note": edge["note"]}
            if edge["type"] in {"composes", "requires", "parent"} and len(support) < 3:
                support.append(item)
            elif edge["type"] == "validates" and validator is None:
                validator = item
            elif edge["type"] in {"alternative-to", "supersedes"} and fallback is None:
                fallback = item
        result = {
            "ok": True,
            "lead": lead,
            "support": support,
            "validator": validator,
            "fallback": fallback,
            "ranking": candidates["ranking"],
            "negative_evidence_gate": candidates.get("negative_evidence_gate"),
            "limits": {"lead": 1, "support": 3, "validator": 1, "fallback": 1},
        }
        if calibration_policy_artifact is not None:
            artifact = _read_policy_artifact(calibration_policy_artifact)
            if artifact.get("active_version") is None:
                raise SkillError("calibration policy artifact has no active version")
            active = _policy_version(artifact, artifact["active_version"])
            by_skill = active["policy"].get("by_skill", {})
            by_domain = active["policy"].get("by_domain", {})
            domain_policy = by_domain.get(lead.get("domain"), active["policy"]["global"])
            policy = by_skill.get(lead["skill_id"], domain_policy)
            threshold = policy.get("threshold") if policy.get("eligible") else None
            result = _apply_abstention(result, policy, threshold)
            result["calibration_policy"] = {
                "artifact": str(calibration_policy_artifact),
                "version": active["version"],
                "abstention_enabled": threshold is not None,
                "threshold": threshold,
                "scope": "skill" if lead["skill_id"] in by_skill else "domain" if lead.get("domain") in by_domain else "global",
            }
        return result
    except sqlite3.Error as exc:
        fail(f"route failed: {exc}")
    finally:
        conn.close()


def route_and_journal(
    db: Path,
    text: str,
    tag: str | None,
    domain: str | None,
    min_confidence: float,
    limit: int,
    min_coverage: int,
    journal_path: Path | None = None,
    journal_opt_in: bool = False,
    privacy_reviewed: bool = False,
    store_task_content: bool = False,
    redaction_keys: set[str] | None = None,
    calibration_policy_artifact: Path | None = None,
) -> dict[str, Any]:
    """Route normally, optionally append a minimized decision event.

    Task content is never stored unless all three explicit choices are made:
    journal opt-in, privacy review, and task-content storage. The default path
    performs no journal access and returns the ordinary route result.
    """
    if journal_path is None and (journal_opt_in or privacy_reviewed or store_task_content):
        raise SkillError("journal flags require --journal JOURNAL")
    if journal_path is not None and not journal_opt_in:
        raise SkillError("automatic route journaling requires --journal-opt-in")
    if store_task_content and not privacy_reviewed:
        raise SkillError("storing task content requires --privacy-reviewed")
    result = route(db, text, tag, domain, min_confidence, limit, min_coverage, calibration_policy_artifact)
    if journal_path is None:
        return {**result, "journal": {"stored": False, "reason": "automatic journaling not requested"}}
    lead = result.get("lead")
    def compact(value: Any, role: str, relation: str | None = None) -> dict[str, Any] | None:
        if not isinstance(value, dict) or not isinstance(value.get("skill_id"), str):
            return None
        item = {"skill_id": value["skill_id"], "role": role, "confidence": value.get("confidence"), "match_coverage": value.get("match_coverage")}
        if relation is not None:
            item["relation"] = relation
        return item
    route_record: dict[str, Any] = {
        "lead": compact(lead, "lead"),
        "calibration_policy": result.get("calibration_policy"),
        "support": [item for item in (compact(value, "support", value.get("relation")) for value in result.get("support", [])) if item],
        "validator": compact(result.get("validator"), "validator", result.get("validator", {}).get("relation") if isinstance(result.get("validator"), dict) else None),
        "fallback": compact(result.get("fallback"), "fallback", result.get("fallback", {}).get("relation") if isinstance(result.get("fallback"), dict) else None),            "ranking": result.get("ranking"),
            "negative_evidence_gate": result.get("negative_evidence_gate"),
        }
    payload: dict[str, Any] = {
        "query_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "query_length": len(text),
        "route": route_record,
        "task_content": "[WITHHELD]" if not store_task_content else text,
    }
    provenance = {
        "source": "route-command",
        "index": str(db.resolve()),
        "privacy": {
            "opt_in": True,
            "privacy_reviewed": privacy_reviewed,
            "task_content_requested": store_task_content,
            "task_content_stored": store_task_content,
        },
    }
    event = append_journal_event(journal_path, "decision", payload, None, provenance, redaction_keys or set())
    return {
        **result,
        "journal": {
            "stored": True,
            "event_id": event["event_id"],
            "task_content_stored": bool(store_task_content),
            "task_content_withheld": not store_task_content,
            "task_content_sha256": payload["query_sha256"],
            "redactions": event.get("redactions", []),
            "privacy_reviewed": privacy_reviewed,
        },
    }


def neighbors(db: Path, skill_id: str, depth: int, relation: str | None) -> dict[str, Any]:
    if not db.is_file():
        fail(f"index database does not exist: {db}")
    conn = connect(str(db))
    try:
        if conn.execute("SELECT 1 FROM skills WHERE skill_id=?", (skill_id,)).fetchone() is None:
            fail(f"unknown skill id: {skill_id}")
        rows = conn.execute(
            """
            WITH RECURSIVE reachable(node, depth, path) AS (
                SELECT ?, 0, ',' || ? || ','
                UNION
                SELECT CASE WHEN e.source=reachable.node THEN e.target ELSE e.source END,
                       reachable.depth+1,
                       reachable.path || (CASE WHEN e.source=reachable.node THEN e.target ELSE e.source END) || ','
                FROM reachable
                JOIN edges e ON e.source=reachable.node OR e.target=reachable.node
                WHERE reachable.depth < ?
                  AND instr(reachable.path, ',' || (CASE WHEN e.source=reachable.node THEN e.target ELSE e.source END) || ',')=0
                  AND (? IS NULL OR e.type=?)
            )
            SELECT e.source, e.target, e.type, e.weight, e.note, MIN(reachable.depth) AS depth
            FROM reachable JOIN edges e
              ON (e.source=reachable.node AND e.target<>reachable.node)
              OR (e.target=reachable.node AND e.source<>reachable.node)
            WHERE reachable.depth>0
            GROUP BY e.source, e.target, e.type, e.weight, e.note
            ORDER BY depth, e.type, e.source, e.target
            """,
            (skill_id, skill_id, depth, relation, relation),
        )
        return {"ok": True, "skill_id": skill_id, "depth": depth, "edges": [dict(row) for row in rows]}
    except sqlite3.Error as exc:
        fail(f"neighbor query failed: {exc}")
    finally:
        conn.close()


def stats(db: Path) -> dict[str, Any]:
    if not db.is_file():
        fail(f"index database does not exist: {db}")
    conn = connect(str(db))
    try:
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
        counts = {
            "skills": conn.execute("SELECT count(*) FROM skills").fetchone()[0],
            "tags": conn.execute("SELECT count(*) FROM tags").fetchone()[0],
            "edges": conn.execute("SELECT count(*) FROM edges").fetchone()[0],
        }
        return {"ok": True, "meta": meta, "counts": counts}
    except sqlite3.Error as exc:
        fail(f"stats failed: {exc}")
    finally:
        conn.close()


def validate_command(root: Path, strict: bool) -> int:
    if not root.is_dir():
        fail(f"skill root is not a directory: {root}")
    records, issues = load_records(root.resolve())
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    result = {
        "ok": not errors and (not strict or not warnings),
        "root": str(root.resolve()),
        "skills": len(records),
        "errors": [i.as_dict() for i in errors],
        "warnings": [i.as_dict() for i in warnings],
    }
    emit(result)
    return 0 if result["ok"] else 1


def check_index(db: Path, root: Path, manifest_path: Path | None) -> dict[str, Any]:
    if not db.is_file():
        fail(f"index database does not exist: {db}")
    if not root.is_dir():
        fail(f"skill root is not a directory: {root}")
    conn = connect(str(db))
    try:
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
        indexed_rows = {row["skill_id"]: dict(row) for row in conn.execute("SELECT skill_id, path, sha256 FROM skills")}
    except sqlite3.Error as exc:
        fail(f"check failed: {exc}")
    finally:
        conn.close()
    records, issues = load_records(root.resolve())
    current_rows = {record.skill_id: {"skill_id": record.skill_id, "path": record.path, "sha256": record.sha256} for record in records}
    changed = sorted(
        skill_id
        for skill_id in set(indexed_rows) | set(current_rows)
        if indexed_rows.get(skill_id) != current_rows.get(skill_id)
    )
    manifest_changed = False
    manifest_hash = None
    if manifest_path is not None:
        if not manifest_path.is_file():
            fail(f"manifest does not exist: {manifest_path}")
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        manifest_changed = manifest_hash != meta.get("manifest_sha256", "")
    stale = bool(
        issues
        or meta.get("source_root") != str(root.resolve())
        or meta.get("skill_count") != str(len(current_rows))
        or changed
        or manifest_changed
    )
    return {
        "ok": not stale,
        "stale": stale,
        "indexed_at": meta.get("indexed_at"),
        "source_root": meta.get("source_root"),
        "manifest_checked": manifest_path is not None,
        "manifest_changed": manifest_changed,
        "changed_skills": changed,
        "validation_issues": [issue.as_dict() for issue in issues],
    }


def evaluate_index(db: Path, cases_path: Path, limit: int) -> dict[str, Any]:
    if not cases_path.is_file():
        fail(f"evaluation cases do not exist: {cases_path}")
    try:
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read evaluation cases: {exc}")
    if not isinstance(cases, list):
        fail("evaluation cases must be a JSON array")
    results: list[dict[str, Any]] = []
    for position, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("query"), str):
            fail(f"evaluation case {position} requires a query string")
        expected = set(case.get("expected", []))
        forbidden = set(case.get("forbidden", []))
        query = query_index(
            db,
            case["query"],
            case.get("tag"),
            case.get("domain"),
            float(case.get("min_confidence", 0.0)),
            limit,
            False,
            int(case.get("min_coverage", 2)),
        )
        returned = [row["skill_id"] for row in query["results"]]
        selected = returned[:1]
        relevant_ranks = [rank for rank, skill_id in enumerate(returned, start=1) if skill_id in expected]
        first_rank = relevant_ranks[0] if relevant_ranks else None
        forbidden_hits = sorted(set(selected) & forbidden)
        results.append({
            "id": case.get("id", f"case-{position + 1}"),
            "query": case["query"],
            "expected": sorted(expected),
            "returned": returned,
            "selected": selected,
            "first_relevant_rank": first_rank,
            "top3_hit": bool(relevant_ranks and first_rank <= 3),
            "forbidden_hits": forbidden_hits,
            "no_trigger_false_activation": not expected and bool(selected),
        })
    positive = [row for row in results if row["expected"]]
    negative = [row for row in results if not row["expected"]]
    forbidden_rate = round(sum(bool(row["forbidden_hits"]) for row in results) / len(results), 4) if results else None
    no_trigger_rate = round(sum(row["no_trigger_false_activation"] for row in negative) / len(negative), 4) if negative else None
    passed = forbidden_rate == 0 and (no_trigger_rate is None or no_trigger_rate == 0)
    return {
        "ok": True,
        "passed": passed,
        "cases": len(results),
        "metrics": {
            "expected_cases": len(positive),
            "hit_rate": round(sum(row["first_relevant_rank"] is not None for row in positive) / len(positive), 4) if positive else None,
            "mrr": round(sum(1 / row["first_relevant_rank"] for row in positive if row["first_relevant_rank"]), 4) / len(positive) if positive else None,
            "top3_rate": round(sum(row["top3_hit"] for row in positive) / len(positive), 4) if positive else None,
            "forbidden_rate": forbidden_rate,
            "no_trigger_false_activation_rate": no_trigger_rate,
        },
        "results": results,
    }


def _domain_metrics(cases: list[dict[str, Any]], k: int) -> dict[str, Any]:
    if not cases:
        return {"cases": 0, "precision_at_k": None, "recall_at_k": None, "mrr": None, "map": None, "ndcg_at_k": None, "top1_accuracy": None, "abstention_accuracy": None, "false_activation_rate": None}
    precision_values: list[float] = []
    recall_values: list[float] = []
    reciprocal_ranks: list[float] = []
    average_precisions: list[float] = []
    ndcg_values: list[float] = []
    top1_correct = 0
    abstention_correct = 0
    false_activations = 0
    negative_cases = 0
    for case in cases:
        rankings = case["returned"]
        judgments = case["judgments"]
        relevant = {skill_id for skill_id, grade in judgments.items() if grade >= 2}
        positive = bool(relevant)
        if not positive:
            negative_cases += 1
        top = rankings[:k]
        hits = [skill_id in relevant for skill_id in top]
        precision = sum(hits) / k if k else 0.0
        recall = sum(hits) / len(relevant) if relevant else (1.0 if not top else 0.0)
        precision_values.append(precision)
        recall_values.append(recall)
        first = next((rank for rank, skill_id in enumerate(rankings, start=1) if skill_id in relevant), None)
        reciprocal_ranks.append(1.0 / first if first else 0.0)
        if rankings and rankings[0] in relevant:
            top1_correct += 1
        if not positive and not rankings:
            abstention_correct += 1
        if not positive and rankings:
            false_activations += 1
        if relevant:
            hits_so_far = 0
            precision_sum = 0.0
            for rank, skill_id in enumerate(rankings[:k], start=1):
                if skill_id in relevant:
                    hits_so_far += 1
                    precision_sum += hits_so_far / rank
            average_precisions.append(precision_sum / min(len(relevant), k))
        else:
            average_precisions.append(0.0)
        gains = [(2 ** judgments.get(skill_id, 0)) - 1 for skill_id in top]
        dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
        ideal_grades = sorted((grade for grade in judgments.values() if grade > 0), reverse=True)[:k]
        idcg = sum(((2 ** grade) - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades, start=1))
        ndcg_values.append(dcg / idcg if idcg else 0.0)
    return {
        "cases": len(cases),
        "positive_cases": len(cases) - negative_cases,
        "negative_cases": negative_cases,
        "precision_at_k": round(sum(precision_values) / len(precision_values), 4),
        "recall_at_k": round(sum(recall_values) / len(recall_values), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        "map": round(sum(average_precisions) / len(average_precisions), 4),
        "ndcg_at_k": round(sum(ndcg_values) / len(ndcg_values), 4),
        "top1_accuracy": round(top1_correct / len(cases), 4),
        "abstention_accuracy": round(abstention_correct / negative_cases, 4) if negative_cases else None,
        "false_activation_rate": round(false_activations / negative_cases, 4) if negative_cases else None,
    }


def _repeated_query_group_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        group_id = result.get("group_id")
        if isinstance(group_id, str) and group_id:
            grouped.setdefault(group_id, []).append(result)
    by_group: dict[str, Any] = {}
    repeated = 0
    consistent = 0
    for group_id, group in sorted(grouped.items()):
        top1_values = [item["returned"][0] if item["returned"] else None for item in group]
        relevant_sets = [tuple(item.get("relevant", [])) for item in group]
        is_repeated = len(group) > 1
        is_consistent = len(set(top1_values)) <= 1 and len(set(relevant_sets)) <= 1
        if is_repeated:
            repeated += 1
            consistent += int(is_consistent)
        by_group[group_id] = {
            "cases": len(group),
            "repeated": is_repeated,
            "top1_values": top1_values,
            "top1_consistent": len(set(top1_values)) <= 1,
            "relevance_sets_consistent": len(set(relevant_sets)) <= 1,
            "consistent": is_consistent,
            "false_activations": sum(item.get("false_activation", False) for item in group),
        }
    return {
        "groups": len(grouped),
        "repeated_groups": repeated,
        "consistent_groups": consistent,
        "consistency_rate": round(consistent / repeated, 4) if repeated else None,
        "by_group": by_group,
    }


def _false_activation_analysis(results: list[dict[str, Any]]) -> dict[str, Any]:
    negative = [item for item in results if not item.get("relevant")]
    false_activations = [item for item in negative if item.get("false_activation")]
    by_domain: dict[str, Any] = {}
    for domain in sorted({item["domain"] for item in negative}):
        domain_cases = [item for item in negative if item["domain"] == domain]
        by_domain[domain] = {
            "negative_cases": len(domain_cases),
            "false_activations": sum(item.get("false_activation", False) for item in domain_cases),
            "false_activation_rate": round(sum(item.get("false_activation", False) for item in domain_cases) / len(domain_cases), 4) if domain_cases else None,
        }
    by_group: dict[str, Any] = {}
    for group_id in sorted({item.get("group_id") for item in false_activations if isinstance(item.get("group_id"), str)}):
        group_cases = [item for item in false_activations if item.get("group_id") == group_id]
        by_group[group_id] = {"false_activations": len(group_cases), "case_ids": [item["id"] for item in group_cases]}
    return {
        "negative_cases": len(negative),
        "false_activations": len(false_activations),
        "false_activation_rate": round(len(false_activations) / len(negative), 4) if negative else None,
        "case_ids": [item["id"] for item in false_activations],
        "by_domain": by_domain,
        "by_group": by_group,
    }


def evaluate_domain_bench(db: Path, cases_path: Path, limit: int, k: int) -> dict[str, Any]:
    if not db.is_file():
        raise SkillError(f"index database does not exist: {db}")
    if not cases_path.is_file():
        raise SkillError(f"domain benchmark does not exist: {cases_path}")
    try:
        document = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"cannot read domain benchmark: {exc}")
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("cases"), list):
        raise SkillError("domain benchmark requires schema_version 1 and a cases array")
    if not 1 <= k <= limit <= 100:
        raise SkillError("ranking requires 1 <= k <= limit <= 100")
    conn = connect(str(db))
    try:
        known_skills = {row["skill_id"] for row in conn.execute("SELECT skill_id FROM skills")}
    finally:
        conn.close()
    results: list[dict[str, Any]] = []
    for position, case in enumerate(document["cases"]):
        if not isinstance(case, dict) or not isinstance(case.get("query"), str) or not isinstance(case.get("domain"), str):
            raise SkillError(f"domain case {position} requires query and domain")
        if case.get("group_id") is not None and (not isinstance(case.get("group_id"), str) or not case["group_id"].strip()):
            raise SkillError(f"domain case {position} group_id must be a non-empty string when provided")
        if case.get("split") != "heldout":
            raise SkillError(f"domain case {position} must use split=heldout")
        raw_judgments = case.get("judgments")
        if not isinstance(raw_judgments, dict) or not raw_judgments:
            raise SkillError(f"domain case {position} requires a non-empty judgments object")
        judgments: dict[str, int] = {}
        for skill_id, grade in raw_judgments.items():
            if not isinstance(skill_id, str) or skill_id not in known_skills:
                raise SkillError(f"domain case {position} judges unknown skill {skill_id!r}")
            if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
                raise SkillError(f"domain case {position} relevance grades must be integers from 0 to 3")
            judgments[skill_id] = grade
        query = query_index(db, case["query"], case.get("tag"), None, float(case.get("min_confidence", 0.0)), limit, False, int(case.get("min_coverage", 1)))
        returned = [row["skill_id"] for row in query["results"]]
        results.append({
            "id": case.get("id", f"domain-case-{position + 1}"),
            "group_id": case.get("group_id"),
            "domain": case["domain"],
            "query": case["query"],
            "split": "heldout",
            "judgments": judgments,
            "relevant": sorted(skill_id for skill_id, grade in judgments.items() if grade >= 2),
            "returned": returned,
            "false_activation": not any(grade >= 2 for grade in judgments.values()) and bool(returned),
            "k": k,
        })
    domain_groups: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        domain_groups.setdefault(result["domain"], []).append(result)
    return {
        "ok": True,
        "benchmark": "heldout-domain-relevance",
        "schema_version": 1,
        "cases": len(results),
        "k": k,
        "relevance_scale": {"0": "irrelevant", "1": "related", "2": "relevant", "3": "highly relevant"},
        "metrics": _domain_metrics(results, k),
        "by_domain": {domain: _domain_metrics(group, k) for domain, group in sorted(domain_groups.items())},
        "repeated_query_groups": _repeated_query_group_metrics(results),
        "false_activation_analysis": _false_activation_analysis(results),
        "results": results,
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def redact_value(value: Any, extra_keys: set[str] | None = None, path: str = "$") -> tuple[Any, list[str]]:
    """Return a recursively redacted JSON value and the paths changed."""
    extra_keys = {key.lower().replace("-", "_") for key in (extra_keys or set())}
    changed: list[str] = []
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            child_path = f"{path}.{key}"
            if normalized in JOURNAL_SECRET_KEYS or normalized in extra_keys:
                result[key] = "[REDACTED]"
                changed.append(child_path)
            else:
                result[key], child_changed = redact_value(child, extra_keys, child_path)
                changed.extend(child_changed)
        return result, changed
    if isinstance(value, list):
        result_list: list[Any] = []
        for position, child in enumerate(value):
            child_value, child_changed = redact_value(child, extra_keys, f"{path}[{position}]")
            result_list.append(child_value)
            changed.extend(child_changed)
        return result_list, changed
    if isinstance(value, str):
        result_text = value
        for pattern, replacement in JOURNAL_SECRET_PATTERNS:
            result_text = pattern.sub(replacement, result_text)
        if result_text != value:
            changed.append(path)
        return result_text, changed
    return value, changed


def connect_journal(path: Path) -> sqlite3.Connection:
    conn = connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def create_journal_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS journal_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journal_events (
            sequence INTEGER PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('decision', 'outcome', 'note')),
            parent_event_id TEXT REFERENCES journal_events(event_id),
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            redactions_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_journal_parent ON journal_events(parent_event_id, sequence);
        CREATE TRIGGER IF NOT EXISTS journal_events_no_update
            BEFORE UPDATE ON journal_events
            BEGIN SELECT RAISE(ABORT, 'journal events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS journal_events_no_delete
            BEFORE DELETE ON journal_events
            BEGIN SELECT RAISE(ABORT, 'journal events are append-only'); END;
        """
    )
    current = conn.execute("SELECT value FROM journal_meta WHERE key='schema_version'").fetchone()
    if current is not None and current[0] != JOURNAL_SCHEMA_VERSION:
        raise SkillError(f"unsupported journal schema version: {current[0]}")
    conn.execute("INSERT OR IGNORE INTO journal_meta(key, value) VALUES ('schema_version', ?)", (JOURNAL_SCHEMA_VERSION,))
    conn.execute("INSERT OR IGNORE INTO journal_meta(key, value) VALUES ('redaction_version', ?)", (JOURNAL_REDACTION_VERSION,))


def journal_event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "sequence": row["sequence"],
        "event_id": row["event_id"],
        "kind": row["kind"],
        "parent_event_id": row["parent_event_id"],
        "created_at": row["created_at"],
        "payload": json.loads(row["payload_json"]),
        "provenance": json.loads(row["provenance_json"]),
        "redactions": json.loads(row["redactions_json"]),
        "payload_sha256": row["payload_sha256"],
        "previous_hash": row["previous_hash"],
        "event_hash": row["event_hash"],
    }


def verify_journal_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    previous_hash = "0" * 64
    expected_sequence = 1
    for row in conn.execute("SELECT * FROM journal_events ORDER BY sequence"):
        event = journal_event_from_row(row)
        if event["sequence"] != expected_sequence:
            raise SkillError(f"journal sequence gap at {event['sequence']}")
        if event["previous_hash"] != previous_hash:
            raise SkillError(f"journal chain break at sequence {event['sequence']}")
        unsigned = {key: value for key, value in event.items() if key != "event_hash"}
        expected_hash = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
        if event["event_hash"] != expected_hash:
            raise SkillError(f"journal event hash mismatch at sequence {event['sequence']}")
        if hashlib.sha256(canonical_json(event["payload"]).encode("utf-8")).hexdigest() != event["payload_sha256"]:
            raise SkillError(f"journal payload hash mismatch at sequence {event['sequence']}")
        previous_hash = event["event_hash"]
        expected_sequence += 1
    return {"ok": True, "events": expected_sequence - 1, "head_hash": previous_hash}


def journal_init(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_journal(path)
    try:
        with conn:
            create_journal_schema(conn)
        return {"ok": True, "journal": str(path.resolve()), **verify_journal_chain(conn)}
    except sqlite3.Error as exc:
        fail(f"journal initialization failed without committing: {exc}")
    finally:
        conn.close()


def append_journal_event(
    path: Path,
    kind: str,
    payload: Any,
    parent_event_id: str | None,
    provenance: dict[str, Any],
    redaction_keys: set[str] | None = None,
) -> dict[str, Any]:
    if kind not in {"decision", "outcome", "note"}:
        raise SkillError("journal kind must be decision, outcome, or note")
    if kind == "outcome":
        if not isinstance(payload, dict) or payload.get("status") not in {"success", "partial", "failure", "abstain"}:
            raise SkillError("journal outcome payload requires status success, partial, failure, or abstain")
        if parent_event_id is None:
            raise SkillError("journal outcome requires --parent EVENT_ID")
    if not path.is_file():
        fail(f"journal does not exist: {path}; run journal-init first")
    safe_payload, payload_redactions = redact_value(payload, redaction_keys)
    safe_provenance, provenance_redactions = redact_value(provenance, redaction_keys)
    conn = connect_journal(path)
    try:
        with conn:
            create_journal_schema(conn)
            verify_journal_chain(conn)
            if parent_event_id is not None and conn.execute("SELECT 1 FROM journal_events WHERE event_id=?", (parent_event_id,)).fetchone() is None:
                raise SkillError(f"unknown parent event: {parent_event_id}")
            row = conn.execute("SELECT sequence, event_hash FROM journal_events ORDER BY sequence DESC LIMIT 1").fetchone()
            sequence = row["sequence"] + 1 if row else 1
            previous_hash = row["event_hash"] if row else "0" * 64
            event = {
                "sequence": sequence,
                "event_id": str(uuid.uuid4()),
                "kind": kind,
                "parent_event_id": parent_event_id,
                "created_at": utc_now(),
                "payload": safe_payload,
                "provenance": safe_provenance,
                "redactions": sorted(payload_redactions + provenance_redactions),
                "payload_sha256": hashlib.sha256(canonical_json(safe_payload).encode("utf-8")).hexdigest(),
                "previous_hash": previous_hash,
            }
            event["event_hash"] = hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO journal_events(sequence, event_id, kind, parent_event_id, created_at, payload_json, provenance_json, redactions_json, payload_sha256, previous_hash, event_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event["sequence"], event["event_id"], event["kind"], event["parent_event_id"], event["created_at"],
                    canonical_json(event["payload"]), canonical_json(event["provenance"]), canonical_json(event["redactions"]),
                    event["payload_sha256"], event["previous_hash"], event["event_hash"],
                ),
            )
        return {"ok": True, **event}
    except sqlite3.Error as exc:
        fail(f"journal append failed without committing: {exc}")
    finally:
        conn.close()


def journal_show(path: Path, limit: int) -> dict[str, Any]:
    if not path.is_file():
        fail(f"journal does not exist: {path}")
    conn = connect_journal(path)
    try:
        chain = verify_journal_chain(conn)
        rows = conn.execute("SELECT * FROM journal_events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return {"ok": True, **chain, "events": [journal_event_from_row(row) for row in rows]}
    except sqlite3.Error as exc:
        fail(f"journal read failed: {exc}")
    finally:
        conn.close()


def journal_verify(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"journal does not exist: {path}")
    conn = connect_journal(path)
    try:
        return {"ok": True, **verify_journal_chain(conn)}
    except sqlite3.Error as exc:
        fail(f"journal verification failed: {exc}")
    finally:
        conn.close()


def _route_attributions(payload: dict[str, Any]) -> list[dict[str, str]]:
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(value: Any, default_relation: str) -> None:
        if isinstance(value, str):
            skill_id, relation = value, default_relation
        elif isinstance(value, dict) and isinstance(value.get("skill_id"), str):
            skill_id = value["skill_id"]
            relation = value.get("relation", default_relation)
        else:
            return
        if not isinstance(relation, str) or not relation:
            relation = default_relation
        key = (skill_id, relation)
        if key not in seen:
            seen.add(key)
            result.append({"skill_id": skill_id, "relation": relation})

    add(route.get("lead"), route.get("lead_relation", "lead") if isinstance(route.get("lead_relation"), str) else "lead")
    if not route and not isinstance(payload.get("lead"), (str, dict)):
        add(payload.get("skill_id"), "lead")
    else:
        add(payload.get("lead"), "lead")
    for relation_key, default_relation in (("support", "support"), ("validator", "validates"), ("fallback", "fallback")):
        values = route.get(relation_key)
        if isinstance(values, list):
            for value in values:
                add(value, default_relation)
        else:
            add(values, default_relation)
    return result


def _empty_outcome_metrics() -> dict[str, Any]:
    counts = {status: 0 for status in sorted(CALIBRATION_OUTCOMES)}
    rates = {status: 0.0 for status in counts}
    return {"outcomes": 0, "counts": counts, "rates": rates, "success_rate": 0.0, "partial_rate": 0.0, "failure_rate": 0.0, "abstention_rate": 0.0}


def _add_outcome_metric(metrics: dict[str, Any], status: str) -> None:
    metrics["outcomes"] += 1
    metrics["counts"][status] += 1


def _finalize_outcome_metric(metrics: dict[str, Any]) -> dict[str, Any]:
    total = metrics["outcomes"]
    if total:
        metrics["rates"] = {status: round(metrics["counts"][status] / total, 4) for status in metrics["counts"]}
        metrics["success_rate"] = metrics["rates"]["success"]
        metrics["partial_rate"] = metrics["rates"]["partial"]
        metrics["failure_rate"] = metrics["rates"]["failure"]
        metrics["abstention_rate"] = metrics["rates"]["abstain"]
    return metrics


def journal_outcome_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SkillError(f"journal does not exist: {path}")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        chain = verify_journal_chain(conn)
        decisions = {
            row["event_id"]: journal_event_from_row(row)
            for row in conn.execute("SELECT * FROM journal_events WHERE kind='decision'")
        }
        by_skill: dict[str, dict[str, Any]] = {}
        by_relation: dict[str, dict[str, Any]] = {}
        by_skill_relation: dict[str, dict[str, Any]] = {}
        total = _empty_outcome_metrics()
        attributed = 0
        unlinked = 0
        for row in conn.execute("SELECT * FROM journal_events WHERE kind='outcome' ORDER BY sequence"):
            event = journal_event_from_row(row)
            status = event["payload"].get("status")
            if status not in CALIBRATION_OUTCOMES:
                continue
            decision = decisions.get(event["parent_event_id"])
            if decision is None:
                unlinked += 1
                continue
            attributions = _route_attributions(decision["payload"])
            if not attributions:
                unlinked += 1
                continue
            for attribution in attributions:
                skill = attribution["skill_id"]
                relation = attribution["relation"]
                skill_metrics = by_skill.setdefault(skill, _empty_outcome_metrics())
                relation_metrics = by_relation.setdefault(relation, _empty_outcome_metrics())
                pair_metrics = by_skill_relation.setdefault(f"{skill}\x1f{relation}", _empty_outcome_metrics())
                _add_outcome_metric(total, status)
                _add_outcome_metric(skill_metrics, status)
                _add_outcome_metric(relation_metrics, status)
                _add_outcome_metric(pair_metrics, status)
                pair_metrics["skill_id"] = skill
                pair_metrics["relation"] = relation
                attributed += 1
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "ok": True,
            "read_only": True,
            "journal": chain,
            "statuses": sorted(CALIBRATION_OUTCOMES),
            "total": _finalize_outcome_metric(total),
            "by_skill": {key: _finalize_outcome_metric(value) for key, value in sorted(by_skill.items())},
            "by_relation": {key: _finalize_outcome_metric(value) for key, value in sorted(by_relation.items())},
            "by_skill_relation": {key.replace("\x1f", "::"): _finalize_outcome_metric(value) for key, value in sorted(by_skill_relation.items())},
            "attributions": attributed,
            "unlinked_outcomes": unlinked,
            "artifacts_unchanged": before == after,
        }
    except sqlite3.Error as exc:
        raise SkillError(f"journal evaluation failed: {exc}") from exc
    finally:
        conn.close()


def wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = proportion + z * z / (2.0 * total)
    margin = z * math.sqrt((proportion * (1.0 - proportion) + z * z / (4.0 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _route_lead(payload: dict[str, Any]) -> tuple[str | None, float | None, str | None]:
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    lead = route.get("lead") if isinstance(route, dict) else None
    if lead is None:
        lead = payload.get("lead")
    if isinstance(lead, str):
        skill_id, confidence, domain = lead, route.get("confidence", payload.get("confidence")), route.get("domain", payload.get("domain"))
    elif isinstance(lead, dict):
        skill_id = lead.get("skill_id")
        confidence = lead.get("confidence", route.get("confidence", payload.get("confidence")))
        domain = lead.get("domain", route.get("domain", payload.get("domain")))
    else:
        skill_id, confidence, domain = payload.get("skill_id"), payload.get("confidence"), payload.get("domain")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        confidence = None
    else:
        confidence = float(confidence)
    return (skill_id if isinstance(skill_id, str) and skill_id else None, confidence, domain if isinstance(domain, str) and domain else None)


def _journal_route_observations(conn: sqlite3.Connection, cutoff: dt.datetime | None = None) -> list[dict[str, Any]]:
    decisions = {
        row["event_id"]: journal_event_from_row(row)
        for row in conn.execute("SELECT * FROM journal_events WHERE kind='decision'")
    }
    observations: list[dict[str, Any]] = []
    for row in conn.execute("SELECT * FROM journal_events WHERE kind='outcome' ORDER BY sequence"):
        event = journal_event_from_row(row)
        observed_at = _parse_observation_time(event.get("created_at"))
        if cutoff is not None and (observed_at is None or observed_at > cutoff):
            continue
        decision = decisions.get(event.get("parent_event_id"))
        if decision is None or event.get("payload", {}).get("status") not in CALIBRATION_OUTCOMES:
            continue
        skill_id, confidence, domain = _route_lead(decision.get("payload", {}))
        if skill_id is None or confidence is None:
            continue
        status = event["payload"]["status"]
        observations.append({
            "event_id": event["event_id"],
            "decision_event_id": decision["event_id"],
            "skill_id": skill_id,
            "confidence": confidence,
            "outcome": status,
            "outcome_score": {"success": 1.0, "partial": 0.5, "failure": 0.0, "abstain": 0.0}[status],
            "domain": domain or "unknown",
            "observed_at": event["created_at"],
        })
    return observations


def weekly_report_data(
    journal_path: Path,
    as_of: str | None = None,
    window_days: int = 7,
    minimum_samples: int = 5,
    drift_threshold: float = 0.15,
) -> dict[str, Any]:
    """Build a read-only weekly operational report from the execution journal."""
    if not journal_path.is_file():
        raise SkillError(f"journal does not exist: {journal_path}")
    if window_days < 1 or window_days > 365:
        raise SkillError("weekly report window must be between 1 and 365 days")
    if minimum_samples < 1:
        raise SkillError("weekly report minimum samples must be at least 1")
    if not 0 < drift_threshold <= 1:
        raise SkillError("weekly report drift threshold must be greater than 0 and at most 1")
    as_of_dt = _parse_observation_time(as_of) if as_of else dt.datetime.now(dt.timezone.utc)
    if as_of_dt is None:
        raise SkillError("weekly report as_of must be an ISO-8601 timestamp")
    cutoff = as_of_dt - dt.timedelta(days=window_days)
    conn = sqlite3.connect(f"file:{journal_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        chain = verify_journal_chain(conn)
        events = [journal_event_from_row(row) for row in conn.execute("SELECT * FROM journal_events ORDER BY sequence")]
        decisions = {event["event_id"]: event for event in events if event["kind"] == "decision"}
        period_events = []
        for event in events:
            timestamp = _parse_observation_time(event.get("created_at"))
            if timestamp is not None and cutoff <= timestamp <= as_of_dt:
                period_events.append(event)
        period_decisions = [event for event in period_events if event["kind"] == "decision"]
        period_outcomes = [event for event in period_events if event["kind"] == "outcome"]
        total = _empty_outcome_metrics()
        failure_by_skill: dict[str, int] = {}
        failure_by_relation: dict[str, int] = {}
        unlinked = 0
        for event in period_outcomes:
            status = event["payload"].get("status")
            if status not in CALIBRATION_OUTCOMES:
                continue
            decision = decisions.get(event.get("parent_event_id"))
            if decision is None:
                unlinked += 1
                continue
            _add_outcome_metric(total, status)
            attributions = _route_attributions(decision["payload"])
            if not attributions:
                unlinked += 1
                continue
            for attribution in attributions:
                if status == "failure":
                    failure_by_skill[attribution["skill_id"]] = failure_by_skill.get(attribution["skill_id"], 0) + 1
                    failure_by_relation[attribution["relation"]] = failure_by_relation.get(attribution["relation"], 0) + 1
        abstained_decisions = []
        abstention_reasons: dict[str, int] = {}
        unselected_decisions = []
        for event in period_decisions:
            payload = event["payload"]
            route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
            lead, _, _ = _route_lead(payload)
            is_abstained = bool(payload.get("abstained") or route.get("abstained") or payload.get("abstention_reason") or route.get("abstention_reason"))
            if is_abstained:
                abstained_decisions.append(event)
                reason = payload.get("abstention_reason") or route.get("abstention_reason") or "unspecified"
                abstention_reasons[reason] = abstention_reasons.get(reason, 0) + 1
            elif lead is None:
                unselected_decisions.append(event)
        observations = _journal_route_observations(conn, as_of_dt)
        drift = temporal_calibration_drift(observations, window_days=window_days, minimum_samples=minimum_samples, threshold_delta=drift_threshold)
        outcomes = _finalize_outcome_metric(total)
        abstentions = {"decisions": len(abstained_decisions), "rate_of_decisions": round(len(abstained_decisions) / len(period_decisions), 4) if period_decisions else None, "by_reason": dict(sorted(abstention_reasons.items()))}
        routing_failures = {
            "failed_outcomes": total["counts"].get("failure", 0),
            "unselected_decisions": len(unselected_decisions),
            "unlinked_outcomes": unlinked,
            "by_skill": dict(sorted(failure_by_skill.items())),
            "by_relation": dict(sorted(failure_by_relation.items())),
        }
        action_items = _weekly_action_items(
            period_decisions=period_decisions,
            outcomes=outcomes,
            abstentions=abstentions,
            routing_failures=routing_failures,
            drift=drift,
            observations=observations,
            minimum_samples=minimum_samples,
        )
        return {
            "schema_version": 1,
            "ok": True,
            "report": "weekly-operations",
            "read_only": True,
            "journal": chain,
            "period": {"start": cutoff.isoformat(), "end": as_of_dt.isoformat(), "days": window_days},
            "events": {"decisions": len(period_decisions), "outcomes": len(period_outcomes)},
            "outcomes": outcomes,
            "abstentions": abstentions,
            "routing_failures": routing_failures,
            "calibration_drift": drift,
            "observations_used_for_drift": len(observations),
            "action_items": action_items,
        }
    except sqlite3.Error as exc:
        raise SkillError(f"weekly report failed: {exc}") from exc
    finally:
        conn.close()


def _weekly_action_items(
    *,
    period_decisions: list[dict[str, Any]],
    outcomes: dict[str, Any],
    abstentions: dict[str, Any],
    routing_failures: dict[str, Any],
    drift: dict[str, Any],
    observations: list[dict[str, Any]],
    minimum_samples: int,
) -> list[dict[str, Any]]:
    """Turn report signals into an explicit, human-reviewed work queue.

    These are deliberately recommendations rather than automatic mutations. The
    report must remain safe to run against a sparse or read-only journal.
    """
    items: list[dict[str, Any]] = []

    def add(priority: str, signal: str, evidence: dict[str, Any], action: str) -> None:
        items.append({
            "id": signal,
            "priority": priority,
            "signal": signal,
            "evidence": evidence,
            "recommended_action": action,
            "status": "open",
            "requires_human_review": True,
        })

    if drift.get("drift_detected"):
        add(
            "high",
            "calibration_drift",
            {"status": drift.get("status"), "success_rate_delta": drift.get("success_rate_delta")},
            "Freeze automatic policy changes and run the independent held-out suite before reviewing the active calibration policy.",
        )
    failed = routing_failures.get("failed_outcomes", 0)
    if failed:
        failure_rate = outcomes.get("failure_rate", 0.0)
        add(
            "high" if failed >= 2 or failure_rate >= 0.2 else "medium",
            "routing_failures",
            {"failed_outcomes": failed, "failure_rate": failure_rate, "by_skill": routing_failures.get("by_skill", {})},
            "Inspect the attributed skill and relation, reproduce a representative failure, and add a regression case before changing routing behavior.",
        )
    unlinked = routing_failures.get("unlinked_outcomes", 0)
    if unlinked:
        add(
            "medium",
            "unlinked_outcomes",
            {"count": unlinked},
            "Repair outcome parent links or document why the outcome cannot be attributed; unattributed outcomes cannot calibrate routing safely.",
        )
    unselected = routing_failures.get("unselected_decisions", 0)
    if unselected:
        add(
            "medium",
            "unselected_decisions",
            {"count": unselected},
            "Review representative unselected decisions for missing skills, filters, or an overly conservative abstention gate.",
        )
    unexpected_abstentions = {
        reason: count
        for reason, count in abstentions.get("by_reason", {}).items()
        if reason != "negative_evidence_gate"
    }
    if unexpected_abstentions:
        add(
            "medium",
            "unexpected_abstentions",
            {"by_reason": unexpected_abstentions},
            "Investigate non-negative-evidence abstentions separately; do not tune them away without held-out no-trigger controls.",
        )
    if not period_decisions:
        add(
            "low",
            "insufficient_decisions",
            {"decisions": 0, "outcomes": outcomes.get("outcomes", 0)},
            "Collect representative routed decisions with parent-linked outcomes before making quality or calibration claims.",
        )
    elif drift.get("status") == "insufficient_data" and len(observations) < minimum_samples:
        add(
            "low",
            "insufficient_drift_samples",
            {"observations": len(observations), "minimum_samples": minimum_samples},
            "Keep collecting verified outcomes across both sides of the temporal comparison window.",
        )
    return items


def render_weekly_report(report: dict[str, Any]) -> str:
    period = report["period"]
    outcomes = report["outcomes"]
    abstentions = report["abstentions"]
    failures = report["routing_failures"]
    drift = report["calibration_drift"]

    def percent(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"

    lines = [
        "WEEKLY SKILL ROUTING REPORT",
        f"Period: {period['start']} to {period['end']} ({period['days']} days)",
        f"Journal: verified {report['journal']['events']} events; read-only={report['read_only']}",
        "",
        "EXECUTIVE SUMMARY",
        f"- Outcomes: {outcomes['outcomes']} attributed; {outcomes['counts']['success']} success, {outcomes['counts']['partial']} partial, {outcomes['counts']['failure']} failure, {outcomes['counts']['abstain']} abstain.",
        f"- Abstentions: {abstentions['decisions']} of {report['events']['decisions']} decisions ({percent(abstentions['rate_of_decisions'])}); reasons: {', '.join(f'{key}={value}' for key, value in abstentions.get('by_reason', {}).items()) or 'none'}.",
        f"- Routing failures: {failures['failed_outcomes']} failed outcomes; {failures['unselected_decisions']} decisions had no selected lead; {failures['unlinked_outcomes']} outcomes were unlinked.",
        f"- Calibration drift: {drift['status']} (recent success delta: {drift.get('success_rate_delta') if drift.get('success_rate_delta') is not None else 'n/a'}).",
        "",
        "OUTCOMES",
        f"Success: {outcomes['counts']['success']} ({percent(outcomes['success_rate'])})",
        f"Partial: {outcomes['counts']['partial']} ({percent(outcomes['partial_rate'])})",
        f"Failure: {outcomes['counts']['failure']} ({percent(outcomes['failure_rate'])})",
        f"Abstain: {outcomes['counts']['abstain']} ({percent(outcomes['abstention_rate'])})",
        "",
        "ROUTING FAILURES",
    ]
    if failures["by_skill"]:
        lines.append("Failures by skill: " + ", ".join(f"{key}={value}" for key, value in failures["by_skill"].items()))
    else:
        lines.append("No attributed routing failures.")
    if failures["by_relation"]:
        lines.append("Failures by relation: " + ", ".join(f"{key}={value}" for key, value in failures["by_relation"].items()))
    lines.extend([
        "",
        "CALIBRATION DRIFT",
        f"Status: {drift['status']}",
        f"Observations: {report['observations_used_for_drift']} (minimum {drift['minimum_samples']} required per window)",
        f"Recent: {drift['recent']}",
        f"Baseline: {drift['baseline']}",
        f"Reasons: {'; '.join(drift['reasons']) if drift['reasons'] else 'none'}",
        "",
        "ACTION ITEMS",
    ])
    if report.get("action_items"):
        for item in report["action_items"]:
            lines.append(f"- [{item['priority']}] {item['signal']}: {item['recommended_action']}")
    else:
        lines.append("No review actions triggered; continue routine monitoring.")
    lines.extend([
        "",
        "Interpretation: action items are human-reviewed signals, not automatic policy changes. Confirm drift and routing regressions against independent held-out cases before changing an active policy.",
    ])
    return "\n".join(lines)


def _parse_observation_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.timezone.utc)


def _observation_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    if not observations:
        return {"samples": 0, "mean_confidence": None, "observed_score": None}
    return {
        "samples": len(observations),
        "mean_confidence": round(sum(item["confidence"] for item in observations) / len(observations), 4),
        "observed_score": round(sum(item["outcome_score"] for item in observations) / len(observations), 4),
    }


def temporal_calibration_drift(observations: list[dict[str, Any]], window_days: int = 30, minimum_samples: int = 5, threshold_delta: float = 0.15) -> dict[str, Any]:
    if window_days < 1:
        raise SkillError("temporal window days must be at least 1")
    if not 0 < threshold_delta <= 1:
        raise SkillError("temporal drift threshold must be greater than 0 and at most 1")
    timestamped = [(item, _parse_observation_time(item.get("observed_at"))) for item in observations]
    timestamped = [(item, timestamp) for item, timestamp in timestamped if timestamp is not None]
    if not timestamped:
        return {"status": "insufficient_data", "drift_detected": False, "window_days": window_days, "minimum_samples": minimum_samples, "recent": _observation_summary([]), "baseline": _observation_summary([]), "reasons": ["no timestamped observations"]}
    latest = max(timestamp for _, timestamp in timestamped)
    cutoff = latest - dt.timedelta(days=window_days)
    recent = [item for item, timestamp in timestamped if timestamp >= cutoff]
    baseline = [item for item, timestamp in timestamped if timestamp < cutoff]
    recent_summary = _observation_summary(recent)
    baseline_summary = _observation_summary(baseline)
    reasons: list[str] = []
    if len(recent) < minimum_samples or len(baseline) < minimum_samples:
        reasons.append("recent or baseline window has insufficient samples")
    success_delta = None
    if recent_summary["observed_score"] is not None and baseline_summary["observed_score"] is not None:
        success_delta = round(recent_summary["observed_score"] - baseline_summary["observed_score"], 4)
        if abs(success_delta) >= threshold_delta:
            reasons.append("observed success rate changed beyond temporal threshold")
    return {
        "status": "drift_detected" if reasons and len(recent) >= minimum_samples and len(baseline) >= minimum_samples else "insufficient_data" if reasons else "in_sync",
        "drift_detected": bool(success_delta is not None and abs(success_delta) >= threshold_delta and len(recent) >= minimum_samples and len(baseline) >= minimum_samples),
        "window_days": window_days,
        "cutoff": cutoff.isoformat(),
        "latest_observation_at": latest.isoformat(),
        "minimum_samples": minimum_samples,
        "threshold_delta": threshold_delta,
        "success_rate_delta": success_delta,
        "recent": recent_summary,
        "baseline": baseline_summary,
        "reasons": reasons,
    }


def load_route_observations(journal_path: Path, min_samples: int, target_success_rate: float) -> dict[str, Any]:
    if not journal_path.is_file():
        raise SkillError(f"journal does not exist: {journal_path}")
    if min_samples < 1:
        raise SkillError("minimum samples must be at least 1")
    conn = connect_journal(journal_path)
    try:
        chain = verify_journal_chain(conn)
        decisions = {
            row["event_id"]: journal_event_from_row(row)
            for row in conn.execute("SELECT * FROM journal_events WHERE kind='decision'")
        }
        observations: list[dict[str, Any]] = []
        for row in conn.execute("SELECT * FROM journal_events WHERE kind='outcome' ORDER BY sequence"):
            event = journal_event_from_row(row)
            decision = decisions.get(event["parent_event_id"])
            if decision is None or event["payload"].get("status") not in CALIBRATION_OUTCOMES:
                continue
            payload = decision["payload"]
            route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
            lead = route.get("lead") if isinstance(route.get("lead"), dict) else payload.get("lead")
            if isinstance(lead, str):
                skill_id = lead
                confidence = route.get("confidence", payload.get("confidence"))
                domain = route.get("domain", payload.get("domain"))
            elif isinstance(lead, dict):
                skill_id = lead.get("skill_id")
                confidence = lead.get("confidence", route.get("confidence", payload.get("confidence")))
                domain = lead.get("domain", route.get("domain", payload.get("domain")))
            else:
                skill_id = payload.get("skill_id")
                confidence = payload.get("confidence")
                domain = payload.get("domain")
            if not isinstance(skill_id, str) or isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                continue
            if not 0 <= float(confidence) <= 1:
                continue
            outcome_score = {"success": 1.0, "partial": 0.5, "failure": 0.0, "abstain": 0.0}[event["payload"]["status"]]
            observations.append({
                "event_id": event["event_id"],
                "decision_event_id": decision["event_id"],
                "skill_id": skill_id,
                "confidence": float(confidence),
                "outcome": event["payload"]["status"],
                "outcome_score": outcome_score,
                "domain": domain if isinstance(domain, str) and domain else "unknown",
                "observed_at": event["created_at"],
            })
        grouped: dict[str, list[dict[str, Any]]] = {}
        domain_grouped: dict[str, list[dict[str, Any]]] = {}
        for observation in observations:
            grouped.setdefault(observation["skill_id"], []).append(observation)
            domain_grouped.setdefault(observation["domain"], []).append(observation)
        policies: dict[str, Any] = {}
        domain_policies: dict[str, Any] = {}
        all_observations = observations
        for skill_id, skill_observations in sorted(grouped.items()):
            policies[skill_id] = _calibration_policy(skill_observations, min_samples, target_success_rate)
        for domain_name, domain_observations in sorted(domain_grouped.items()):
            domain_policies[domain_name] = _calibration_policy(domain_observations, min_samples, target_success_rate)
        global_policy = _calibration_policy(all_observations, min_samples, target_success_rate)
        return {
            "ok": True,
            "journal": chain,
            "observations": observations,
            "policies": policies,
            "domain_policies": domain_policies,
            "global_policy": global_policy,
            "minimum_samples": min_samples,
            "target_success_rate": target_success_rate,
        }
    finally:
        conn.close()


def _calibration_policy(observations: list[dict[str, Any]], min_samples: int, target_success_rate: float) -> dict[str, Any]:
    total = len(observations)
    if total == 0:
        return {"samples": 0, "eligible": False, "threshold": None, "target_success_rate": target_success_rate, "reason": "no labeled outcomes"}
    predicted = sum(item["confidence"] for item in observations) / total
    observed = sum(item["outcome_score"] for item in observations) / total
    brier = sum((item["confidence"] - item["outcome_score"]) ** 2 for item in observations) / total
    candidates: list[dict[str, Any]] = []
    for step in range(21):
        threshold = step / 20
        selected = [item for item in observations if item["confidence"] >= threshold]
        successes = sum(item["outcome_score"] for item in selected)
        candidates.append({
            "threshold": round(threshold, 2),
            "samples": len(selected),
            "mean_confidence": round(sum(item["confidence"] for item in selected) / len(selected), 4) if selected else None,
            "observed_score": round(successes / len(selected), 4) if selected else None,
            "wilson_lower": round(wilson_lower_bound(sum(item["outcome_score"] >= 1.0 for item in selected), len(selected)), 4) if selected else 0.0,
        })
    eligible_candidates = [
        candidate for candidate in candidates
        if candidate["samples"] >= min_samples and candidate["observed_score"] is not None and candidate["observed_score"] >= target_success_rate
    ]
    # Wilson lower bounds make selection conservative while retaining the
    # observed-score floor used by the original calibration contract.
    selected_candidate = max(
        eligible_candidates,
        key=lambda candidate: (candidate["wilson_lower"], candidate["threshold"], candidate["samples"]),
    ) if eligible_candidates else None
    return {
        "samples": total,
        "eligible": total >= min_samples,
        "target_success_rate": target_success_rate,
        "threshold": selected_candidate["threshold"] if selected_candidate else None,
        "selected_wilson_lower": selected_candidate["wilson_lower"] if selected_candidate else None,
        "selection_method": "max_wilson_lower_bound",
        "mean_confidence": round(predicted, 4),
        "observed_score": round(observed, 4),
        "brier_score": round(brier, 4),
        "candidates": candidates,
        "reason": "eligible" if total >= min_samples else "insufficient labeled outcomes",
    }


def _apply_abstention(result: dict[str, Any], policy: dict[str, Any], threshold: float | None) -> dict[str, Any]:
    lead = result.get("lead")
    if lead is None:
        return {"lead": None, "support": [], "validator": None, "fallback": None, "abstained": True, "abstention_reason": "no_candidate"}
    confidence = lead.get("confidence") if isinstance(lead, dict) else None
    abstained = threshold is not None and (not isinstance(confidence, (int, float)) or confidence < threshold)
    if abstained:
        return {"lead": None, "support": [], "validator": None, "fallback": None, "abstained": True, "abstention_reason": "confidence_below_policy"}
    return {**result, "abstained": False}


def evaluate_abstention_cases(db: Path, cases_path: Path, limit: int, policies: dict[str, Any], global_policy: dict[str, Any], domain_policies: dict[str, Any] | None = None) -> dict[str, Any]:
    if not cases_path.is_file():
        raise SkillError(f"held-out cases do not exist: {cases_path}")
    try:
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"cannot read held-out cases: {exc}")
    if not isinstance(cases, list):
        raise SkillError("held-out cases must be a JSON array")
    results: list[dict[str, Any]] = []
    domain_policies = domain_policies or {}
    for position, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("query"), str):
            raise SkillError(f"held-out case {position} requires a query string")
        expected = set(case.get("expected", []))
        forbidden = set(case.get("forbidden", []))
        raw_route = route(db, case["query"], case.get("tag"), case.get("domain"), float(case.get("min_confidence", 0.0)), limit, int(case.get("min_coverage", 1)))
        lead = raw_route.get("lead")
        skill_id = lead.get("skill_id") if isinstance(lead, dict) else None
        lead_domain = lead.get("domain") if isinstance(lead, dict) else None
        policy = policies.get(skill_id, domain_policies.get(lead_domain, global_policy)) if skill_id else global_policy
        threshold = policy.get("threshold") if policy.get("eligible") else None
        selected_route = _apply_abstention(raw_route, policy, threshold)
        selected = selected_route.get("lead")
        selected_id = selected.get("skill_id") if isinstance(selected, dict) else None
        positive = bool(expected)
        correct = bool(selected_id in expected) if positive else selected_id is None
        results.append({
            "id": case.get("id", f"heldout-{position + 1}"),
            "query": case["query"],
            "expected": sorted(expected),
            "forbidden": sorted(forbidden),
            "raw_lead": skill_id,
            "selected": selected_id,
            "abstained": selected_route["abstained"],
            "abstention_reason": selected_route.get("abstention_reason"),
            "correct": correct,
            "false_activation": not positive and selected_id is not None,
            "forbidden_hit": selected_id in forbidden if selected_id else False,
            "confidence": selected.get("confidence") if isinstance(selected, dict) else None,
            "threshold": threshold,
        })
    positive = [item for item in results if item["expected"]]
    negative = [item for item in results if not item["expected"]]
    selected = [item for item in results if item["selected"] is not None]
    return {
        "ok": True,
        "cases": len(results),
        "metrics": {
            "coverage": round(len(selected) / len(results), 4) if results else None,
            "selective_accuracy": round(sum(item["correct"] for item in selected) / len(selected), 4) if selected else None,
            "positive_hit_rate": round(sum(item["selected"] in item["expected"] for item in positive) / len(positive), 4) if positive else None,
            "negative_abstention_rate": round(sum(item["abstained"] for item in negative) / len(negative), 4) if negative else None,
            "false_activation_rate": round(sum(item["false_activation"] for item in negative) / len(negative), 4) if negative else None,
            "forbidden_rate": round(sum(item["forbidden_hit"] for item in results) / len(results), 4) if results else None,
            "abstentions": sum(item["abstained"] for item in results),
        },
        "results": results,
    }


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.is_file():
            digest.update(candidate.name.encode("utf-8"))
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def calibrate_routes(journal_path: Path, db: Path, cases_path: Path, min_samples: int, limit: int, target_success_rate: float, temporal_window_days: int = 30, temporal_drift_threshold: float = 0.15) -> dict[str, Any]:
    if not 0 < target_success_rate <= 1:
        raise SkillError("target success rate must be greater than 0 and at most 1")
    index_before = file_fingerprint(db)
    journal_before = file_fingerprint(journal_path)
    observations = load_route_observations(journal_path, min_samples, target_success_rate)
    heldout = evaluate_abstention_cases(db, cases_path, limit, observations["policies"], observations["global_policy"], observations["domain_policies"])
    temporal_drift = temporal_calibration_drift(observations["observations"], temporal_window_days, min_samples, temporal_drift_threshold)
    index_after = file_fingerprint(db)
    journal_after = file_fingerprint(journal_path)
    return {
        "ok": True,
        "policy_source": "verified journal outcomes",
        "policy_mutated": False,
        "routing_policy_changed": False,
        "index_mutated": index_before != index_after,
        "journal_mutated": journal_before != journal_after,
        "artifacts_unchanged": index_before == index_after and journal_before == journal_after,
        "index_fingerprint_before": index_before,
        "index_fingerprint_after": index_after,
        "journal_fingerprint_before": journal_before,
        "journal_fingerprint_after": journal_after,
        "heldout_independent": True,
        "thresholds_fitted_on_holdout": False,
        "minimum_samples": min_samples,
        "target_success_rate": target_success_rate,
        "temporal_window_days": temporal_window_days,
        "temporal_drift_threshold": temporal_drift_threshold,
        "temporal_drift": temporal_drift,
        "calibration": observations,
        "heldout": heldout,
    }


def _policy_snapshot_from_calibration(report: dict[str, Any]) -> dict[str, Any]:
    calibration = report.get("calibration") if isinstance(report, dict) else None
    if not isinstance(calibration, dict) or not isinstance(calibration.get("global_policy"), dict):
        raise SkillError("calibration report requires calibration.global_policy")
    policies = calibration.get("policies", {})
    if not isinstance(policies, dict):
        raise SkillError("calibration report requires calibration.policies object")
    domain_policies = calibration.get("domain_policies", {})
    if not isinstance(domain_policies, dict):
        raise SkillError("calibration report requires calibration.domain_policies object")
    return {"global": calibration["global_policy"], "by_skill": policies, "by_domain": domain_policies}


def _policy_artifact_hash(artifact: dict[str, Any]) -> str:
    payload = dict(artifact)
    payload.pop("integrity", None)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_policy_artifact(artifact: Any) -> dict[str, Any]:
    if not isinstance(artifact, dict) or artifact.get("schema_version") != 1:
        raise SkillError("calibration policy artifact schema_version must be 1")
    if artifact.get("artifact_type") != "skill-supermind-calibration-policy":
        raise SkillError("unsupported calibration policy artifact type")
    versions = artifact.get("versions")
    if not isinstance(versions, list) or not versions:
        raise SkillError("calibration policy artifact requires versions")
    seen: set[int] = set()
    active_count = 0
    active_version = artifact.get("active_version")
    allowed = {"candidate", "approved", "active", "superseded", "rolled_back"}
    for version in versions:
        if not isinstance(version, dict) or isinstance(version.get("version"), bool) or not isinstance(version.get("version"), int) or version["version"] < 1:
            raise SkillError("calibration policy versions require positive integer version numbers")
        if version["version"] in seen:
            raise SkillError("calibration policy versions must be unique")
        seen.add(version["version"])
        if version.get("status") not in allowed:
            raise SkillError(f"unsupported calibration policy status: {version.get('status')!r}")
        if version.get("status") == "active":
            active_count += 1
            if active_version != version["version"]:
                raise SkillError("active calibration policy version does not match active_version")
        if version["status"] in {"approved", "active", "superseded", "rolled_back"}:
            approval = version.get("approval")
            if not isinstance(approval, dict) or not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip():
                raise SkillError("approved calibration policy versions require approval.approved_by")
        if not isinstance(version.get("policy"), dict) or "global" not in version["policy"] or "by_skill" not in version["policy"]:
            raise SkillError("calibration policy version requires policy.global and policy.by_skill")
    if active_count > 1 or (active_count == 0) != (active_version is None):
        raise SkillError("calibration policy artifact has inconsistent active version state")
    integrity = artifact.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256" or integrity.get("payload_sha256") != _policy_artifact_hash(artifact):
        raise SkillError("calibration policy artifact integrity verification failed")
    return artifact


def _read_policy_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SkillError(f"calibration policy artifact does not exist: {path}")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"cannot read calibration policy artifact: {exc}") from exc
    return _validate_policy_artifact(artifact)


def _write_policy_artifact(path: Path, artifact: dict[str, Any]) -> None:
    artifact["integrity"] = {"algorithm": "sha256", "payload_sha256": _policy_artifact_hash(artifact)}
    _validate_policy_artifact(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(artifact, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _policy_version(artifact: dict[str, Any], version: int) -> dict[str, Any]:
    for candidate in artifact["versions"]:
        if candidate["version"] == version:
            return candidate
    raise SkillError(f"calibration policy version does not exist: {version}")


def _append_policy_event(artifact: dict[str, Any], version: dict[str, Any], action: str, actor: str, note: str = "") -> None:
    event = {"action": action, "actor": actor, "at": utc_now(), "version": version["version"]}
    if note:
        event["note"] = note
    version.setdefault("events", []).append(event)
    artifact.setdefault("events", []).append(event.copy())


def create_calibration_policy_artifact(path: Path, calibration_report: dict[str, Any], created_by: str = "calibrate") -> dict[str, Any]:
    if not isinstance(created_by, str) or not created_by.strip():
        raise SkillError("created_by must be a non-empty string")
    snapshot = _policy_snapshot_from_calibration(calibration_report)
    if path.exists():
        artifact = _read_policy_artifact(path)
    else:
        artifact = {
            "schema_version": 1,
            "artifact_type": "skill-supermind-calibration-policy",
            "created_at": utc_now(),
            "versions": [],
            "active_version": None,
            "events": [],
        }
    version_number = max((version["version"] for version in artifact["versions"]), default=0) + 1
    source = {
        "index_fingerprint": calibration_report.get("index_fingerprint_after") or calibration_report.get("index_fingerprint_before"),
        "journal_fingerprint": calibration_report.get("journal_fingerprint_after") or calibration_report.get("journal_fingerprint_before"),
        "minimum_samples": calibration_report.get("minimum_samples"),
        "target_success_rate": calibration_report.get("target_success_rate"),
        "heldout_metrics": calibration_report.get("heldout", {}).get("metrics") if isinstance(calibration_report.get("heldout"), dict) else None,
        "temporal_drift": calibration_report.get("temporal_drift"),
    }
    version = {
        "version": version_number,
        "status": "candidate",
        "created_at": utc_now(),
        "created_by": created_by,
        "policy": snapshot,
        "policy_sha256": hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest(),
        "source": source,
        "approval": None,
        "events": [],
    }
    artifact["versions"].append(version)
    _append_policy_event(artifact, version, "created", created_by, "candidate policy version created")
    _write_policy_artifact(path, artifact)
    return calibration_policy_artifact_verify(path)


def approve_calibration_policy(path: Path, version_number: int, approved_by: str, note: str = "") -> dict[str, Any]:
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise SkillError("approved_by must be a non-empty string")
    artifact = _read_policy_artifact(path)
    version = _policy_version(artifact, version_number)
    if version["status"] != "candidate":
        raise SkillError(f"only candidate calibration policies can be approved; current status is {version['status']}")
    version["status"] = "approved"
    version["approval"] = {"approved_by": approved_by, "approved_at": utc_now(), "note": note}
    _append_policy_event(artifact, version, "approved", approved_by, note)
    _write_policy_artifact(path, artifact)
    return calibration_policy_artifact_verify(path)


def promote_calibration_policy(path: Path, version_number: int, actor: str, note: str = "") -> dict[str, Any]:
    if not isinstance(actor, str) or not actor.strip():
        raise SkillError("actor must be a non-empty string")
    artifact = _read_policy_artifact(path)
    version = _policy_version(artifact, version_number)
    if version["status"] == "active":
        return calibration_policy_artifact_verify(path)
    if version["status"] != "approved":
        raise SkillError("only approved calibration policies can be promoted")
    previous = artifact.get("active_version")
    if previous is not None:
        previous_version = _policy_version(artifact, previous)
        previous_version["status"] = "superseded"
        _append_policy_event(artifact, previous_version, "superseded", actor, f"superseded by version {version_number}")
    version["status"] = "active"
    version["previous_version"] = previous
    version["promoted_at"] = utc_now()
    version["promoted_by"] = actor
    artifact["active_version"] = version_number
    _append_policy_event(artifact, version, "promoted", actor, note)
    _write_policy_artifact(path, artifact)
    return calibration_policy_artifact_verify(path)


def rollback_calibration_policy(path: Path, actor: str, note: str = "") -> dict[str, Any]:
    if not isinstance(actor, str) or not actor.strip():
        raise SkillError("actor must be a non-empty string")
    artifact = _read_policy_artifact(path)
    active_number = artifact.get("active_version")
    if active_number is None:
        raise SkillError("no active calibration policy is available to roll back")
    active = _policy_version(artifact, active_number)
    previous_number = active.get("previous_version")
    if previous_number is None:
        raise SkillError("active calibration policy has no previous version to roll back to")
    previous = _policy_version(artifact, previous_number)
    active["status"] = "rolled_back"
    previous["status"] = "active"
    artifact["active_version"] = previous_number
    _append_policy_event(artifact, active, "rolled_back", actor, note)
    _append_policy_event(artifact, previous, "rollback_promoted", actor, f"restored version {previous_number}")
    _write_policy_artifact(path, artifact)
    return calibration_policy_artifact_verify(path)


def calibration_policy_artifact_verify(path: Path) -> dict[str, Any]:
    artifact = _read_policy_artifact(path)
    return {
        "ok": True,
        "path": str(path),
        "schema_version": artifact["schema_version"],
        "artifact_type": artifact["artifact_type"],
        "active_version": artifact["active_version"],
        "versions": [{"version": version["version"], "status": version["status"], "created_at": version["created_at"]} for version in artifact["versions"]],
        "integrity": artifact["integrity"],
    }


def _changed_policy_paths(left: Any, right: Any, prefix: str = "policy") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_changed_policy_paths(left[key], right[key], child))
        return paths
    return [] if left == right else [prefix]


def monitor_calibration_policy_drift(path: Path, calibration_report: dict[str, Any]) -> dict[str, Any]:
    artifact = _read_policy_artifact(path)
    current_policy = _policy_snapshot_from_calibration(calibration_report)
    active_number = artifact.get("active_version")
    if active_number is None:
        return {"ok": True, "in_sync": False, "status": "no_active_policy", "drift_detected": True, "policy_changes": [], "source_changes": [], "active_version": None}
    active = _policy_version(artifact, active_number)
    policy_changes = _changed_policy_paths(active["policy"], current_policy)
    source_changes: list[str] = []
    source = active.get("source", {})
    for field, report_field in (("index_fingerprint", "index_fingerprint_after"), ("journal_fingerprint", "journal_fingerprint_after"), ("temporal_drift", "temporal_drift")):
        if source.get(field) is not None and calibration_report.get(report_field) is not None and source[field] != calibration_report[report_field]:
            source_changes.append(field)
    drift = bool(policy_changes or source_changes)
    return {
        "ok": True,
        "in_sync": not drift,
        "status": "in_sync" if not drift else "drift_detected",
        "drift_detected": drift,
        "active_version": active_number,
        "policy_changes": policy_changes,
        "source_changes": source_changes,
        "active_policy_sha256": active.get("policy_sha256"),
        "current_policy_sha256": hashlib.sha256(canonical_json(current_policy).encode("utf-8")).hexdigest(),
    }


def _read_ci_baseline(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SkillError(f"CI baseline does not exist: {path}")
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"cannot read CI baseline: {exc}") from exc
    if not isinstance(baseline, dict) or baseline.get("schema_version") != 1:
        raise SkillError("CI baseline requires schema_version 1")
    routing = baseline.get("routing")
    metrics = routing.get("metrics") if isinstance(routing, dict) else None
    if not isinstance(metrics, dict):
        raise SkillError("CI baseline requires routing.metrics")
    for name in ("hit_rate", "forbidden_rate", "no_trigger_false_activation_rate"):
        value = metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            raise SkillError(f"CI baseline routing metric must be numeric [0,1]: {name}")
    drift = baseline.get("calibration_drift")
    if not isinstance(drift, dict) or not isinstance(drift.get("status"), str) or not isinstance(drift.get("drift_detected"), bool):
        raise SkillError("CI baseline requires calibration_drift.status and boolean calibration_drift.drift_detected")
    return baseline


def _ci_input_fingerprint(path: Path) -> str:
    """Fingerprint the database file without treating read-lock sidecars as mutations."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_only_journal_chain(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SkillError(f"journal does not exist: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        return verify_journal_chain(conn)
    finally:
        conn.close()


def ci_quality_gate(
    db: Path,
    journal: Path,
    cases: Path,
    baseline_path: Path,
    limit: int = 10,
    minimum_samples: int = 5,
    drift_window_days: int = 30,
    drift_threshold: float = 0.15,
) -> dict[str, Any]:
    """Run read-only CI gates for routing, journal integrity, and drift.

    The gate is deliberately fail-closed: it requires a versioned baseline,
    positive and no-trigger routing coverage, an unchanged pair of artifacts,
    and a valid journal chain before it can pass.
    """
    if not 1 <= limit <= 100:
        raise SkillError("CI routing limit must be between 1 and 100")
    if not 1 <= minimum_samples <= 10_000:
        raise SkillError("CI minimum samples must be between 1 and 10000")
    if not 1 <= drift_window_days <= 3650:
        raise SkillError("CI drift window must be between 1 and 3650 days")
    if not 0 < drift_threshold <= 1:
        raise SkillError("CI drift threshold must be greater than 0 and at most 1")
    if not db.is_file():
        raise SkillError(f"index database does not exist: {db}")
    if not cases.is_file():
        raise SkillError(f"evaluation cases do not exist: {cases}")
    baseline = _read_ci_baseline(baseline_path)
    before = {"index": _ci_input_fingerprint(db), "journal": _ci_input_fingerprint(journal)}
    failures: list[str] = []

    current_routing = evaluate_index(db, cases, limit)
    current_metrics = current_routing["metrics"]
    baseline_metrics = baseline["routing"]["metrics"]
    if current_metrics.get("expected_cases", 0) < 1:
        failures.append("routing evaluation has no positive cases")
    if current_metrics.get("no_trigger_false_activation_rate") is None:
        failures.append("routing evaluation has no no-trigger cases")
    comparisons = {
        "hit_rate": ("lower", baseline_metrics["hit_rate"]),
        "forbidden_rate": ("higher", baseline_metrics["forbidden_rate"]),
        "no_trigger_false_activation_rate": ("higher", baseline_metrics["no_trigger_false_activation_rate"]),
    }
    regressions: list[dict[str, Any]] = []
    for name, (direction, baseline_value) in comparisons.items():
        current_value = current_metrics.get(name)
        if not isinstance(current_value, (int, float)) or isinstance(current_value, bool):
            regressions.append({"metric": name, "current": current_value, "baseline": baseline_value, "reason": "missing_current_metric"})
        elif (direction == "lower" and current_value < baseline_value) or (direction == "higher" and current_value > baseline_value):
            regressions.append({"metric": name, "current": current_value, "baseline": baseline_value, "direction": direction})
    for optional in ("top3_rate", "mrr"):
        current_value = current_metrics.get(optional)
        baseline_value = baseline_metrics.get(optional)
        if isinstance(current_value, (int, float)) and isinstance(baseline_value, (int, float)) and current_value < baseline_value:
            regressions.append({"metric": optional, "current": current_value, "baseline": baseline_value, "direction": "lower"})
    routing_passed = not failures and not regressions
    if not routing_passed:
        failures.append("routing regression or insufficient evaluation coverage")

    journal_check: dict[str, Any] = {"passed": False, "read_only": True}
    try:
        journal_check.update(_read_only_journal_chain(journal))
        journal_check["passed"] = True
    except (OSError, sqlite3.Error, SkillError, KeyError, TypeError, ValueError) as exc:
        journal_check["error"] = str(exc)
        failures.append("journal chain verification failed")

    drift_check: dict[str, Any] = {"passed": False, "evaluated": False, "baseline": baseline["calibration_drift"]}
    if journal_check["passed"]:
        try:
            weekly = weekly_report_data(journal, window_days=drift_window_days, minimum_samples=minimum_samples, drift_threshold=drift_threshold)
            current_drift = weekly["calibration_drift"]
            current_detected = bool(current_drift.get("drift_detected"))
            baseline_detected = bool(baseline["calibration_drift"].get("drift_detected"))
            drift_check.update({
                "passed": not current_detected,
                "evaluated": True,
                "current": current_drift,
                "newly_detected": current_detected and not baseline_detected,
                "known_drift_persisted": current_detected and baseline_detected,
            })
            if current_detected:
                failures.append("calibration drift detected")
        except (OSError, sqlite3.Error, SkillError, KeyError, TypeError, ValueError) as exc:
            drift_check["error"] = str(exc)
            failures.append("calibration drift check failed")
    else:
        drift_check["error"] = "skipped because journal verification failed"

    after = {"index": _ci_input_fingerprint(db), "journal": _ci_input_fingerprint(journal)}
    artifacts_unchanged = before == after
    if not artifacts_unchanged:
        failures.append("CI checks mutated an input artifact")
    result = {
        "schema_version": 1,
        "ok": not failures,
        "passed": not failures,
        "read_only": True,
        "artifacts_unchanged": artifacts_unchanged,
        "failures": failures,
        "routing": {
            "passed": routing_passed,
            "cases": current_routing.get("cases", 0),
            "metrics": current_metrics,
            "baseline_metrics": baseline_metrics,
            "regressions": regressions,
        },
        "journal": journal_check,
        "calibration_drift": drift_check,
        "fingerprints": {"before": before, "after": after},
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate discovered skills")
    validate.add_argument("root", type=Path)
    validate.add_argument("--strict", action="store_true")

    index = sub.add_parser("index", help="build or atomically refresh an index")
    index.add_argument("root", type=Path)
    index.add_argument("--db", type=Path)
    index.add_argument("--manifest", type=Path)
    index.add_argument("--strict", action="store_true")

    incremental = sub.add_parser("index-incremental", help="refresh an index by reusing unchanged content hashes")
    incremental.add_argument("root", type=Path)
    incremental.add_argument("--db", type=Path)
    incremental.add_argument("--manifest", type=Path)
    incremental.add_argument("--strict", action="store_true")

    query = sub.add_parser("query", help="retrieve ranked skills")
    query.add_argument("db", type=Path)
    query.add_argument("text")
    query.add_argument("--tag")
    query.add_argument("--domain")
    query.add_argument("--min-confidence", type=float, default=0.0)
    query.add_argument("--limit", type=int, default=8)
    query.add_argument("--explain", action="store_true")
    query.add_argument("--min-coverage", type=int, default=1)

    route = sub.add_parser("route", help="select a lead plus bounded graph roles")
    route.add_argument("db", type=Path)
    route.add_argument("text")
    route.add_argument("--tag")
    route.add_argument("--domain")
    route.add_argument("--min-confidence", type=float, default=0.0)
    route.add_argument("--limit", type=int, default=8)
    route.add_argument("--min-coverage", type=int, default=1)
    route.add_argument("--journal", type=Path, help="optional journal path; requires explicit opt-in")
    route.add_argument("--journal-opt-in", action="store_true", help="allow automatic route journaling")
    route.add_argument("--privacy-reviewed", action="store_true", help="confirm task-content privacy review")
    route.add_argument("--store-task-content", action="store_true", help="store redacted task text; requires --privacy-reviewed")
    route.add_argument("--journal-redact-key", action="append", default=[], help="additional key to redact in journal payload")
    route.add_argument("--policy-artifact", type=Path, help="apply the explicitly active calibration policy version")

    evaluate = sub.add_parser("evaluate", help="measure routing quality against JSON cases")
    evaluate.add_argument("db", type=Path)
    evaluate.add_argument("cases", type=Path)
    evaluate.add_argument("--limit", type=int, default=10)

    domain_eval = sub.add_parser("evaluate-domain", help="score held-out domain queries with graded relevance judgments")
    domain_eval.add_argument("db", type=Path)
    domain_eval.add_argument("cases", type=Path)
    domain_eval.add_argument("--limit", type=int, default=10)
    domain_eval.add_argument("--k", type=int, default=3)

    journal = sub.add_parser("journal-init", help="create an append-only execution journal")
    journal.add_argument("journal", type=Path)

    record = sub.add_parser("journal-record", help="append a redacted decision, outcome, or note")
    record.add_argument("journal", type=Path)
    record.add_argument("kind", choices=["decision", "outcome", "note"])
    record.add_argument("payload", help="JSON payload; secrets are redacted before storage")
    record.add_argument("--parent", dest="parent_event_id")
    record.add_argument("--provenance", default="{}", help="JSON provenance object")
    record.add_argument("--redact-key", action="append", default=[], help="additional case-insensitive key to redact")

    journal_show_parser = sub.add_parser("journal-show", help="verify and inspect recent journal events")
    journal_show_parser.add_argument("journal", type=Path)
    journal_show_parser.add_argument("--limit", type=int, default=20)

    journal_verify_parser = sub.add_parser("journal-verify", help="verify journal hashes and sequence")
    journal_verify_parser.add_argument("journal", type=Path)

    journal_evaluate = sub.add_parser("journal-evaluate", help="report verified outcomes by skill and relation")
    journal_evaluate.add_argument("journal", type=Path)

    weekly = sub.add_parser("weekly-report", help="render a human-readable weekly routing operations report")
    weekly.add_argument("journal", type=Path)
    weekly.add_argument("--as-of", help="ISO-8601 report end; defaults to now")
    weekly.add_argument("--window-days", type=int, default=7)
    weekly.add_argument("--minimum-samples", type=int, default=5)
    weekly.add_argument("--drift-threshold", type=float, default=0.15)
    weekly.add_argument("--format", choices=("text", "json"), default="text", help="report format; JSON is suitable for automation")
    weekly.add_argument("--output", type=Path, help="write the selected report format to a file instead of stdout")

    calibrate = sub.add_parser("calibrate", help="derive abstention policy from verified outcomes and score held-out cases")
    calibrate.add_argument("journal", type=Path)
    calibrate.add_argument("db", type=Path)
    calibrate.add_argument("heldout_cases", type=Path)
    calibrate.add_argument("--min-samples", type=int, default=5)
    calibrate.add_argument("--target-success-rate", type=float, default=0.8)
    calibrate.add_argument("--limit", type=int, default=10)
    calibrate.add_argument("--temporal-window-days", type=int, default=30)
    calibrate.add_argument("--temporal-drift-threshold", type=float, default=0.15)

    policy_create = sub.add_parser("policy-create", help="create a versioned calibration policy candidate")
    policy_create.add_argument("artifact", type=Path)
    policy_create.add_argument("calibration_report", type=Path)
    policy_create.add_argument("--created-by", default="calibrate")

    policy_approve = sub.add_parser("policy-approve", help="approve a calibration policy candidate")
    policy_approve.add_argument("artifact", type=Path)
    policy_approve.add_argument("version", type=int)
    policy_approve.add_argument("--approved-by", required=True)
    policy_approve.add_argument("--note", default="")

    policy_promote = sub.add_parser("policy-promote", help="promote an approved calibration policy")
    policy_promote.add_argument("artifact", type=Path)
    policy_promote.add_argument("version", type=int)
    policy_promote.add_argument("--actor", required=True)
    policy_promote.add_argument("--note", default="")

    policy_rollback = sub.add_parser("policy-rollback", help="restore the previous active calibration policy")
    policy_rollback.add_argument("artifact", type=Path)
    policy_rollback.add_argument("--actor", required=True)
    policy_rollback.add_argument("--note", default="")

    policy_verify = sub.add_parser("policy-verify", help="verify calibration policy artifact integrity and lifecycle")
    policy_verify.add_argument("artifact", type=Path)

    policy_drift = sub.add_parser("policy-drift", help="compare an active policy with a fresh calibration report")
    policy_drift.add_argument("artifact", type=Path)
    policy_drift.add_argument("calibration_report", type=Path)

    ci = sub.add_parser("ci-check", help="run read-only routing, journal, and calibration-drift quality gates")
    ci.add_argument("db", type=Path)
    ci.add_argument("journal", type=Path)
    ci.add_argument("cases", type=Path)
    ci.add_argument("baseline", type=Path, help="versioned routing and drift baseline JSON")
    ci.add_argument("--limit", type=int, default=10)
    ci.add_argument("--minimum-samples", type=int, default=5)
    ci.add_argument("--drift-window-days", type=int, default=30)
    ci.add_argument("--drift-threshold", type=float, default=0.15)

    check = sub.add_parser("check", help="detect a stale index or changed manifest")
    check.add_argument("db", type=Path)
    check.add_argument("root", type=Path)
    check.add_argument("--manifest", type=Path)

    graph = sub.add_parser("neighbors", help="return typed graph neighbors")
    graph.add_argument("db", type=Path)
    graph.add_argument("skill_id")
    graph.add_argument("--depth", type=int, default=1)
    graph.add_argument("--relation", choices=sorted(RELATION_TYPES))

    stat = sub.add_parser("stats", help="show index metadata and counts")
    stat.add_argument("db", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return validate_command(args.root, args.strict)
    if args.command == "index":
        db = args.db or (args.root / ".skill-brain" / "index.sqlite3")
        result = refresh_index(args.root, db, args.manifest, args.strict)
        emit(result)
        return 0 if result["ok"] else 1
    if args.command == "index-incremental":
        db = args.db or (args.root / ".skill-brain" / "index.sqlite3")
        try:
            result = refresh_index_incremental(args.root, db, args.manifest, args.strict)
        except SkillError as exc:
            fail(str(exc))
        emit(result)
        return 0 if result["ok"] else 1
    if args.command == "query":
        if not 1 <= args.limit <= 100:
            fail("--limit must be between 1 and 100")
        if not 0 <= args.min_confidence <= 1:
            fail("--min-confidence must be between 0 and 1")
        if not 1 <= args.min_coverage <= 12:
            fail("--min-coverage must be between 1 and 12")
        emit(query_index(args.db, args.text, args.tag, args.domain, args.min_confidence, args.limit, args.explain, args.min_coverage))
        return 0
    if args.command == "route":
        if not 1 <= args.limit <= 100:
            fail("--limit must be between 1 and 100")
        if not 0 <= args.min_confidence <= 1:
            fail("--min-confidence must be between 0 and 1")
        if not 1 <= args.min_coverage <= 12:
            fail("--min-coverage must be between 1 and 12")
        try:
            emit(route_and_journal(
                args.db, args.text, args.tag, args.domain, args.min_confidence, args.limit, args.min_coverage,
                args.journal, args.journal_opt_in, args.privacy_reviewed, args.store_task_content, set(args.journal_redact_key), args.policy_artifact,
            ))
        except SkillError as exc:
            fail(str(exc))
        return 0
    if args.command == "evaluate":
        if not 1 <= args.limit <= 100:
            fail("--limit must be between 1 and 100")
        emit(evaluate_index(args.db, args.cases, args.limit))
        return 0
    if args.command == "evaluate-domain":
        if not 1 <= args.limit <= 100:
            fail("--limit must be between 1 and 100")
        if not 1 <= args.k <= args.limit:
            fail("--k must be between 1 and --limit")
        try:
            emit(evaluate_domain_bench(args.db, args.cases, args.limit, args.k))
        except SkillError as exc:
            fail(str(exc))
        return 0
    if args.command == "journal-init":
        emit(journal_init(args.journal))
        return 0
    if args.command == "journal-record":
        try:
            payload = json.loads(args.payload)
            provenance = json.loads(args.provenance)
        except json.JSONDecodeError as exc:
            fail(f"payload and provenance must be valid JSON: {exc}")
        if not isinstance(provenance, dict):
            fail("--provenance must be a JSON object")
        emit(append_journal_event(args.journal, args.kind, payload, args.parent_event_id, provenance, set(args.redact_key)))
        return 0
    if args.command == "journal-show":
        if not 1 <= args.limit <= 1000:
            fail("--limit must be between 1 and 1000")
        emit(journal_show(args.journal, args.limit))
        return 0
    if args.command == "journal-verify":
        emit(journal_verify(args.journal))
        return 0
    if args.command == "journal-evaluate":
        try:
            emit(journal_outcome_report(args.journal))
        except SkillError as exc:
            fail(str(exc))
        return 0
    if args.command == "weekly-report":
        try:
            report = weekly_report_data(args.journal, args.as_of, args.window_days, args.minimum_samples, args.drift_threshold)
            text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) if args.format == "json" else render_weekly_report(report)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text + "\n", encoding="utf-8")
                print(f"weekly {args.format} report written to {args.output}", file=sys.stderr)
            else:
                print(text)
        except (OSError, SkillError) as exc:
            fail(str(exc))
        return 0
    if args.command == "calibrate":
        if not 1 <= args.min_samples <= 10000:
            fail("--min-samples must be between 1 and 10000")
        if not 0 < args.target_success_rate <= 1:
            fail("--target-success-rate must be greater than 0 and at most 1")
        if not 1 <= args.limit <= 100:
            fail("--limit must be between 1 and 100")
        if not 1 <= args.temporal_window_days <= 3650:
            fail("--temporal-window-days must be between 1 and 3650")
        if not 0 < args.temporal_drift_threshold <= 1:
            fail("--temporal-drift-threshold must be greater than 0 and at most 1")
        try:
            emit(calibrate_routes(args.journal, args.db, args.heldout_cases, args.min_samples, args.limit, args.target_success_rate, args.temporal_window_days, args.temporal_drift_threshold))
        except SkillError as exc:
            fail(str(exc))
        return 0
    if args.command == "policy-create":
        try:
            report = json.loads(args.calibration_report.read_text(encoding="utf-8"))
            result = create_calibration_policy_artifact(args.artifact, report, args.created_by)
        except (OSError, json.JSONDecodeError, SkillError) as exc:
            fail(str(exc))
        emit(result)
        return 0
    if args.command == "policy-approve":
        try:
            result = approve_calibration_policy(args.artifact, args.version, args.approved_by, args.note)
        except SkillError as exc:
            fail(str(exc))
        emit(result)
        return 0
    if args.command == "policy-promote":
        try:
            result = promote_calibration_policy(args.artifact, args.version, args.actor, args.note)
        except SkillError as exc:
            fail(str(exc))
        emit(result)
        return 0
    if args.command == "policy-rollback":
        try:
            result = rollback_calibration_policy(args.artifact, args.actor, args.note)
        except SkillError as exc:
            fail(str(exc))
        emit(result)
        return 0
    if args.command == "policy-verify":
        try:
            result = calibration_policy_artifact_verify(args.artifact)
        except SkillError as exc:
            fail(str(exc))
        emit(result)
        return 0
    if args.command == "policy-drift":
        try:
            report = json.loads(args.calibration_report.read_text(encoding="utf-8"))
            result = monitor_calibration_policy_drift(args.artifact, report)
        except (OSError, json.JSONDecodeError, SkillError) as exc:
            fail(str(exc))
        emit(result)
        return 0 if result["in_sync"] else 1
    if args.command == "ci-check":
        try:
            result = ci_quality_gate(args.db, args.journal, args.cases, args.baseline, args.limit, args.minimum_samples, args.drift_window_days, args.drift_threshold)
        except (OSError, SkillError) as exc:
            fail(str(exc))
        emit(result)
        return 0 if result["passed"] else 1
    if args.command == "check":
        result = check_index(args.db, args.root, args.manifest)
        emit(result)
        return 0 if result["ok"] else 1
    if args.command == "neighbors":
        if not 0 <= args.depth <= 3:
            fail("--depth must be between 0 and 3")
        emit(neighbors(args.db, args.skill_id, args.depth, args.relation))
        return 0
    if args.command == "stats":
        emit(stats(args.db))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
