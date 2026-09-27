#!/usr/bin/env python3
"""Serve a local visual dashboard for skill-supermind artifacts.

The dashboard uses only Python's standard library. It opens the index and
journal SQLite files read-only, discovers JSON reports below a report root,
and serves a small JSON API plus a static browser UI. Operator acknowledgements and explicit reopen decisions
are stored in a separate, atomically replaced local overlay; source artifacts
remain read-only. The report-directory cache can optionally validate cached
file contents with SHA-256, and local operators can manually invalidate only
that in-memory cache after replacing report artifacts externally.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

HTML_PATH = SCRIPT_DIR.parent / "assets" / "dashboard.html"
_REPORT_SCAN_LIMIT_OVERRIDES: ContextVar[dict[str, int] | None] = ContextVar("report_scan_limit_overrides", default=None)
_LAST_REPORT_SCAN: ContextVar[dict[str, Any] | None] = ContextVar("last_report_scan", default=None)


class DashboardData:
    ACTION_STATE_KIND = "skill-supermind-dashboard-action-state"
    ACTION_STATE_SCHEMA_VERSION = 1
    ACTION_STATE_FILE = ".dashboard-action-state.json"
    ACTION_STATUSES = ("acknowledged", "resolved", "reopened")
    ACTION_MUTATION_STATUSES = ("acknowledged", "resolved", "reopen")
    OPERATOR_NOTE_MAX_LENGTH = 2_000
    ACTOR_MAX_LENGTH = 256
    CURATED_REPORT_MANIFEST_KIND = "skill-supermind-curated-report-manifest"
    CURATED_REPORT_MANIFEST_SCHEMA_VERSION = 1
    REPORT_SCAN_MAX_ENTRIES = 1_000
    REPORT_SCAN_MAX_DEPTH = 3
    REPORT_SCAN_MAX_FILES = 200
    REPORT_SCAN_MAX_FILE_BYTES = 10_000_000
    REPORT_SCAN_OVERRIDE_MAX_ENTRIES = 100_000
    REPORT_SCAN_OVERRIDE_MAX_DEPTH = 32
    REPORT_SCAN_OVERRIDE_MAX_FILES = 20_000
    REPORT_SCAN_OVERRIDE_MAX_FILE_BYTES = 100_000_000
    REPORT_SCAN_LIMIT_KEYS = ("scan_max_entries", "scan_max_depth", "scan_max_files", "scan_max_file_bytes")
    REPORT_SCAN_LIMIT_FIELDS = {
        "scan_max_entries": "max_entries",
        "scan_max_depth": "max_depth",
        "scan_max_files": "max_files",
        "scan_max_file_bytes": "max_file_bytes",
    }
    REPORT_SCAN_LIMIT_QUERY_KEYS = {field: key for key, field in REPORT_SCAN_LIMIT_FIELDS.items()}
    REPORT_SCAN_OVERRIDE_MAXIMA = {
        "scan_max_entries": REPORT_SCAN_OVERRIDE_MAX_ENTRIES,
        "scan_max_depth": REPORT_SCAN_OVERRIDE_MAX_DEPTH,
        "scan_max_files": REPORT_SCAN_OVERRIDE_MAX_FILES,
        "scan_max_file_bytes": REPORT_SCAN_OVERRIDE_MAX_FILE_BYTES,
    }
    BENCHMARK_TREE_PREFIXES = ("bench-", "benchmark-", "incremental-", "resource-", "calibration-check", "route-journal-")

    def __init__(self, db: Path, journal: Path, reports: Path, action_state: Path | None = None, local_only: bool = True, benchmark_trees: list[Path] | None = None, report_scan_max_entries: int | None = None, report_scan_max_depth: int | None = None, report_scan_max_files: int | None = None, report_scan_max_file_bytes: int | None = None, cache_content_hash: bool = False, report_manifest: Path | None = None) -> None:
        self.db = db
        self.journal_path = journal
        self.reports = reports
        self.action_state = action_state or (reports / self.ACTION_STATE_FILE)
        self.local_only = local_only
        self.benchmark_trees = tuple(benchmark_trees or ())
        self.report_manifest = report_manifest.resolve() if report_manifest is not None else None
        self.curated_report_manifest = self._load_curated_report_manifest()
        self.report_scan_max_entries = self.REPORT_SCAN_MAX_ENTRIES if report_scan_max_entries is None else report_scan_max_entries
        self.report_scan_max_depth = self.REPORT_SCAN_MAX_DEPTH if report_scan_max_depth is None else report_scan_max_depth
        self.report_scan_max_files = self.REPORT_SCAN_MAX_FILES if report_scan_max_files is None else report_scan_max_files
        self.report_scan_max_file_bytes = self.REPORT_SCAN_MAX_FILE_BYTES if report_scan_max_file_bytes is None else report_scan_max_file_bytes
        if not isinstance(cache_content_hash, bool):
            raise ValueError("cache_content_hash must be a boolean")
        self.cache_content_hash = cache_content_hash
        for name, value in (("max_entries", self.report_scan_max_entries), ("max_depth", self.report_scan_max_depth), ("max_files", self.report_scan_max_files), ("max_file_bytes", self.report_scan_max_file_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"report scan {name} must be a positive integer")
        self._last_report_scan: dict[str, Any] = {}
        self._last_report_directory_cache: dict[str, Any] = {}
        self._last_report_cacheable = False
        self._report_cache: dict[str, Any] | None = None
        self._pending_report_cache_invalidation_reasons: list[str] = []
        self._report_cache_metadata: dict[str, Any] = {
            "enabled": True,
            "status": "empty",
            "freshness": "unknown",
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
            "checks": 0,
            "last_checked_at": None,
            "last_invalidated_at": None,
            "last_rebuilt_at": None,
            "last_invalidation_reasons": [],
            "validation": "directory_and_entry_metadata+sha256" if cache_content_hash else "directory_and_entry_metadata",
            "content_hashed_files": 0,
        }
        self._report_cache_lock = threading.Lock()
        self._benchmark_scan_lock = threading.Lock()
        self._benchmark_inventory_lock = threading.Lock()
        self._action_state_lock = threading.Lock()

    def _load_curated_report_manifest(self) -> dict[str, Any] | None:
        if self.report_manifest is None:
            return None
        try:
            raw = self.report_manifest.read_bytes()
            document = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read curated report manifest: {exc}") from exc
        if not isinstance(document, dict) or document.get("kind") != self.CURATED_REPORT_MANIFEST_KIND or document.get("schema_version") != self.CURATED_REPORT_MANIFEST_SCHEMA_VERSION:
            raise ValueError("curated report manifest has an unsupported or invalid schema")
        raw_reports = document.get("reports")
        if not isinstance(raw_reports, list):
            raise ValueError("curated report manifest reports must be a list")
        root = self.reports.resolve()
        reports: list[str] = []
        seen: set[str] = set()
        for raw_path in raw_reports:
            if not isinstance(raw_path, str) or not raw_path or len(raw_path) > 1_024 or "\\" in raw_path:
                raise ValueError("curated report paths must be non-empty portable relative strings")
            posix_path = PurePosixPath(raw_path)
            if posix_path.is_absolute() or not posix_path.parts or any(part in {"", ".", ".."} for part in posix_path.parts) or ":" in posix_path.parts[0] or posix_path.as_posix() != raw_path:
                raise ValueError(f"curated report path is not a normalized safe relative path: {raw_path}")
            if posix_path.suffix != ".json":
                raise ValueError(f"curated report path must end in .json: {raw_path}")
            normalized = posix_path.as_posix()
            if normalized in seen:
                raise ValueError(f"curated report path is duplicated: {normalized}")
            candidate = self.reports.joinpath(*posix_path.parts).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"curated report path escapes the report root: {normalized}") from exc
            seen.add(normalized)
            reports.append(normalized)
        return {
            "path": str(self.report_manifest),
            "schema_version": self.CURATED_REPORT_MANIFEST_SCHEMA_VERSION,
            "kind": self.CURATED_REPORT_MANIFEST_KIND,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "reports": tuple(reports),
        }

    def _curated_report_manifest_metadata(self) -> dict[str, Any]:
        if self.curated_report_manifest is None:
            return {"enabled": False, "path": None, "schema_version": None, "sha256": None, "report_count": 0, "reports": []}
        manifest = self.curated_report_manifest
        return {
            "enabled": True,
            "path": manifest["path"],
            "schema_version": manifest["schema_version"],
            "kind": manifest["kind"],
            "sha256": manifest["sha256"],
            "report_count": len(manifest["reports"]),
            "reports": list(manifest["reports"]),
        }

    def _report_cache_metadata_copy(self) -> dict[str, Any]:
        metadata = dict(self._report_cache_metadata)
        checks = metadata["checks"]
        metadata["hit_rate"] = round(metadata["hits"] / checks, 4) if checks else None
        metadata["last_invalidation_reasons"] = list(self._report_cache_metadata["last_invalidation_reasons"])
        return metadata

    def _publish_report_scan(self, scan: dict[str, Any]) -> None:
        self._last_report_scan = scan
        _LAST_REPORT_SCAN.set(scan)

    def _current_report_scan(self) -> dict[str, Any]:
        return _LAST_REPORT_SCAN.get() or self._last_report_scan

    def _effective_report_scan_limits(self) -> dict[str, int]:
        limits = {
            "max_entries": self.report_scan_max_entries,
            "max_depth": self.report_scan_max_depth,
            "max_files": self.report_scan_max_files,
            "max_file_bytes": self.report_scan_max_file_bytes,
        }
        limits.update(_REPORT_SCAN_LIMIT_OVERRIDES.get() or {})
        return limits

    def _report_scan_limit_override_metadata(self) -> dict[str, int]:
        return {
            self.REPORT_SCAN_LIMIT_QUERY_KEYS[field]: value
            for field, value in (_REPORT_SCAN_LIMIT_OVERRIDES.get() or {}).items()
        }

    @contextmanager
    def report_scan_limit_overrides(self, overrides: dict[str, str | int] | None = None) -> Iterator[None]:
        normalized: dict[str, int] = {}
        for key, raw_value in (overrides or {}).items():
            if key not in self.REPORT_SCAN_OVERRIDE_MAXIMA:
                raise ValueError(f"unknown scan limit override: {key}")
            if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int)):
                raise ValueError(f"{key} must be an integer")
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            maximum = self.REPORT_SCAN_OVERRIDE_MAXIMA[key]
            if value < 1 or value > maximum:
                raise ValueError(f"{key} must be between 1 and {maximum}")
            normalized[self.REPORT_SCAN_LIMIT_FIELDS[key]] = value
        token = _REPORT_SCAN_LIMIT_OVERRIDES.set(normalized)
        try:
            yield
        finally:
            _REPORT_SCAN_LIMIT_OVERRIDES.reset(token)

    @staticmethod
    def _report_file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def scan_configuration(self) -> dict[str, Any]:
        with self._report_cache_lock:
            cache_metadata = self._report_cache_metadata_copy()
        effective_limits = self._effective_report_scan_limits()
        configured_limits = {
            "max_entries": self.report_scan_max_entries,
            "max_depth": self.report_scan_max_depth,
            "max_files": self.report_scan_max_files,
            "max_file_bytes": self.report_scan_max_file_bytes,
        }
        effective_benchmark_trees = [] if self.curated_report_manifest is not None else sorted(str(path) for path in self._benchmark_tree_roots())
        return {
            "root": str(self.reports),
            "selection_mode": "explicit_manifest" if self.curated_report_manifest is not None else "prefix_curation",
            "limits": effective_limits,
            "configured_limits": configured_limits,
            "limit_overrides": self._report_scan_limit_override_metadata(),
            "limit_override_maxima": dict(self.REPORT_SCAN_OVERRIDE_MAXIMA),
            "report_manifest": self._curated_report_manifest_metadata(),
            "benchmark_tree_prefixes": list(self.BENCHMARK_TREE_PREFIXES),
            "configured_benchmark_trees": [str(path) for path in self.benchmark_trees],
            "benchmark_trees": effective_benchmark_trees,
            "cache": cache_metadata,
        }

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    @staticmethod
    def _compact_role(value: Any, default_relation: str) -> dict[str, Any] | None:
        if isinstance(value, str):
            return {"skill_id": value, "relation": default_relation}
        if isinstance(value, dict) and isinstance(value.get("skill_id"), str):
            return {
                "skill_id": value["skill_id"],
                "relation": value.get("relation", default_relation),
                "confidence": value.get("confidence"),
            }
        return None

    def graph(self) -> dict[str, Any]:
        if not self.db.is_file():
            return {"ok": False, "error": f"index database does not exist: {self.db}", "nodes": [], "edges": [], "counts": {}}
        try:
            conn = self._connect_readonly(self.db)
            try:
                nodes = [
                    {
                        "id": row["skill_id"],
                        "name": row["name"],
                        "description": row["description"],
                        "domain": row["domain"],
                        "confidence": row["confidence"],
                        "tags": sorted(row["tags"].split(",")) if row["tags"] else [],
                    }
                    for row in conn.execute(
                        """
                        SELECT s.skill_id, s.name, s.description, s.domain, s.confidence,
                               COALESCE(group_concat(t.tag, ','), '') AS tags
                        FROM skills s LEFT JOIN skill_tags tag_rel ON tag_rel.skill_id=s.skill_id
                        LEFT JOIN tags t ON t.tag=tag_rel.tag
                        GROUP BY s.skill_id ORDER BY s.skill_id
                        """
                    )
                ]
                edges = [dict(row) for row in conn.execute("SELECT source, target, type, weight, note FROM edges ORDER BY type, source, target")]
                meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
            finally:
                conn.close()
            edge_types: dict[str, int] = {}
            for edge in edges:
                edge_types[edge["type"]] = edge_types.get(edge["type"], 0) + 1
            return {
                "ok": True,
                "meta": meta,
                "nodes": nodes,
                "edges": edges,
                "counts": {"skills": len(nodes), "edges": len(edges), "edge_types": edge_types},
            }
        except sqlite3.Error as exc:
            return {"ok": False, "error": f"cannot read index: {exc}", "nodes": [], "edges": [], "counts": {}}

    def journal(self, limit: int = 100) -> dict[str, Any]:
        if not self.journal_path.is_file():
            return {"ok": False, "error": f"journal does not exist: {self.journal_path}", "events": [], "routes": [], "counts": {}}
        try:
            conn = self._connect_readonly(self.journal_path)
            try:
                rows = conn.execute("SELECT * FROM journal_events ORDER BY sequence DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
                events = []
                for row in rows:
                    payload = json.loads(row["payload_json"])
                    provenance = json.loads(row["provenance_json"])
                    events.append({
                        "sequence": row["sequence"],
                        "event_id": row["event_id"],
                        "kind": row["kind"],
                        "parent_event_id": row["parent_event_id"],
                        "created_at": row["created_at"],
                        "payload": payload,
                        "provenance": provenance,
                        "status": payload.get("status") if isinstance(payload, dict) else None,
                    })
            finally:
                conn.close()
            routes: list[dict[str, Any]] = []
            for event in events:
                if event["kind"] != "decision":
                    continue
                payload = event["payload"] if isinstance(event["payload"], dict) else {}
                route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
                lead = self._compact_role(route.get("lead", payload.get("lead")), "lead")
                support = [self._compact_role(value, "support") for value in route.get("support", [])] if isinstance(route.get("support"), list) else []
                validator = self._compact_role(route.get("validator"), "validates")
                fallback = self._compact_role(route.get("fallback"), "fallback")
                routes.append({
                    "event_id": event["event_id"],
                    "created_at": event["created_at"],
                    "query_sha256": payload.get("query_sha256"),
                    "query_length": payload.get("query_length"),
                    "task_content": payload.get("task_content"),
                    "lead": lead,
                    "support": [item for item in support if item],
                    "validator": validator,
                    "fallback": fallback,
                    "calibration_policy": route.get("calibration_policy"),
                })
            counts: dict[str, int] = {}
            for event in events:
                counts[event["kind"]] = counts.get(event["kind"], 0) + 1
            outcome_counts: dict[str, int] = {}
            for event in events:
                if event["kind"] == "outcome" and event["status"]:
                    outcome_counts[event["status"]] = outcome_counts.get(event["status"], 0) + 1
            return {"ok": True, "events": events, "routes": routes, "counts": {**counts, **{f"outcome:{key}": value for key, value in outcome_counts.items()}}}
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"cannot read journal: {exc}", "events": [], "routes": [], "counts": {}}

    def _benchmark_tree_roots(self) -> set[Path]:
        roots = {path.resolve() for path in self.benchmark_trees}
        try:
            with os.scandir(self.reports) as entries:
                for entry in entries:
                    if entry.name.startswith(self.BENCHMARK_TREE_PREFIXES) and entry.is_dir(follow_symlinks=False):
                        roots.add(Path(entry.path).resolve())
        except OSError:
            pass
        return roots

    def skipped_benchmark_trees(self) -> dict[str, Any]:
        with self._benchmark_inventory_lock:
            started = time.perf_counter()
            selection_mode = "explicit_manifest" if self.curated_report_manifest is not None else "prefix_curation"
            configured = [(path.resolve(), path) for path in self.benchmark_trees]
            roots: dict[str, dict[str, Any]] = {}
            for resolved, original in configured:
                roots[str(resolved)] = {"path": resolved, "configured": True, "prefixes": []}
            try:
                with os.scandir(self.reports) as entries:
                    for entry in entries:
                        if not entry.name.startswith(self.BENCHMARK_TREE_PREFIXES) or not entry.is_dir(follow_symlinks=False):
                            continue
                        path = Path(entry.path)
                        resolved = path.resolve()
                        record = roots.setdefault(str(resolved), {"path": resolved, "configured": False, "prefixes": []})
                        record["prefixes"] = [prefix for prefix in self.BENCHMARK_TREE_PREFIXES if entry.name.startswith(prefix)]
            except OSError as exc:
                detection_error = str(exc)
            else:
                detection_error = None
            trees: list[dict[str, Any]] = []
            for record in sorted(roots.values(), key=lambda item: str(item["path"]).lower()):
                path = record["path"]
                sources = []
                if record["configured"]:
                    sources.append("configured")
                sources.extend(record["prefixes"])
                tree: dict[str, Any] = {
                    "path": str(path),
                    "name": path.name,
                    "exclusion_sources": sources,
                    "active": selection_mode == "prefix_curation",
                    "root_metadata_size_bytes": None,
                    "shallow_size_bytes": None,
                    "direct_entry_count": 0,
                    "direct_file_count": 0,
                    "direct_directory_count": 0,
                    "direct_symlink_or_junction_count": 0,
                    "direct_file_bytes": 0,
                    "modified_at": None,
                    "error": None,
                }
                is_link = path.is_symlink()
                is_junction = getattr(path, "is_junction", None)
                if callable(is_junction) and is_junction():
                    is_link = True
                if is_link:
                    tree["error"] = "unsafe_symlink_or_junction"
                    trees.append(tree)
                    continue
                try:
                    root_stat = path.stat(follow_symlinks=False)
                    tree["root_metadata_size_bytes"] = root_stat.st_size
                    tree["modified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(root_stat.st_mtime))
                    if not path.is_dir():
                        tree["error"] = "not_a_directory"
                        trees.append(tree)
                        continue
                    with os.scandir(path) as children:
                        for child in children:
                            tree["direct_entry_count"] += 1
                            try:
                                if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                                    tree["direct_symlink_or_junction_count"] += 1
                                elif child.is_dir(follow_symlinks=False):
                                    tree["direct_directory_count"] += 1
                                elif child.is_file(follow_symlinks=False):
                                    tree["direct_file_count"] += 1
                                    tree["direct_file_bytes"] += child.stat(follow_symlinks=False).st_size
                            except OSError:
                                tree["error"] = "partial_direct_entry_inventory"
                except OSError as exc:
                    tree["error"] = f"unreadable: {exc}"
                tree["shallow_size_bytes"] = (tree["root_metadata_size_bytes"] or 0) + tree["direct_file_bytes"]
                trees.append(tree)
            active_count = sum(1 for tree in trees if tree["active"] and tree["error"] is None)
            return {
                "ok": detection_error is None,
                "schema_version": 1,
                "scope": "skipped_benchmark_trees",
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "selection_mode": selection_mode,
                "recursive_traversal": False,
                "size_semantics": "root_metadata_plus_direct_child_file_bytes",
                "detection_error": detection_error,
                "counts": {
                    "trees": len(trees),
                    "active": active_count,
                    "inactive": len(trees) - active_count,
                    "errors": sum(1 for tree in trees if tree["error"] is not None),
                },
                "shallow_bytes": sum(tree["shallow_size_bytes"] or 0 for tree in trees),
                "trees": trees,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }

    def _report_cache_invalidation_reasons(self) -> list[str]:
        if self._report_cache is None:
            return list(self._pending_report_cache_invalidation_reasons) or ["cache_empty"]
        reasons: list[str] = []
        for directory, snapshot in self._report_cache.get("directories", {}).items():
            directory_path = Path(directory)
            try:
                if directory_path.stat(follow_symlinks=False).st_mtime_ns != snapshot["mtime_ns"]:
                    reasons.append(f"directory_changed:{directory}")
            except OSError:
                reasons.append(f"directory_unreadable:{directory}")
                continue
            for entry in snapshot.get("entries", []):
                if entry.get("benchmark"):
                    continue
                entry_path = Path(entry["path"])
                try:
                    stat = entry_path.stat(follow_symlinks=False)
                except OSError:
                    reasons.append(f"entry_unreadable:{entry['path']}")
                    continue
                if stat.st_mtime_ns != entry.get("mtime_ns") or stat.st_size != entry.get("size"):
                    reasons.append(f"entry_changed:{entry['path']}")
        if reasons:
            return reasons
        if self.cache_content_hash:
            content_hashes = self._report_cache.get("content_hashes", {})
            for cached_path in self._report_cache.get("files", []):
                expected_hash = content_hashes.get(cached_path)
                if expected_hash is None:
                    reasons.append(f"entry_content_hash_missing:{cached_path}")
                    continue
                try:
                    current_hash = self._report_file_sha256(Path(cached_path))
                except OSError:
                    reasons.append(f"entry_content_unreadable:{cached_path}")
                    continue
                if current_hash != expected_hash:
                    reasons.append(f"entry_content_changed:{cached_path}")
        return reasons

    def invalidate_report_cache(self, reason: str = "operator_request") -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 128:
            raise ValueError("cache invalidation reason must be a non-empty string up to 128 characters")
        normalized_reason = reason.strip()
        with self._report_cache_lock:
            invalidated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._report_cache = None
            self._pending_report_cache_invalidation_reasons = [normalized_reason]
            self._report_cache_metadata["status"] = "invalidated"
            self._report_cache_metadata["freshness"] = "unknown"
            self._report_cache_metadata["invalidations"] += 1
            self._report_cache_metadata["last_invalidated_at"] = invalidated_at
            self._report_cache_metadata["last_invalidation_reasons"] = [normalized_reason]
            self._report_cache_metadata["content_hashed_files"] = 0
            return {
                "ok": True,
                "invalidated": True,
                "reason": normalized_reason,
                "next_scan": {"counted_as": "miss", "expected_status": "rebuilt"},
                "cache": self._report_cache_metadata_copy(),
            }

    def _scan_report_files(self) -> tuple[list[Path], dict[str, Any]]:
        limit_overrides = self._report_scan_limit_override_metadata()
        with self._report_cache_lock:
            if limit_overrides:
                files, scan = self._scan_report_files_uncached()
                scan["request_limit_overrides"] = limit_overrides
                scan["content_hashed_files"] = 0
                scan["content_hash_errors"] = 0
                cache_metadata = self._report_cache_metadata_copy()
                cache_metadata["status"] = "bypassed"
                cache_metadata["freshness"] = "unknown"
                cache_metadata["bypassed_for_limit_overrides"] = True
                cache_metadata["limit_overrides"] = limit_overrides
                scan["cache"] = cache_metadata
                self._publish_report_scan(scan)
                return files, scan
            started = time.perf_counter()
            self._report_cache_metadata["checks"] += 1
            reasons = self._report_cache_invalidation_reasons()
            if self._report_cache is not None and not reasons:
                cached_scan = dict(self._report_cache["scan"])
                cached_scan.pop("cache", None)
                self._report_cache_metadata["status"] = "hit"
                self._report_cache_metadata["freshness"] = "fresh"
                self._report_cache_metadata["hits"] += 1
                self._report_cache_metadata["last_checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                cached_scan["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
                cached_scan["cache"] = self._report_cache_metadata_copy()
                self._publish_report_scan(cached_scan)
                return [Path(path) for path in self._report_cache["files"]], cached_scan
            status = "miss" if self._report_cache is None else "invalidated"
            if self._report_cache is not None:
                self._report_cache_metadata["invalidations"] += 1
            else:
                self._report_cache_metadata["misses"] += 1
            self._report_cache_metadata["last_invalidation_reasons"] = reasons
            self._report_cache_metadata["last_invalidated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            files, scan = self._scan_report_files_uncached()
            content_hashes: dict[str, str] = {}
            content_hash_errors = 0
            if self.cache_content_hash:
                for path in files:
                    try:
                        content_hashes[str(path)] = self._report_file_sha256(path)
                    except OSError:
                        content_hash_errors += 1
                if content_hash_errors:
                    self._last_report_cacheable = False
            scan["content_hashed_files"] = len(content_hashes)
            scan["content_hash_errors"] = content_hash_errors
            checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if self._last_report_cacheable:
                self._report_cache = {
                    "files": [str(path) for path in files],
                    "scan": dict(scan),
                    "directories": self._last_report_directory_cache,
                    "content_hashes": content_hashes,
                }
                self._report_cache_metadata["status"] = "rebuilt"
                self._report_cache_metadata["freshness"] = "fresh"
                self._report_cache_metadata["content_hashed_files"] = len(content_hashes)
                self._report_cache_metadata["last_rebuilt_at"] = checked_at
            else:
                self._report_cache = None
                self._report_cache_metadata["status"] = status
                self._report_cache_metadata["freshness"] = "unknown"
                self._report_cache_metadata["content_hashed_files"] = 0
            self._pending_report_cache_invalidation_reasons.clear()
            self._report_cache_metadata["last_checked_at"] = checked_at
            scan["cache"] = self._report_cache_metadata_copy()
            self._publish_report_scan(scan)
            return files, scan

    def _manifest_path_has_link(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.reports)
        except ValueError:
            return True
        current = self.reports
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return True
            is_junction = getattr(current, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
        return False

    def _scan_manifest_files_uncached(self, started: float) -> tuple[list[Path], dict[str, Any]]:
        limits = self._effective_report_scan_limits()
        manifest = self.curated_report_manifest or {}
        manifest_reports = manifest.get("reports", ())
        candidates: list[Path] = []
        missing: list[str] = []
        non_files: list[str] = []
        links: list[str] = []
        depth_limited: list[str] = []
        large: list[str] = []
        file_capped: list[str] = []
        entries_scanned = 0
        limit_reached = len(manifest_reports) > limits["max_entries"]
        for relative in manifest_reports[:limits["max_entries"]]:
            entries_scanned += 1
            path = self.reports.joinpath(*PurePosixPath(relative).parts)
            if self._manifest_path_has_link(path):
                links.append(relative)
                continue
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError:
                missing.append(relative)
                continue
            if not path.is_file():
                non_files.append(relative)
                continue
            if len(PurePosixPath(relative).parts) - 1 > limits["max_depth"]:
                depth_limited.append(relative)
                continue
            if stat.st_size > limits["max_file_bytes"]:
                large.append(relative)
                continue
            candidates.append(path)
        for relative in manifest_reports[limits["max_entries"]:]:
            file_capped.append(relative)
        files = candidates[:limits["max_files"]]
        file_capped.extend(path.relative_to(self.reports).as_posix() for path in candidates[limits["max_files"]:])
        directory_entries: dict[str, list[dict[str, Any]]] = {}
        for relative in manifest_reports:
            path = self.reports.joinpath(*PurePosixPath(relative).parts)
            parent = path.parent
            while not parent.exists() and parent != self.reports:
                parent = parent.parent
            directory_entries.setdefault(str(parent.resolve()), [])
            try:
                stat = path.stat(follow_symlinks=False)
                directory_entries[str(parent.resolve())].append({"path": str(path), "kind": "file", "mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "benchmark": False})
            except OSError:
                pass
        directory_cache: dict[str, Any] = {}
        for directory, entries in directory_entries.items():
            try:
                stat = Path(directory).stat(follow_symlinks=False)
                directory_cache[directory] = {"mtime_ns": stat.st_mtime_ns, "entries": entries}
            except OSError:
                pass
        scan = {
            "root": str(self.reports),
            "selection_mode": "explicit_manifest",
            "curated_only": True,
            "report_manifest": self._curated_report_manifest_metadata(),
            "benchmark_roots": [],
            "configured_benchmark_trees": [str(path) for path in self.benchmark_trees],
            "skipped_benchmark_trees": 0,
            "skipped_benchmark_tree_names": [],
            "entries_scanned": entries_scanned,
            "directories_seen": len(directory_cache),
            "files_considered": len(candidates),
            "files_returned": len(files),
            "skipped_links": len(links),
            "skipped_large": len(large),
            "depth_limited": len(depth_limited),
            "errors": len(missing) + len(non_files),
            "invalid_json": 0,
            "non_object_documents": 0,
            "truncated": limit_reached,
            "max_entries": limits["max_entries"],
            "max_depth": limits["max_depth"],
            "max_files": limits["max_files"],
            "max_file_bytes": limits["max_file_bytes"],
            "manifest_missing": missing,
            "manifest_non_files": non_files,
            "manifest_links": links,
            "manifest_depth_limited": depth_limited,
            "manifest_large": large,
            "manifest_file_capped": file_capped,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        self._last_report_directory_cache = directory_cache
        self._last_report_cacheable = not limit_reached
        self._publish_report_scan(scan)
        return files, scan

    def _scan_report_files_uncached(self) -> tuple[list[Path], dict[str, Any]]:
        started = time.perf_counter()
        if self.curated_report_manifest is not None:
            return self._scan_manifest_files_uncached(started)
        limits = self._effective_report_scan_limits()
        candidates: list[tuple[float, Path]] = []
        directory_cache: dict[str, Any] = {}
        pending: list[tuple[Path, int]] = [(self.reports, 0)]
        benchmark_roots = self._benchmark_tree_roots()
        scanned_entries = 0
        directories_seen = 0
        skipped_links = 0
        skipped_large = 0
        depth_limited = 0
        skipped_benchmark_trees = 0
        skipped_benchmark_tree_names: list[str] = []
        errors = 0
        limit_reached = False
        while pending and scanned_entries < limits["max_entries"]:
            directory, depth = pending.pop()
            try:
                directory_stat = directory.stat(follow_symlinks=False)
                directory_entries: list[dict[str, Any]] = []
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if scanned_entries >= limits["max_entries"]:
                            limit_reached = True
                            break
                        scanned_entries += 1
                        try:
                            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                                skipped_links += 1
                                continue
                            entry_path = Path(entry.path)
                            if entry.is_dir(follow_symlinks=False):
                                directories_seen += 1
                                stat = entry.stat(follow_symlinks=False)
                                is_benchmark_tree = entry_path.resolve() in benchmark_roots
                                directory_entries.append({"path": str(entry_path.resolve()), "kind": "directory", "mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "benchmark": is_benchmark_tree})
                                if is_benchmark_tree:
                                    skipped_benchmark_trees += 1
                                    skipped_benchmark_tree_names.append(entry.name)
                                    continue
                                if depth < limits["max_depth"]:
                                    pending.append((Path(entry.path), depth + 1))
                                else:
                                    depth_limited += 1
                            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                                stat = entry.stat(follow_symlinks=False)
                                directory_entries.append({"path": str(entry_path.resolve()), "kind": "file", "mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "benchmark": False})
                                if stat.st_size > limits["max_file_bytes"]:
                                    skipped_large += 1
                                else:
                                    candidates.append((stat.st_mtime, Path(entry.path)))
                        except OSError:
                            errors += 1
                    if scanned_entries >= limits["max_entries"]:
                        limit_reached = True
                directory_cache[str(directory.resolve())] = {"mtime_ns": directory_stat.st_mtime_ns, "entries": directory_entries}
            except OSError:
                errors += 1
        files = [path for _, path in sorted(candidates, key=lambda item: item[0], reverse=True)[:limits["max_files"]]]
        scan = {
            "root": str(self.reports),
            "selection_mode": "prefix_curation",
            "curated_only": True,
            "benchmark_roots": sorted(str(path) for path in benchmark_roots),
            "skipped_benchmark_trees": skipped_benchmark_trees,
            "skipped_benchmark_tree_names": sorted(skipped_benchmark_tree_names),
            "entries_scanned": scanned_entries,
            "directories_seen": directories_seen,
            "files_considered": len(candidates),
            "files_returned": len(files),
            "skipped_links": skipped_links,
            "skipped_large": skipped_large,
            "depth_limited": depth_limited,
            "errors": errors,
            "invalid_json": 0,
            "non_object_documents": 0,
            "truncated": limit_reached,
            "max_entries": limits["max_entries"],
            "max_depth": limits["max_depth"],
            "max_files": limits["max_files"],
            "max_file_bytes": limits["max_file_bytes"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        self._last_report_directory_cache = directory_cache
        self._last_report_cacheable = not limit_reached
        self._publish_report_scan(scan)
        return files, scan

    def dry_run_scan(self) -> dict[str, Any]:
        with self._report_cache_lock:
            return self._dry_run_scan_locked()

    def _dry_run_manifest_scan_locked(self, started: float) -> dict[str, Any]:
        limits = self._effective_report_scan_limits()
        manifest = self.curated_report_manifest or {}
        manifest_reports = manifest.get("reports", ())
        decisions: dict[str, list[dict[str, Any]]] = {"included": [], "skipped": [], "capped": [], "rejected": []}
        candidates: list[tuple[str, Path, int]] = []
        directories_seen: set[str] = set()
        entries_scanned = 0
        errors = 0
        for relative in manifest_reports:
            path = self.reports.joinpath(*PurePosixPath(relative).parts)
            if entries_scanned >= limits["max_entries"]:
                decisions["capped"].append({"path": relative, "kind": "file", "reason": "max_entries", "limit": limits["max_entries"]})
                continue
            entries_scanned += 1
            if self._manifest_path_has_link(path):
                decisions["skipped"].append({"path": relative, "kind": "link_or_junction", "reason": "symlink_or_junction"})
                continue
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError:
                errors += 1
                decisions["rejected"].append({"path": relative, "kind": "file", "reason": "file_missing_or_unreadable"})
                continue
            if not path.is_file():
                errors += 1
                decisions["rejected"].append({"path": relative, "kind": "entry", "reason": "not_a_regular_file"})
                continue
            directories_seen.add(str(path.parent.resolve()))
            depth = len(PurePosixPath(relative).parts) - 1
            if depth > limits["max_depth"]:
                decisions["capped"].append({"path": relative, "kind": "file", "reason": "max_depth", "limit": limits["max_depth"]})
                continue
            if stat.st_size > limits["max_file_bytes"]:
                decisions["rejected"].append({"path": relative, "kind": "file", "reason": "max_file_bytes", "limit": limits["max_file_bytes"], "size": stat.st_size})
                continue
            candidates.append((relative, path, stat.st_size))
        selected = candidates[:limits["max_files"]]
        for relative, _, size in candidates[limits["max_files"]:]:
            decisions["capped"].append({"path": relative, "kind": "file", "reason": "max_files", "limit": limits["max_files"], "size": size})
        for relative, path, size in selected:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                decisions["rejected"].append({"path": relative, "kind": "file", "reason": "invalid_utf8", "size": size})
                continue
            except json.JSONDecodeError as exc:
                decisions["rejected"].append({"path": relative, "kind": "file", "reason": "invalid_json", "size": size, "line": exc.lineno, "column": exc.colno})
                continue
            except OSError:
                errors += 1
                decisions["rejected"].append({"path": relative, "kind": "file", "reason": "file_unreadable", "size": size})
                continue
            if isinstance(document, dict):
                decisions["included"].append({"path": relative, "kind": "file", "reason": "valid_manifest_json_object", "size": size})
            else:
                decisions["rejected"].append({"path": relative, "kind": "file", "reason": "non_object_document", "size": size})
        for paths in decisions.values():
            paths.sort(key=lambda item: item["path"])
        counts = {name: len(paths) for name, paths in decisions.items()}
        max_entries_reached = len(manifest_reports) > limits["max_entries"]
        return {
            "ok": True,
            "schema_version": 1,
            "dry_run": True,
            "selection_mode": "explicit_manifest",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": str(self.reports),
            "report_manifest": self._curated_report_manifest_metadata(),
            "effective_limits": limits,
            "configured_limits": {
                "max_entries": self.report_scan_max_entries,
                "max_depth": self.report_scan_max_depth,
                "max_files": self.report_scan_max_files,
                "max_file_bytes": self.report_scan_max_file_bytes,
            },
            "limit_overrides": self._report_scan_limit_override_metadata(),
            "benchmark_roots": [],
            "configured_benchmark_trees": [str(path) for path in self.benchmark_trees],
            "entries_scanned": entries_scanned,
            "directories_seen": len(directories_seen),
            "candidates": len(candidates),
            "manifest_report_count": len(manifest_reports),
            "unlisted_paths_enumerated": False,
            "errors": errors,
            "max_entries_reached": max_entries_reached,
            "truncated": max_entries_reached,
            "unseen_paths_enumerated": not max_entries_reached,
            "counts": {**counts, "total": sum(counts.values())},
            "paths": decisions,
            "cache": {"status": "bypassed", "reason": "dry_run"},
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def _dry_run_scan_locked(self) -> dict[str, Any]:
        started = time.perf_counter()
        if self.curated_report_manifest is not None:
            return self._dry_run_manifest_scan_locked(started)
        limits = self._effective_report_scan_limits()
        decisions: dict[str, list[dict[str, Any]]] = {"included": [], "skipped": [], "capped": [], "rejected": []}
        candidates: list[tuple[float, Path, int]] = []
        pending: list[tuple[Path, int]] = [(self.reports, 0)]
        benchmark_roots = self._benchmark_tree_roots()
        entries_scanned = 0
        directories_seen = 0
        errors = 0
        max_entries_reached = False

        while pending and entries_scanned < limits["max_entries"]:
            directory, depth = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        entry_path = Path(entry.path)
                        if entries_scanned >= limits["max_entries"]:
                            decisions["capped"].append({"path": str(entry_path), "kind": "entry", "reason": "max_entries", "limit": limits["max_entries"]})
                            max_entries_reached = True
                            break
                        entries_scanned += 1
                        try:
                            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                                decisions["skipped"].append({"path": str(entry_path), "kind": "link_or_junction", "reason": "symlink_or_junction"})
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                directories_seen += 1
                                stat = entry.stat(follow_symlinks=False)
                                is_benchmark_tree = entry_path.resolve() in benchmark_roots
                                if is_benchmark_tree:
                                    decisions["skipped"].append({"path": str(entry_path), "kind": "directory", "reason": "benchmark_tree"})
                                elif depth >= limits["max_depth"]:
                                    decisions["capped"].append({"path": str(entry_path), "kind": "directory", "reason": "max_depth", "limit": limits["max_depth"]})
                                else:
                                    pending.append((entry_path, depth + 1))
                            elif entry.is_file(follow_symlinks=False):
                                stat = entry.stat(follow_symlinks=False)
                                if not entry.name.endswith(".json"):
                                    decisions["skipped"].append({"path": str(entry_path), "kind": "file", "reason": "non_report_extension", "size": stat.st_size})
                                elif stat.st_size > limits["max_file_bytes"]:
                                    decisions["rejected"].append({"path": str(entry_path), "kind": "file", "reason": "max_file_bytes", "limit": limits["max_file_bytes"], "size": stat.st_size})
                                else:
                                    candidates.append((stat.st_mtime, entry_path, stat.st_size))
                            else:
                                decisions["skipped"].append({"path": str(entry_path), "kind": "other", "reason": "unsupported_entry_type"})
                        except OSError:
                            errors += 1
                            decisions["rejected"].append({"path": str(entry_path), "kind": "entry", "reason": "metadata_unreadable"})
                    if entries_scanned >= limits["max_entries"]:
                        max_entries_reached = True
            except OSError:
                errors += 1
                decisions["rejected"].append({"path": str(directory), "kind": "directory", "reason": "directory_unreadable"})

        if pending:
            max_entries_reached = True
            for directory, _ in pending:
                decisions["capped"].append({"path": str(directory), "kind": "directory", "reason": "max_entries", "limit": limits["max_entries"]})

        ordered_candidates = sorted(candidates, key=lambda item: (item[0], str(item[1])), reverse=True)
        selected = ordered_candidates[:limits["max_files"]]
        for _, path, size in ordered_candidates[limits["max_files"]:]:
            decisions["capped"].append({"path": str(path), "kind": "file", "reason": "max_files", "limit": limits["max_files"], "size": size})
        for _, path, size in selected:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                decisions["rejected"].append({"path": str(path), "kind": "file", "reason": "invalid_utf8", "size": size})
                continue
            except json.JSONDecodeError as exc:
                decisions["rejected"].append({"path": str(path), "kind": "file", "reason": "invalid_json", "size": size, "line": exc.lineno, "column": exc.colno})
                continue
            except OSError:
                errors += 1
                decisions["rejected"].append({"path": str(path), "kind": "file", "reason": "file_unreadable", "size": size})
                continue
            if isinstance(document, dict):
                decisions["included"].append({"path": str(path), "kind": "file", "reason": "valid_json_object", "size": size})
            else:
                decisions["rejected"].append({"path": str(path), "kind": "file", "reason": "non_object_document", "size": size})

        for paths in decisions.values():
            paths.sort(key=lambda item: item["path"])
        counts = {name: len(paths) for name, paths in decisions.items()}
        return {
            "ok": True,
            "schema_version": 1,
            "dry_run": True,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": str(self.reports),
            "selection_mode": "prefix_curation",
            "report_manifest": self._curated_report_manifest_metadata(),
            "unlisted_paths_enumerated": True,
            "effective_limits": limits,
            "configured_limits": {
                "max_entries": self.report_scan_max_entries,
                "max_depth": self.report_scan_max_depth,
                "max_files": self.report_scan_max_files,
                "max_file_bytes": self.report_scan_max_file_bytes,
            },
            "limit_overrides": self._report_scan_limit_override_metadata(),
            "benchmark_roots": sorted(str(path) for path in benchmark_roots),
            "entries_scanned": entries_scanned,
            "directories_seen": directories_seen,
            "candidates": len(candidates),
            "errors": errors,
            "max_entries_reached": max_entries_reached,
            "truncated": max_entries_reached,
            "unseen_paths_enumerated": not max_entries_reached,
            "counts": {**counts, "total": sum(counts.values())},
            "paths": decisions,
            "cache": {"status": "bypassed", "reason": "dry_run"},
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def _report_files(self) -> list[Path]:
        files, _ = self._scan_report_files()
        return files

    def _report_documents(self) -> list[tuple[Path, dict[str, Any]]]:
        documents: list[tuple[Path, dict[str, Any]]] = []
        files, scan = self._scan_report_files()
        for path in files:
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                scan["invalid_json"] += 1
                continue
            except OSError:
                scan["errors"] += 1
                continue
            if isinstance(report, dict):
                documents.append((path, report))
            else:
                scan["non_object_documents"] += 1
        self._publish_report_scan(scan)
        return documents

    def calibration(self, documents: list[tuple[Path, dict[str, Any]]] | None = None) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        for path, report in (self._report_documents() if documents is None else documents):
            calibration = report.get("calibration") if isinstance(report, dict) else None
            if not isinstance(calibration, dict) or not isinstance(calibration.get("global_policy"), dict):
                continue
            global_policy = calibration["global_policy"]
            domain_policies = calibration.get("domain_policies", {}) if isinstance(calibration.get("domain_policies", {}), dict) else {}
            reports.append({
                "path": str(path),
                "name": path.name,
                "created_at": report.get("created_at"),
                "global_policy": {
                    "threshold": global_policy.get("threshold"),
                    "samples": global_policy.get("samples"),
                    "eligible": global_policy.get("eligible"),
                    "selected_wilson_lower": global_policy.get("selected_wilson_lower"),
                    "observed_score": global_policy.get("observed_score"),
                },
                "domain_policies": {
                    name: {"threshold": policy.get("threshold"), "samples": policy.get("samples"), "eligible": policy.get("eligible"), "selected_wilson_lower": policy.get("selected_wilson_lower")}
                    for name, policy in sorted(domain_policies.items()) if isinstance(policy, dict)
                },
                "temporal_drift": report.get("temporal_drift"),
                "heldout_metrics": report.get("heldout", {}).get("metrics") if isinstance(report.get("heldout"), dict) else None,
                "policy_source": report.get("policy_source"),
            })
        return {"ok": True, "scan": dict(self._current_report_scan()), "reports": reports, "latest": reports[0] if reports else None}

    def curated_reports(self, documents: list[tuple[Path, dict[str, Any]]] | None = None) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        benchmark_documents_separated = 0
        for path, report in (self._report_documents() if documents is None else documents):
            if isinstance(report.get("benchmark"), str):
                benchmark_documents_separated += 1
                continue
            report_type = report.get("report") if isinstance(report.get("report"), str) else "untyped"
            action_items = report.get("action_items") if isinstance(report.get("action_items"), list) else []
            reports.append({
                "path": str(path),
                "name": path.name,
                "report_type": report_type,
                "created_at": report.get("created_at"),
                "schema_version": report.get("schema_version"),
                "read_only": report.get("read_only", True),
                "period": report.get("period", {}),
                "action_item_count": len(action_items),
                "has_calibration": isinstance(report.get("calibration"), dict),
            })
        scan = dict(self._current_report_scan())
        scan["scope"] = "curated_reports"
        scan["independent_from_benchmark_scan"] = True
        return {
            "ok": True,
            "schema_version": 1,
            "scope": "curated_reports",
            "status": "ready" if reports else "no_reports",
            "selection_mode": scan.get("selection_mode", "prefix_curation"),
            "scan": scan,
            "benchmark_documents_separated": benchmark_documents_separated,
            "reports": reports,
            "latest": reports[0] if reports else None,
            "counts": {"reports": len(reports), "benchmark_documents_separated": benchmark_documents_separated},
        }

    def _scan_benchmark_report_files(self) -> tuple[list[Path], dict[str, Any]]:
        started = time.perf_counter()
        limits = self._effective_report_scan_limits()
        roots = sorted(self._benchmark_tree_roots(), key=lambda path: str(path).lower())
        root_keys = {str(path) for path in roots}
        missing_roots = [str(path) for path in roots if not path.is_dir()]
        pending: list[tuple[Path, int]] = []
        queued_root_keys: set[str] = set()
        visited_directories: set[str] = set()
        candidates: list[tuple[float, Path, int]] = []
        entries_scanned = 0
        directories_seen = 0
        skipped_links = 0
        skipped_large = 0
        skipped_non_json = 0
        unscoped_top_level_entries = 0
        depth_limited = 0
        errors = 0
        limit_reached = False
        try:
            with os.scandir(self.reports) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    entry_path = Path(entry.path)
                    try:
                        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                            if entry.name.endswith(".json"):
                                skipped_links += 1
                            continue
                        if entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                            if entries_scanned >= limits["max_entries"]:
                                limit_reached = True
                                break
                            entries_scanned += 1
                            stat = entry.stat(follow_symlinks=False)
                            if stat.st_size > limits["max_file_bytes"]:
                                skipped_large += 1
                            else:
                                candidates.append((stat.st_mtime, entry_path, stat.st_size))
                        elif entry.is_dir(follow_symlinks=False) and str(entry_path.resolve()) in root_keys:
                            if entries_scanned >= limits["max_entries"]:
                                limit_reached = True
                                break
                            entries_scanned += 1
                            pending.append((entry_path, 0))
                            queued_root_keys.add(str(entry_path.resolve()))
                        else:
                            unscoped_top_level_entries += 1
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
        for root in roots:
            root_key = str(root)
            if root.is_dir() and root_key not in queued_root_keys:
                pending.append((root, 0))
        while pending and entries_scanned < limits["max_entries"]:
            directory, depth = pending.pop(0)
            directory_key = str(directory.resolve())
            if directory_key in visited_directories:
                continue
            visited_directories.add(directory_key)
            directories_seen += 1
            try:
                with os.scandir(directory) as entries:
                    for entry in sorted(entries, key=lambda item: item.name):
                        entry_path = Path(entry.path)
                        if entries_scanned >= limits["max_entries"]:
                            limit_reached = True
                            break
                        entries_scanned += 1
                        try:
                            if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                                skipped_links += 1
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                directories_seen += 1
                                if depth < limits["max_depth"]:
                                    pending.append((entry_path, depth + 1))
                                else:
                                    depth_limited += 1
                            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                                stat = entry.stat(follow_symlinks=False)
                                if stat.st_size > limits["max_file_bytes"]:
                                    skipped_large += 1
                                else:
                                    candidates.append((stat.st_mtime, entry_path, stat.st_size))
                            else:
                                skipped_non_json += 1
                        except OSError:
                            errors += 1
            except OSError:
                errors += 1
        if pending:
            limit_reached = True
        ordered = sorted(candidates, key=lambda item: (item[0], str(item[1])), reverse=True)
        files = [path for _, path, _ in ordered[:limits["max_files"]]]
        file_capped = [str(path) for _, path, _ in ordered[limits["max_files"]:]]
        return files, {
            "scope": "benchmark_reports",
            "independent_from_curated_scan": True,
            "root": str(self.reports),
            "benchmark_roots": [str(path) for path in roots],
            "missing_benchmark_roots": missing_roots,
            "entries_scanned": entries_scanned,
            "directories_seen": directories_seen,
            "files_considered": len(candidates),
            "files_returned": len(files),
            "skipped_links": skipped_links,
            "skipped_large": skipped_large,
            "skipped_non_json": skipped_non_json,
            "unscoped_top_level_entries": unscoped_top_level_entries,
            "depth_limited": depth_limited,
            "file_capped": file_capped,
            "errors": errors,
            "truncated": limit_reached,
            "max_entries": limits["max_entries"],
            "max_depth": limits["max_depth"],
            "max_files": limits["max_files"],
            "max_file_bytes": limits["max_file_bytes"],
            "cache": {"status": "independent", "shared_with_curated_scan": False},
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def benchmarks(self, documents: list[tuple[Path, dict[str, Any]]] | None = None) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        with self._benchmark_scan_lock:
            files, scan = self._scan_benchmark_report_files()
            for path in files:
                try:
                    report = json.loads(path.read_text(encoding="utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    scan["invalid_json"] = scan.get("invalid_json", 0) + 1
                    continue
                except OSError:
                    scan["errors"] += 1
                    continue
                if not isinstance(report, dict):
                    scan["non_object_documents"] = scan.get("non_object_documents", 0) + 1
                    continue
                if not isinstance(report.get("benchmark"), str):
                    scan["non_benchmark_documents"] = scan.get("non_benchmark_documents", 0) + 1
                    continue
                results = report.get("results") if isinstance(report.get("results"), list) else []
                reports.append({
                    "path": str(path),
                    "name": path.name,
                    "benchmark": report["benchmark"],
                    "created_at": report.get("created_at"),
                    "passed": report.get("passed", report.get("ok")),
                    "total_seconds": report.get("total_seconds"),
                    "cases": len(results),
                    "sizes": [item.get("count") for item in results if isinstance(item, dict) and item.get("count") is not None],
                    "speedups": [item.get("speedup_vs_full") for item in results if isinstance(item, dict) and item.get("speedup_vs_full") is not None],
                    "statuses": [item.get("status", "completed") for item in results if isinstance(item, dict)],
                    "resource_policy": report.get("resource_policy"),
                })
            scan["benchmark_reports"] = len(reports)
        return {"ok": True, "scan": scan, "reports": reports, "latest": reports[0] if reports else None}

    def _report_identity(self, path: Path, report: dict[str, Any]) -> str:
        try:
            source_name = path.relative_to(self.reports).as_posix()
        except ValueError:
            source_name = path.name
        period = report.get("period") if isinstance(report.get("period"), dict) else {}
        start = period.get("start") if isinstance(period.get("start"), str) else "unknown"
        end = period.get("end") if isinstance(period.get("end"), str) else "unknown"
        return f"{source_name}::{start}::{end}"

    def _read_action_state(self) -> dict[str, Any]:
        if not self.action_state.exists():
            return {
                "schema_version": self.ACTION_STATE_SCHEMA_VERSION,
                "kind": self.ACTION_STATE_KIND,
                "updated_at": None,
                "items": {},
            }
        try:
            state = json.loads(self.action_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read action state: {exc}") from exc
        if not isinstance(state, dict) or state.get("schema_version") != self.ACTION_STATE_SCHEMA_VERSION or state.get("kind") != self.ACTION_STATE_KIND or not isinstance(state.get("items"), dict):
            raise ValueError("action state has an unsupported or invalid schema")
        for report_id, entries in state["items"].items():
            if not isinstance(report_id, str) or not isinstance(entries, dict):
                raise ValueError("action state contains an invalid report entry")
            for action_id, entry in entries.items():
                if not isinstance(action_id, str) or not isinstance(entry, dict) or entry.get("status") not in self.ACTION_STATUSES:
                    raise ValueError("action state contains an invalid action entry")
                note = entry.get("operator_note")
                actor = entry.get("actor")
                if note is not None and (not isinstance(note, str) or not note.strip() or len(note) > self.OPERATOR_NOTE_MAX_LENGTH):
                    raise ValueError("action state contains an invalid operator note")
                if actor is not None and (not isinstance(actor, str) or not actor.strip() or len(actor) > self.ACTOR_MAX_LENGTH):
                    raise ValueError("action state contains an invalid actor identity")
                if entry.get("status") == "reopened" and not note:
                    raise ValueError("reopened action state requires an operator note")
        return state

    def _write_action_state(self, state: dict[str, Any]) -> None:
        self.action_state.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.action_state.parent,
                prefix=f".{self.action_state.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.action_state)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def set_action_status(self, report_id: str, action_id: str, status: str, operator_note: str | None = None, actor: str | None = None) -> dict[str, Any]:
        if not isinstance(report_id, str) or not report_id or len(report_id) > 1_024:
            raise ValueError("report_id must be a non-empty string")
        if not isinstance(action_id, str) or not action_id or len(action_id) > 256:
            raise ValueError("action_id must be a non-empty string")
        if status not in self.ACTION_MUTATION_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(self.ACTION_MUTATION_STATUSES)}")
        if operator_note is not None:
            if not isinstance(operator_note, str) or not operator_note.strip():
                raise ValueError("operator_note must be a non-empty string when provided")
            if len(operator_note) > self.OPERATOR_NOTE_MAX_LENGTH:
                raise ValueError(f"operator_note must be at most {self.OPERATOR_NOTE_MAX_LENGTH} characters")
            operator_note = operator_note.strip()
        elif status == "reopen":
            raise ValueError("operator_note is required when reopening an action")
        if actor is not None:
            if not isinstance(actor, str) or not actor.strip():
                raise ValueError("actor must be a non-empty string when provided")
            if len(actor) > self.ACTOR_MAX_LENGTH:
                raise ValueError(f"actor must be at most {self.ACTOR_MAX_LENGTH} characters")
            actor = actor.strip()
        with self._action_state_lock:
            weekly = self.weekly()
            if weekly.get("state_error"):
                raise ValueError(weekly["state_error"])
            match = next((report for report in weekly.get("reports", []) if report.get("report_id") == report_id), None)
            current_item = next((item for item in match.get("action_items", []) if item.get("id") == action_id), None) if match else None
            if current_item is None:
                raise ValueError("action item is not present in the selected report")
            if status == "reopen" and current_item.get("status") not in {"acknowledged", "resolved"}:
                raise ValueError("only acknowledged or resolved actions can be reopened")
            source_paths = {Path(report["path"]).resolve() for report in weekly.get("reports", [])}
            source_paths.update((self.db.resolve(), self.journal_path.resolve()))
            if self.action_state.resolve() in source_paths:
                raise ValueError("action state path cannot overwrite a source artifact")
            state = self._read_action_state()
            updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            persisted_status = "reopened" if status == "reopen" else status
            entry: dict[str, Any] = {"status": persisted_status, "updated_at": updated_at}
            if operator_note is not None:
                entry["operator_note"] = operator_note
            if actor is not None:
                entry["actor"] = actor
            state["updated_at"] = updated_at
            state["items"].setdefault(report_id, {})[action_id] = entry
            self._write_action_state(state)
            result = {"ok": True, "report_id": report_id, "action_id": action_id, "status": persisted_status, "updated_at": updated_at}
            if operator_note is not None:
                result["operator_note"] = operator_note
            if actor is not None:
                result["actor"] = actor
            return result

    @staticmethod
    def _parse_timestamp(value: Any) -> dt.datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip()
        if len(normalized) == 10:
            normalized += "T00:00:00+00:00"
        try:
            parsed = dt.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)

    def _report_freshness(self, path: Path, report: dict[str, Any], journal_head_at: str | None) -> dict[str, Any]:
        period = report.get("period") if isinstance(report.get("period"), dict) else {}
        period_end = period.get("end") if isinstance(period.get("end"), str) else None
        report_modified_at: str | None = None
        try:
            report_modified_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
        except OSError:
            pass
        period_value = self._parse_timestamp(period_end)
        journal_value = self._parse_timestamp(journal_head_at)
        modified_value = self._parse_timestamp(report_modified_at)
        period_vs_journal = "unknown"
        file_vs_journal = "unknown"
        reasons: list[str] = []
        if period_value is not None and journal_value is not None:
            period_vs_journal = "behind" if period_value < journal_value else "ahead" if period_value > journal_value else "equal"
        else:
            reasons.append("report_period_or_journal_head_unavailable")
        if modified_value is not None and journal_value is not None:
            file_vs_journal = "older" if modified_value < journal_value else "newer" if modified_value > journal_value else "equal"
        else:
            reasons.append("report_file_mtime_or_journal_head_unavailable")
        if period_vs_journal == "behind":
            reasons.append("report_period_precedes_journal_head")
        if file_vs_journal == "older":
            reasons.append("report_file_predates_journal_head")
        status = "stale" if "report_period_precedes_journal_head" in reasons or "report_file_predates_journal_head" in reasons else "fresh" if not reasons else "unknown"
        return {
            "status": status,
            "report_period_end": period_end,
            "report_modified_at": report_modified_at,
            "journal_head_at": journal_head_at,
            "period_vs_journal_head": period_vs_journal,
            "file_vs_journal_head": file_vs_journal,
            "reasons": reasons,
        }

    @staticmethod
    def _affected_skills(item: dict[str, Any]) -> list[str]:
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        values: list[Any] = []
        for source in (item, evidence):
            for key in ("affected_skills", "skill_ids", "skills"):
                candidate = source.get(key)
                if isinstance(candidate, list):
                    values.extend(candidate)
            for key in ("skill_id", "lead_skill"):
                candidate = source.get(key)
                if isinstance(candidate, str):
                    values.append(candidate)
        by_skill = evidence.get("by_skill")
        if isinstance(by_skill, dict):
            values.extend(by_skill.keys())
        result = {
            value.get("skill_id") if isinstance(value, dict) else value
            for value in values
            if isinstance(value, str) or (isinstance(value, dict) and isinstance(value.get("skill_id"), str))
        }
        return sorted(result)

    def weekly(self, documents: list[tuple[Path, dict[str, Any]]] | None = None) -> dict[str, Any]:
        reports: list[dict[str, Any]] = []
        journal_snapshot = self.journal(1)
        journal_events = journal_snapshot.get("events", []) if isinstance(journal_snapshot.get("events"), list) else []
        journal_head_at = journal_events[0].get("created_at") if journal_events and isinstance(journal_events[0], dict) else None
        try:
            action_state = self._read_action_state()
            state_error = None
        except ValueError as exc:
            action_state = {"items": {}}
            state_error = str(exc)
        for path, report in (self._report_documents() if documents is None else documents):
            if report.get("report") != "weekly-operations":
                continue
            raw_items = report.get("action_items")
            if not isinstance(raw_items, list):
                continue
            report_id = self._report_identity(path, report)
            report_entries = action_state.get("items", {}).get(report_id, {})
            action_items: list[dict[str, Any]] = []
            by_priority: dict[str, int] = {}
            by_status: dict[str, int] = {}
            report_skills: set[str] = set()
            open_items = 0
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item.setdefault("status", "open")
                item["report_id"] = report_id
                item["affected_skills"] = self._affected_skills(item)
                report_skills.update(item["affected_skills"])
                overlay = report_entries.get(item.get("id")) if isinstance(item.get("id"), str) else None
                if overlay:
                    item["source_status"] = item["status"]
                    item["operator_status"] = overlay["status"]
                    item["status"] = "open" if overlay["status"] == "reopened" else overlay["status"]
                    item["status_updated_at"] = overlay.get("updated_at")
                    item["status_source"] = "operator"
                    if overlay.get("operator_note") is not None:
                        item["operator_note"] = overlay["operator_note"]
                    if overlay.get("actor") is not None:
                        item["actor"] = overlay["actor"]
                else:
                    item["status_source"] = "report"
                status = item["status"] if isinstance(item.get("status"), str) else "open"
                by_status[status] = by_status.get(status, 0) + 1
                if status == "open":
                    open_items += 1
                priority = item.get("priority") if isinstance(item.get("priority"), str) else "low"
                by_priority[priority] = by_priority.get(priority, 0) + 1
                action_items.append(item)
            reports.append({
                "path": str(path),
                "name": path.name,
                "report_id": report_id,
                "period": report.get("period", {}),
                "action_items": action_items,
                "counts": {"action_items": len(action_items), "open_items": open_items, "by_priority": dict(sorted(by_priority.items()))},
                "status_counts": dict(sorted(by_status.items())),
                "affected_skills": sorted(report_skills),
                "freshness": self._report_freshness(path, report, journal_head_at),
                "read_only": report.get("read_only", True),
            })
        latest = reports[0] if reports else None
        return {
            "ok": True,
            "status": "ready" if latest else "no_reports",
            "scan": dict(self._current_report_scan()),
            "action_state": {"path": str(self.action_state), "exists": self.action_state.exists(), "updated_at": action_state.get("updated_at"), "error": state_error},
            "reports": reports,
            "latest": latest,
            "journal_head_at": journal_head_at,
            "freshness": latest.get("freshness") if latest else None,
            "counts": latest["counts"] if latest else {"reports": 0, "action_items": 0, "open_items": 0, "by_priority": {}},
        }

    def overview(self) -> dict[str, Any]:
        graph = self.graph()
        journal = self.journal(20)
        documents = self._report_documents()
        calibration = self.calibration(documents)
        benchmarks = self.benchmarks()
        curated = self.curated_reports(documents)
        weekly = self.weekly(documents)
        outcome_counts = {key.removeprefix("outcome:"): value for key, value in journal.get("counts", {}).items() if key.startswith("outcome:")}
        return {
            "ok": graph.get("ok", False),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "paths": {"index": str(self.db), "journal": str(self.journal_path), "reports": str(self.reports), "action_state": str(self.action_state)},
            "graph": {"ok": graph.get("ok"), "counts": graph.get("counts", {}), "error": graph.get("error")},
            "journal": {"ok": journal.get("ok"), "counts": journal.get("counts", {}), "outcomes": outcome_counts, "routes": len(journal.get("routes", [])), "error": journal.get("error")},
            "calibration": {"ok": calibration.get("ok"), "reports": len(calibration.get("reports", [])), "latest": calibration.get("latest")},
            "benchmarks": {"ok": benchmarks.get("ok"), "reports": len(benchmarks.get("reports", [])), "scan": benchmarks.get("scan", {}), "latest": benchmarks.get("latest")},
            "curated_reports": {"ok": curated.get("ok"), "status": curated.get("status"), "reports": len(curated.get("reports", [])), "scan": curated.get("scan", {}), "benchmark_documents_separated": curated.get("benchmark_documents_separated", 0)},
            "weekly": {"ok": weekly.get("ok"), "status": weekly.get("status"), "scan": weekly.get("scan", {}), "action_state": weekly.get("action_state", {}), "reports": len(weekly.get("reports", [])), "counts": weekly.get("counts", {}), "latest": weekly.get("latest"), "error": weekly.get("error")},
        }


class DashboardHandler(BaseHTTPRequestHandler):
    data: DashboardData
    SCAN_LIMIT_ROUTES = frozenset({"/api/health", "/api/overview", "/api/curated-reports", "/api/calibration", "/api/benchmarks", "/api/weekly", "/api/scan/dry-run"})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"dashboard: {self.address_string()} - {format % args}", file=sys.stderr)

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _scan_limit_overrides_from_query(self, query: str) -> dict[str, str]:
        parsed = parse_qs(query, keep_blank_values=True)
        unknown = sorted(key for key in parsed if key.startswith("scan_") and key not in self.data.REPORT_SCAN_LIMIT_KEYS)
        if unknown:
            raise ValueError(f"unknown scan limit override: {unknown[0]}")
        overrides: dict[str, str] = {}
        for key in self.data.REPORT_SCAN_LIMIT_KEYS:
            if key not in parsed:
                continue
            if len(parsed[key]) != 1:
                raise ValueError(f"{key} must be provided exactly once")
            overrides[key] = parsed[key][0]
        return overrides

    def _serve_get(self, route: str) -> None:
        try:
            if route == "/":
                body = HTML_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/api/health":
                self.send_json({"ok": True, "service": "skill-supermind-dashboard", "scan": self.data.scan_configuration()})
            elif route == "/api/scan/dry-run":
                self.send_json(self.data.dry_run_scan())
            elif route == "/api/overview":
                self.send_json(self.data.overview())
            elif route == "/api/graph":
                self.send_json(self.data.graph())
            elif route == "/api/journal":
                self.send_json(self.data.journal())
            elif route == "/api/curated-reports":
                self.send_json(self.data.curated_reports())
            elif route == "/api/curated-reports":
                self.send_json(self.data.curated_reports())
            elif route == "/api/calibration":
                self.send_json(self.data.calibration())
            elif route == "/api/benchmarks":
                self.send_json(self.data.benchmarks())
            elif route == "/api/skipped-benchmark-trees":
                self.send_json(self.data.skipped_benchmark_trees())
            elif route == "/api/weekly":
                self.send_json(self.data.weekly())
            else:
                self.send_json({"ok": False, "error": "not found"}, 404)
        except FileNotFoundError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)
        except Exception as exc:  # Keep the local dashboard available when one artifact is malformed.
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route not in self.SCAN_LIMIT_ROUTES:
            self._serve_get(route)
            return
        try:
            overrides = self._scan_limit_overrides_from_query(parsed.query)
            with self.data.report_scan_limit_overrides(overrides):
                self._serve_get(route)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route not in {"/api/action-items/status", "/api/cache/invalidate"}:
            self.send_json({"ok": False, "error": "not found"}, 404)
            return
        if not self.data.local_only:
            error = "action updates are disabled for non-local bindings" if route == "/api/action-items/status" else "cache invalidation is disabled for non-local bindings"
            self.send_json({"ok": False, "error": error}, 403)
            return
        if route == "/api/cache/invalidate":
            self.send_json(self.data.invalidate_report_cache())
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 16_384:
            self.send_json({"ok": False, "error": "request body must be a small JSON object"}, 400)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_json({"ok": False, "error": "Content-Type must be application/json"}, 415)
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            result = self.data.set_action_status(payload.get("report_id"), payload.get("action_id"), payload.get("status"), payload.get("operator_note"), payload.get("actor"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except OSError as exc:
            self.send_json({"ok": False, "error": f"cannot save action state: {exc}"}, 500)
        else:
            self.send_json(result)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".skill-brain/index.sqlite3"), help="skill index SQLite file")
    parser.add_argument("--journal", type=Path, default=Path(".skill-brain/execution-journal.sqlite3"), help="execution journal SQLite file")
    parser.add_argument("--reports", type=Path, default=Path(".skill-brain"), help="directory containing JSON reports")
    parser.add_argument("--action-state", type=Path, help="local operator acknowledgement overlay (default: <reports>/.dashboard-action-state.json)")
    parser.add_argument("--benchmark-tree", action="append", type=Path, default=[], help="benchmark artifact tree to exclude from prefix-curated report discovery; repeatable")
    parser.add_argument("--report-manifest", type=Path, help="versioned JSON manifest that explicitly allowlists operational report files")
    parser.add_argument("--scan-max-entries", type=int, default=DashboardData.REPORT_SCAN_MAX_ENTRIES, help="maximum directory entries visited during report discovery")
    parser.add_argument("--scan-max-depth", type=int, default=DashboardData.REPORT_SCAN_MAX_DEPTH, help="maximum operational report directory depth")
    parser.add_argument("--scan-max-files", type=int, default=DashboardData.REPORT_SCAN_MAX_FILES, help="maximum report files returned by discovery")
    parser.add_argument("--scan-max-file-bytes", type=int, default=DashboardData.REPORT_SCAN_MAX_FILE_BYTES, help="maximum bytes allowed for one report JSON file")
    parser.add_argument("--cache-content-hash", action="store_true", help="validate cached report file contents with SHA-256 when metadata is unchanged")
    parser.add_argument("--host", default="127.0.0.1", help="loopback-only by default; dashboard mutation endpoints are disabled for remote bindings")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("--port must be between 1 and 65535", file=sys.stderr)
        return 1
    scan_limits = {
        "scan-max-entries": args.scan_max_entries,
        "scan-max-depth": args.scan_max_depth,
        "scan-max-files": args.scan_max_files,
        "scan-max-file-bytes": args.scan_max_file_bytes,
    }
    invalid_limits = [name for name, value in scan_limits.items() if value < 1]
    if invalid_limits:
        print(f"scan limits must be positive integers: {', '.join(invalid_limits)}", file=sys.stderr)
        return 1
    local_only = args.host.lower() in {"127.0.0.1", "localhost", "::1"}
    try:
        DashboardHandler.data = DashboardData(args.db, args.journal, args.reports, args.action_state, local_only=local_only, benchmark_trees=args.benchmark_tree, report_scan_max_entries=args.scan_max_entries, report_scan_max_depth=args.scan_max_depth, report_scan_max_files=args.scan_max_files, report_scan_max_file_bytes=args.scan_max_file_bytes, cache_content_hash=args.cache_content_hash, report_manifest=args.report_manifest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"skill-supermind dashboard: http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("dashboard stopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
