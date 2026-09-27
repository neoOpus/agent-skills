#!/usr/bin/env python3
"""Benchmark the skill indexer on deterministic synthetic skill corpora.

The harness is intentionally standard-library only. It generates disposable
Agent Skill directories, builds a real SQLite index, checks freshness, runs
retrieval and route workloads, and emits one JSON report. It does not require
network access or third-party packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import skill_graph  # noqa: E402

DEFAULT_SIZES = (100, 1_000, 10_000, 100_000)
DOMAINS = ("software", "delivery", "research", "learning", "operations", "design")
TOPICS = (
    "catalog", "routing", "accessibility", "deployment", "indexing", "privacy",
    "performance", "validation", "knowledge", "automation", "observability", "security",
)
RELATIONS = ("composes", "requires", "validates", "related-to")
BYTES_PER_GB = 1024 ** 3
# These are deliberately conservative planning estimates, not measurements.
# Reports label them as projections so callers do not mistake them for results.
PLANNED_BYTES_PER_SKILL = 16 * 1024
PLANNED_PEAK_MEMORY_BYTES_PER_SKILL = 32 * 1024


@dataclass(frozen=True)
class ResourcePolicy:
    timeout_seconds: float | None = None
    phase_timeout_seconds: float | None = None
    disk_budget_bytes: int | None = None
    memory_warning_bytes: int | None = None

    def validate(self) -> None:
        for name, value in (("timeout_seconds", self.timeout_seconds), ("phase_timeout_seconds", self.phase_timeout_seconds)):
            if value is not None and (not isinstance(value, (int, float)) or value <= 0):
                raise ValueError(f"{name} must be positive or omitted")
        for name, value in (("disk_budget_bytes", self.disk_budget_bytes), ("memory_warning_bytes", self.memory_warning_bytes)):
            if value is not None and (not isinstance(value, int) or value <= 0):
                raise ValueError(f"{name} must be positive or omitted")

    def report(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "phase_timeout_seconds": self.phase_timeout_seconds,
            "disk_budget_bytes": self.disk_budget_bytes,
            "memory_warning_bytes": self.memory_warning_bytes,
        }


class BenchmarkResourceError(RuntimeError):
    def __init__(self, kind: str, label: str, elapsed: float | None = None) -> None:
        self.kind = kind
        self.label = label
        self.elapsed = elapsed
        detail = f"{label} exceeded {kind}"
        if elapsed is not None:
            detail += f" after {elapsed:.3f}s"
        super().__init__(detail)


class _Deadline:
    def __init__(self, policy: ResourcePolicy) -> None:
        policy.validate()
        self.policy = policy
        self.started = time.perf_counter()

    def check(self, label: str, phase_elapsed: float | None = None) -> None:
        total_elapsed = time.perf_counter() - self.started
        if self.policy.timeout_seconds is not None and total_elapsed >= self.policy.timeout_seconds:
            raise BenchmarkResourceError("wall-clock timeout", label, total_elapsed)
        if self.policy.phase_timeout_seconds is not None and phase_elapsed is not None and phase_elapsed >= self.policy.phase_timeout_seconds:
            raise BenchmarkResourceError("phase timeout", label, phase_elapsed)


def _timed(label: str, function: Any, deadline: _Deadline | None = None) -> tuple[Any, float]:
    if deadline is not None:
        deadline.check(label)
    started = time.perf_counter()
    result = function()
    elapsed = time.perf_counter() - started
    if deadline is not None:
        deadline.check(label, elapsed)
    return result, elapsed


def _resource_assessment(policy: ResourcePolicy, count: int, work_root: Path, database_copies: int = 1) -> dict[str, Any]:
    """Project resource risk before allocating a corpus or index."""
    policy.validate()
    work_root.mkdir(parents=True, exist_ok=True)
    free_bytes, total_bytes, _ = shutil.disk_usage(work_root)
    estimated_working_set = count * PLANNED_BYTES_PER_SKILL
    estimated_peak_memory = count * PLANNED_PEAK_MEMORY_BYTES_PER_SKILL
    reasons: list[str] = []
    if policy.disk_budget_bytes is not None and estimated_working_set > policy.disk_budget_bytes:
        reasons.append("projected working set exceeds configured disk budget")
    if free_bytes < estimated_working_set:
        reasons.append("projected working set exceeds filesystem free space")
    if policy.memory_warning_bytes is not None and estimated_peak_memory > policy.memory_warning_bytes:
        reasons.append("projected peak Python memory exceeds warning threshold")
    return {
        "count": count,
        "work_root": str(work_root),
        "database_copies_planned": database_copies,
        "filesystem_free_bytes": free_bytes,
        "filesystem_total_bytes": total_bytes,
        "projection_basis": "conservative planning constants; not a benchmark measurement",
        "estimated_working_set_bytes": estimated_working_set,
        "estimated_peak_python_memory_bytes": estimated_peak_memory,
        "disk_budget_bytes": policy.disk_budget_bytes,
        "memory_warning_bytes": policy.memory_warning_bytes,
        "early_abort_recommendation": {
            "status": "abort_recommended" if reasons else "proceed",
            "should_abort": bool(reasons),
            "reasons": reasons,
            "recommendation": (
                "Reduce corpus size or increase the disk/memory budget before running."
                if reasons else "No configured resource limit predicts an early abort."
            ),
        },    }


def synthetic_skill_text(index: int, total: int, seed: int) -> str:

    topic = TOPICS[index % len(TOPICS)]
    domain = DOMAINS[(index // len(TOPICS)) % len(DOMAINS)]
    workload = index % 97
    return (
        "---\n"
        f"name: synthetic-skill-{index:06d}\n"
        f"description: Synthetic benchmark skill {index} for {topic} workloads in {domain}.\n"
        "metadata:\n"
        "  version: \"1.0.0\"\n"
        f"  benchmark_seed: \"{seed}\"\n"
        f"  tags: \"benchmark, {topic}, {domain}\"\n"
        "---\n"
        f"# Synthetic skill {index}\n\n"
        f"Handle {topic} workload {workload} safely and repeatably.\n"
        f"This generated instruction is deterministic for benchmark corpus size {total}.\n"
        f"#benchmark #{topic} #{domain}\n"
    )


def generate_corpus(root: Path, count: int, seed: int = 0, edge_stride: int = 10) -> dict[str, Any]:
    """Generate count valid skills and a small typed graph overlay."""
    if count < 1:
        raise ValueError("count must be positive")
    if edge_stride < 2:
        raise ValueError("edge_stride must be at least 2")
    root.mkdir(parents=True, exist_ok=False)
    corpus_digest = hashlib.sha256()
    manifest_entries: list[dict[str, Any]] = []
    for index in range(count):
        name = f"synthetic-skill-{index:06d}"
        directory = root / name
        directory.mkdir()
        text = synthetic_skill_text(index, count, seed)
        encoded = text.encode("utf-8")
        (directory / "SKILL.md").write_bytes(encoded)
        corpus_digest.update(name.encode("ascii"))
        corpus_digest.update(b"\0")
        corpus_digest.update(encoded)
        if index % edge_stride == 0 and index + 1 < count:
            relation = RELATIONS[(index // edge_stride) % len(RELATIONS)]
            manifest_entries.append({
                "id": name,
                "domain": DOMAINS[(index // len(TOPICS)) % len(DOMAINS)],
                "relations": [{"type": relation, "target": f"synthetic-skill-{index + 1:06d}", "weight": 0.8}],
            })
    manifest = {"schema_version": 1, "skills": manifest_entries}
    manifest_path = root / "benchmark-registry.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    return {
        "skills": count,
        "seed": seed,
        "edge_stride": edge_stride,
        "edges": len(manifest_entries),
        "corpus_sha256": corpus_digest.hexdigest(),
        "manifest": manifest,
        "manifest_path": manifest_path,
    }


def machine_metadata() -> dict[str, Any]:
    free_bytes, total_bytes, _ = shutil.disk_usage(Path.cwd())
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "sqlite": sqlite3.sqlite_version,
        "filesystem_free_bytes": free_bytes,
        "filesystem_total_bytes": total_bytes,
    }


def run_one(
    count: int,
    work_root: Path,
    seed: int = 0,
    edge_stride: int = 10,
    query_count: int = 5,
    route_count: int = 2,
    keep: bool = False,
    policy: ResourcePolicy | None = None,
    deadline: _Deadline | None = None,
) -> dict[str, Any]:
    if not 1 <= query_count <= 100:
        raise ValueError("query_count must be between 1 and 100")
    if not 1 <= route_count <= 100:
        raise ValueError("route_count must be between 1 and 100")
    run_dir = Path(tempfile.mkdtemp(prefix=f"skills-{count:06d}-", dir=work_root))
    corpus_dir = run_dir / "skills"
    db = run_dir / "index.sqlite3"
    manifest_path: Path | None = None
    policy = policy or ResourcePolicy()
    policy.validate()
    deadline = deadline or _Deadline(policy)
    tracemalloc.start()
    try:
        generated, generate_seconds = _timed("generate", lambda: generate_corpus(corpus_dir, count, seed, edge_stride), deadline)
        manifest_path = generated.pop("manifest_path")
        generated.pop("manifest")
        index_result, index_seconds = _timed("index", lambda: skill_graph.refresh_index(corpus_dir, db, manifest_path, strict=False), deadline)
        check_result, check_seconds = _timed("check", lambda: skill_graph.check_index(db, corpus_dir, manifest_path), deadline)
        query_latencies: list[float] = []
        query_counts: list[int] = []
        query_leads: list[str | None] = []
        for offset in range(query_count):
            topic = TOPICS[(offset + seed) % len(TOPICS)]
            query = f"synthetic {topic} workload {offset % 97}"
            result, elapsed = _timed("query", lambda query=query: skill_graph.query_index(db, query, None, None, 0.0, 8, False, 1), deadline)
            query_latencies.append(elapsed)
            query_counts.append(len(result["results"]))
            query_leads.append(result["results"][0]["skill_id"] if result["results"] else None)
        route_latencies: list[float] = []
        route_counts: list[int] = []
        for offset in range(route_count):
            topic = TOPICS[(offset + seed + 3) % len(TOPICS)]
            query = f"synthetic {topic} workload {offset % 97}"
            result, elapsed = _timed("route", lambda query=query: skill_graph.route(db, query, None, None, 0.0, 8, 1), deadline)
            route_latencies.append(elapsed)
            route_counts.append(1 if result["lead"] else 0)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "count": count,
            "ok": bool(index_result.get("ok") and check_result.get("ok") and not check_result.get("stale")),
            "status": "completed",
            "generated": generated,
            "index": {
                "ok": index_result.get("ok"),
                "seconds": index_seconds,
                "skills": index_result.get("skills"),
                "edges": index_result.get("edges"),
                "fts5": index_result.get("fts5"),
            },
            "check": {
                "ok": check_result.get("ok"),
                "stale": check_result.get("stale"),
                "seconds": check_seconds,
            },
            "queries": {
                "count": query_count,
                "latencies_seconds": query_latencies,
                "result_counts": query_counts,
                "lead_ids": query_leads,
            },
            "routes": {
                "count": route_count,
                "latencies_seconds": route_latencies,
                "lead_counts": route_counts,
            },
            "resources": {
                "database_bytes": db.stat().st_size if db.exists() else 0,
                "corpus_bytes": sum(path.stat().st_size for path in corpus_dir.rglob("SKILL.md")),
                "peak_python_bytes": peak,
                "traced_current_bytes": current,
                "memory_warning": bool(policy.memory_warning_bytes is not None and peak >= policy.memory_warning_bytes),
                "memory_warning_bytes": policy.memory_warning_bytes,
                "disk_budget_bytes": policy.disk_budget_bytes,
                "disk_budget_exceeded": bool(policy.disk_budget_bytes is not None and (db.stat().st_size if db.exists() else 0) + sum(path.stat().st_size for path in corpus_dir.rglob("SKILL.md")) > policy.disk_budget_bytes),
            },
            "timings_seconds": {
                "generate": generate_seconds,
                "index": index_seconds,
                "check": check_seconds,
                "query_total": sum(query_latencies),
                "route_total": sum(route_latencies),
            },
            "run_directory": str(run_dir) if keep else None,
        }
    finally:
        tracemalloc.stop()
        if not keep:
            shutil.rmtree(run_dir, ignore_errors=True)


def mutate_corpus(root: Path, count: int, change_ratio: float, seed: int = 0) -> dict[str, Any]:
    if not 0 <= change_ratio <= 1:
        raise ValueError("change_ratio must be between 0 and 1")
    changed = max(1, round(count * change_ratio)) if count and change_ratio > 0 else 0
    changed_indices = [(seed * 7919 + offset * 104729) % count for offset in range(changed)]
    changed_indices = sorted(set(changed_indices))
    for index in changed_indices:
        path = root / f"synthetic-skill-{index:06d}" / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        marker = f"Handle {TOPICS[index % len(TOPICS)]} workload"
        text = text.replace(marker, f"{marker} after a deterministic mutation", 1)
        path.write_text(text, encoding="utf-8")
    return {"requested_change_ratio": change_ratio, "changed": len(changed_indices), "change_ratio": round(len(changed_indices) / count, 6) if count else 0}


def prepare_incremental_run(
    count: int,
    work_root: Path,
    seed: int = 0,
    edge_stride: int = 10,
    policy: ResourcePolicy | None = None,
    abort_on_risk: bool = False,
) -> dict[str, Any]:
    policy = policy or ResourcePolicy()
    policy.validate()
    work_root.mkdir(parents=True, exist_ok=True)
    assessment = _resource_assessment(policy, count, work_root, database_copies=1)
    if abort_on_risk and assessment["early_abort_recommendation"]["should_abort"]:
        return {"ok": False, "status": "early_aborted", "resource_policy": policy.report(), "resource_assessment": assessment}
    deadline = _Deadline(policy)
    run_dir = Path(tempfile.mkdtemp(prefix=f"incremental-{count:06d}-", dir=work_root))
    corpus_dir = run_dir / "skills"
    initial_db = run_dir / "initial.sqlite3"
    generated, _ = _timed("generate", lambda: generate_corpus(corpus_dir, count, seed, edge_stride), deadline)
    manifest_path = generated.pop("manifest_path")
    generated.pop("manifest")
    initial, _ = _timed("initial-full-index", lambda: skill_graph.refresh_index(corpus_dir, initial_db, manifest_path, strict=False), deadline)
    return {"ok": bool(initial.get("ok")), "status": "completed", "count": count, "resource_policy": policy.report(), "resource_assessment": assessment, "run_directory": str(run_dir), "manifest": str(manifest_path), "initial_database": str(initial_db), "generated": generated}


def run_incremental_comparison(
    sizes: Iterable[int] = (10_000, 100_000),
    work_root: Path | None = None,
    seed: int = 0,
    edge_stride: int = 10,
    change_ratio: float = 0.01,
    keep: bool = False,
    skip_checks: bool = False,
    prepared_root: Path | None = None,
    policy: ResourcePolicy | None = None,
    abort_on_risk: bool = False,
) -> dict[str, Any]:
    sizes = list(sizes)
    if not sizes or any(size < 1 for size in sizes):
        raise ValueError("sizes must contain positive integers")
    if not 0 <= change_ratio <= 1:
        raise ValueError("change_ratio must be between 0 and 1")
    policy = policy or ResourcePolicy()
    policy.validate()
    if work_root is None:
        work_root = Path(tempfile.mkdtemp(prefix="skill-supermind-incremental-"))
        remove_root = not keep
    else:
        work_root.mkdir(parents=True, exist_ok=True)
        remove_root = False
    started = time.perf_counter()
    deadline = _Deadline(policy)
    results: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    try:
        for count in sizes:
            assessment = _resource_assessment(policy, count, work_root, database_copies=3)
            assessments.append(assessment)
            if abort_on_risk and assessment["early_abort_recommendation"]["should_abort"]:
                results.append({"count": count, "ok": False, "status": "early_aborted", "resource_assessment": assessment})
                break
            try:
                if prepared_root is not None:
                    if len(sizes) != 1:
                        raise ValueError("prepared_root can only be used with one corpus size")
                    run_dir = prepared_root.resolve()
                    corpus_dir = run_dir / "skills"
                    initial_db = run_dir / "initial.sqlite3"
                    manifest_path = corpus_dir / "benchmark-registry.json"
                    if not corpus_dir.is_dir() or not initial_db.is_file() or not manifest_path.is_file():
                        raise ValueError(f"prepared_root lacks corpus, manifest, or initial index: {run_dir}")
                    generated = {"prepared": True}
                    initial = {"ok": True}
                    initial_seconds = 0.0
                    owns_run_dir = False
                else:
                    run_dir = Path(tempfile.mkdtemp(prefix=f"incremental-{count:06d}-", dir=work_root))
                    corpus_dir = run_dir / "skills"
                    initial_db = run_dir / "initial.sqlite3"
                    manifest_path = None
                    generated, _ = _timed("generate", lambda: generate_corpus(corpus_dir, count, seed, edge_stride), deadline)
                    manifest_path = generated.pop("manifest_path")
                    generated.pop("manifest")
                    initial, initial_seconds = _timed("initial-full-index", lambda: skill_graph.refresh_index(corpus_dir, initial_db, manifest_path, strict=False), deadline)
                    owns_run_dir = True
                    full_db = run_dir / "full.sqlite3"
                    incremental_db = run_dir / "incremental.sqlite3"
                    deadline.check("copy-initial-snapshot")
                    shutil.copy2(initial_db, incremental_db)
                    mutation = mutate_corpus(corpus_dir, count, change_ratio, seed)
                    full, full_seconds = _timed("full-rebuild", lambda: skill_graph.refresh_index(corpus_dir, full_db, manifest_path, strict=False), deadline)
                    incremental, incremental_seconds = _timed("content-hash-refresh", lambda: skill_graph.refresh_index_incremental(corpus_dir, incremental_db, manifest_path, strict=False), deadline)
                    if skip_checks:
                        full_check = {"ok": None, "skipped": True}
                        incremental_check = {"ok": None, "skipped": True}
                    else:
                        full_check, _ = _timed("full-check", lambda: skill_graph.check_index(full_db, corpus_dir, manifest_path), deadline)
                        incremental_check, _ = _timed("incremental-check", lambda: skill_graph.check_index(incremental_db, corpus_dir, manifest_path), deadline)
                    results.append({
                        "count": count,
                        "ok": bool(initial.get("ok") and full.get("ok") and incremental.get("ok") and (skip_checks or (full_check.get("ok") and incremental_check.get("ok")))),
                        "status": "completed",
                        "mutation": mutation,
                        "initial_full_index_seconds": initial_seconds,
                        "full_rebuild_seconds": full_seconds,
                        "content_hash_refresh_seconds": incremental_seconds,
                        "speedup_vs_full": round(full_seconds / incremental_seconds, 3) if incremental_seconds else None,
                        "full": {"skills": full.get("skills"), "edges": full.get("edges"), "database_bytes": full_db.stat().st_size if full_db.exists() else 0},
                        "incremental": {"skills": incremental.get("skills"), "edges": incremental.get("edges"), "unchanged": incremental.get("unchanged"), "changed": len(incremental.get("changed", [])), "reparsed": incremental.get("reparsed"), "database_bytes": incremental_db.stat().st_size if incremental_db.exists() else 0},
                        "checks": {"full_ok": full_check.get("ok"), "incremental_ok": incremental_check.get("ok"), "skipped": skip_checks},
                        "resource_assessment": assessment,
                        "resource_policy": policy.report(),
                        "run_directory": str(run_dir) if keep else None,
                    })
                    if not keep and owns_run_dir:
                        shutil.rmtree(run_dir, ignore_errors=True)
            except BenchmarkResourceError as exc:
                if "run_dir" in locals() and owns_run_dir and not keep:
                    shutil.rmtree(run_dir, ignore_errors=True)
                results.append({"count": count, "ok": False, "status": exc.kind.replace(" ", "_"), "error": str(exc), "resource_assessment": assessment, "resource_policy": policy.report()})
                break
    finally:
        if remove_root:
            shutil.rmtree(work_root, ignore_errors=True)
    return {
        "schema_version": 1,
        "benchmark": "full-vs-content-hash-incremental",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": machine_metadata(),
        "resource_policy": policy.report(),
        "resource_assessments": assessments,
        "parameters": {"sizes": sizes, "seed": seed, "edge_stride": edge_stride, "change_ratio": change_ratio, "keep_work_directories": keep, "skip_checks": skip_checks, "prepared_root": str(prepared_root) if prepared_root else None, "abort_on_risk": abort_on_risk},
        "total_seconds": time.perf_counter() - started,
        "passed": all(result["ok"] for result in results),
        "results": results,
    }


def run_benchmark(
    sizes: Iterable[int] = DEFAULT_SIZES,
    work_root: Path | None = None,
    seed: int = 0,
    edge_stride: int = 10,
    query_count: int = 5,
    route_count: int = 2,
    keep: bool = False,
    policy: ResourcePolicy | None = None,
    abort_on_risk: bool = False,
) -> dict[str, Any]:
    sizes = list(sizes)
    if not sizes or any(size < 1 for size in sizes):
        raise ValueError("sizes must contain positive integers")
    policy = policy or ResourcePolicy()
    policy.validate()
    if work_root is None:
        work_root = Path(tempfile.mkdtemp(prefix="skill-supermind-benchmark-"))
        remove_root = not keep
    else:
        work_root.mkdir(parents=True, exist_ok=True)
        remove_root = False
    started = time.perf_counter()
    deadline = _Deadline(policy)
    results: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    try:
        for count in sizes:
            assessment = _resource_assessment(policy, count, work_root)
            assessments.append(assessment)
            if abort_on_risk and assessment["early_abort_recommendation"]["should_abort"]:
                results.append({"count": count, "ok": False, "status": "early_aborted", "resource_assessment": assessment})
                break
            try:
                result = run_one(count, work_root, seed, edge_stride, query_count, route_count, keep, policy, deadline)
                result["resource_assessment"] = assessment
                result["resource_policy"] = policy.report()
                results.append(result)
            except BenchmarkResourceError as exc:
                results.append({"count": count, "ok": False, "status": exc.kind.replace(" ", "_"), "error": str(exc), "resource_assessment": assessment, "resource_policy": policy.report()})
                break
    finally:
        if remove_root:
            shutil.rmtree(work_root, ignore_errors=True)
    return {
        "schema_version": 1,
        "benchmark": "synthetic-skill-corpus",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": machine_metadata(),
        "resource_policy": policy.report(),
        "resource_assessments": assessments,
        "parameters": {
            "sizes": sizes,
            "seed": seed,
            "edge_stride": edge_stride,
            "query_count": query_count,
            "route_count": route_count,
            "keep_work_directories": keep,
            "abort_on_risk": abort_on_risk,
        },
        "total_seconds": time.perf_counter() - started,
        "passed": all(result["ok"] for result in results),
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default=",".join(str(size) for size in DEFAULT_SIZES), help="comma-separated corpus sizes")
    parser.add_argument("--work-root", type=Path, help="parent directory for disposable runs")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--edge-stride", type=int, default=10)
    parser.add_argument("--query-count", type=int, default=5)
    parser.add_argument("--route-count", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, help="wall-clock budget for the benchmark; checked between and after phases")
    parser.add_argument("--phase-timeout-seconds", type=float, help="per-phase wall-clock budget; checked between and after phases")
    parser.add_argument("--disk-budget-gb", type=float, default=0.0, help="planned working-set budget in GiB; 0 disables the budget")
    parser.add_argument("--memory-warning-gb", type=float, default=1.0, help="Python-memory warning threshold in GiB; 0 disables warnings")
    parser.add_argument("--abort-on-risk", action="store_true", help="stop before allocation when the resource projection recommends aborting")
    parser.add_argument("--keep", action="store_true", help="keep generated run directories for inspection")
    parser.add_argument("--compare-incremental", action="store_true", help="compare full rebuilds with content-hash refreshes")
    parser.add_argument("--change-ratio", type=float, default=0.01, help="fraction of synthetic skills changed in incremental comparison")
    parser.add_argument("--skip-checks", action="store_true", help="skip expensive full freshness checks for timing-only large runs")
    parser.add_argument("--prepare-incremental", type=int, help="prepare one corpus and initial index, then print its reusable directory")
    parser.add_argument("--prepared-root", type=Path, help="reuse a directory emitted by --prepare-incremental")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sizes = [int(part.strip()) for part in args.sizes.split(",") if part.strip()]
        if args.disk_budget_gb < 0 or args.memory_warning_gb < 0:
            raise ValueError("resource budgets cannot be negative")
        policy = ResourcePolicy(
            timeout_seconds=args.timeout_seconds,
            phase_timeout_seconds=args.phase_timeout_seconds,
            disk_budget_bytes=int(args.disk_budget_gb * BYTES_PER_GB) if args.disk_budget_gb else None,
            memory_warning_bytes=int(args.memory_warning_gb * BYTES_PER_GB) if args.memory_warning_gb else None,
        )
        policy.validate()
        if args.prepare_incremental is not None:
            if args.work_root is None:
                raise ValueError("--prepare-incremental requires --work-root")
            report = prepare_incremental_run(args.prepare_incremental, args.work_root, args.seed, args.edge_stride, policy, args.abort_on_risk)
        elif args.compare_incremental:
            report = run_incremental_comparison(sizes, args.work_root, args.seed, args.edge_stride, args.change_ratio, args.keep, args.skip_checks, args.prepared_root, policy, args.abort_on_risk)
        else:
            report = run_benchmark(sizes, args.work_root, args.seed, args.edge_stride, args.query_count, args.route_count, args.keep, policy, args.abort_on_risk)
    except BenchmarkResourceError as exc:
        print(json.dumps({"ok": False, "status": exc.kind.replace(" ", "_"), "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error, skill_graph.SkillError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed", report.get("ok", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
