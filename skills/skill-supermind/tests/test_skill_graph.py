#!/usr/bin/env python3
"""Dependency-free regression tests for skill_graph.py."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "skill_graph.py"
sys.path.insert(0, str(SCRIPT.parent))
import skill_graph  # noqa: E402
import benchmark_synthetic  # noqa: E402
import dashboard  # noqa: E402


def skill(name: str, description: str, body: str = "# Instructions\n\nDo the work safely.") -> str:
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  version: '1.0.0'\n---\n{body}\n"


class SkillGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "skills"
        self.db = Path(self.temp.name) / "index.sqlite3"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_skill(self, name: str, description: str, body: str) -> None:
        directory = self.root / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(skill(name, description, body), encoding="utf-8")

    def test_frontmatter_parser_supports_metadata_and_folded_description(self) -> None:
        text = """---
name: example-skill
description: >
  A useful description
  across two lines.
metadata:
  version: "1.2.3"
  tags: "one, #Two"
---
# Body
"""
        data, body = skill_graph.parse_frontmatter(text, "example/SKILL.md")
        self.assertEqual(data["name"], "example-skill")
        self.assertEqual(data["description"], "A useful description across two lines.")
        self.assertEqual(data["metadata"]["version"], "1.2.3")
        self.assertIn("# Body", body)

    def test_tag_normalization_ignores_markdown_headings(self) -> None:
        tags = skill_graph.normalize_tags("# Heading\n\nTags: #Knowledge-Management #skill_graph #bad tag\n")
        self.assertEqual(tags, ["bad", "knowledge-management", "skill_graph"])

    def test_validation_catches_name_directory_mismatch(self) -> None:
        directory = self.root / "wrong-directory"
        directory.mkdir()
        path = directory / "SKILL.md"
        path.write_text(skill("right-name", "A valid description."), encoding="utf-8")
        records, issues = skill_graph.load_records(self.root)
        self.assertEqual(len(records), 1)
        self.assertIn("directory-mismatch", {issue.code for issue in issues})

    def test_index_query_and_stats_are_deterministic(self) -> None:
        self.add_skill(
            "search-skill",
            "Search a large skill catalog with tags and graph routing.",
            "# Instructions\n\n#knowledge-management #routing\nUse SQLite.",
        )
        self.add_skill(
            "build-skill",
            "Build a deployment pipeline.",
            "# Instructions\n\n#delivery\nUse a deployment provider.",
        )
        result = skill_graph.refresh_index(self.root, self.db, None, strict=False)
        self.assertTrue(result["ok"])
        stats = skill_graph.stats(self.db)
        self.assertEqual(stats["counts"]["skills"], 2)
        first = skill_graph.query_index(self.db, "SQLite catalog", None, None, 0.0, 5, True)
        second = skill_graph.query_index(self.db, "SQLite catalog", None, None, 0.0, 5, True)
        self.assertEqual(first, second)
        self.assertTrue(first["results"])
        self.assertEqual(first["results"][0]["skill_id"], "search-skill")
        self.assertNotIn("body", first["results"][0])
        self.assertNotIn("_body", first["results"][0])

    def test_incremental_refresh_reuses_unchanged_and_updates_changed_rows(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing.", "# Instructions\\n\\nIndex catalogs.\\n#alpha")
        self.add_skill("beta", "Beta handles deployment.", "# Instructions\\n\\nDeploy safely.\\n#beta")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        unchanged = skill_graph.refresh_index_incremental(self.root, self.db, None, strict=False)
        self.assertTrue(unchanged["ok"])
        self.assertEqual(unchanged["unchanged"], 2)
        self.assertEqual(unchanged["reparsed"], 0)
        (self.root / "alpha" / "SKILL.md").write_text(skill("alpha", "Alpha now handles retrieval.", "# Instructions\nIndex retrieval.\n#alpha"), encoding="utf-8")
        (self.root / "beta" / "SKILL.md").unlink()
        self.add_skill("gamma", "Gamma handles validation.", "# Instructions" + chr(10) + chr(10) + "Validate output." + chr(10) + "#gamma")
        result = skill_graph.refresh_index_incremental(self.root, self.db, None, strict=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], ["gamma"])
        self.assertEqual(result["changed"], ["alpha"])
        self.assertEqual(result["deleted"], ["beta"])
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(skill_graph.stats(self.db)["counts"]["skills"], 2)
        self.assertTrue(skill_graph.check_index(self.db, self.root, None)["ok"])
        self.assertIn("retrieval", skill_graph.query_index(self.db, "Alpha retrieval", None, None, 0.0, 5, False)["results"][0]["description"])

    def test_incremental_refresh_does_not_mutate_on_invalid_change(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing.", "# Instructions\\n\\nIndex catalogs.\\n#alpha")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        before = skill_graph.stats(self.db)
        (self.root / "alpha" / "SKILL.md").write_text("oops", encoding="utf-8")
        result = skill_graph.refresh_index_incremental(self.root, self.db, None, strict=False)
        self.assertFalse(result["ok"])
        self.assertEqual(skill_graph.stats(self.db), before)

    def test_manifest_edges_and_cycles_are_preserved(self) -> None:
        self.add_skill("alpha", "Alpha handles one coherent job.", "# Instructions\n\nWork.\n#alpha")
        self.add_skill("beta", "Beta handles another coherent job.", "# Instructions\n\nWork.\n#alpha")
        manifest = {
            "schema_version": 1,
            "skills": [
                {"id": "alpha", "domain": "test", "relations": [{"type": "composes", "target": "beta"}]},
                {"id": "beta", "relations": [{"type": "composes", "target": "alpha"}]},
            ],
        }
        manifest_path = self.root / "graph.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = skill_graph.refresh_index(self.root, self.db, manifest_path, strict=False)
        self.assertTrue(result["ok"])
        neighbors = skill_graph.neighbors(self.db, "alpha", 3, None)
        self.assertEqual({edge["type"] for edge in neighbors["edges"]}, {"composes"})

    def test_invalid_manifest_does_not_mutate_existing_index(self) -> None:
        self.add_skill("alpha", "Alpha handles one coherent job.", "# Instructions\n\nWork.\n#alpha")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        before = skill_graph.stats(self.db)["counts"]
        manifest = {"schema_version": 1, "skills": [{"id": "alpha", "relations": [{"type": "requires", "target": "missing"}]}]}
        manifest_path = self.root / "bad.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = skill_graph.refresh_index(self.root, self.db, manifest_path, strict=False)
        self.assertFalse(result["ok"])
        self.assertEqual(skill_graph.stats(self.db)["counts"], before)

    def test_malformed_source_does_not_mutate_existing_index(self) -> None:
        self.add_skill("alpha", "Alpha handles one coherent job.", "# Instructions\n\nWork.\n#alpha")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        before = skill_graph.stats(self.db)["counts"]
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text("oops", encoding="utf-8")
        result = skill_graph.refresh_index(self.root, self.db, None, strict=False)
        self.assertFalse(result["ok"])
        self.assertEqual(skill_graph.stats(self.db)["counts"], before)

    def test_duplicate_names_are_rejected(self) -> None:
        first = self.root / "one"
        second = self.root / "two"
        first.mkdir()
        second.mkdir()
        (first / "SKILL.md").write_text(skill("same-skill", "First description."), encoding="utf-8")
        (second / "SKILL.md").write_text(skill("same-skill", "Second description."), encoding="utf-8")
        _, issues = skill_graph.load_records(self.root)
        self.assertIn("duplicate-name", {issue.code for issue in issues})
        result = skill_graph.refresh_index(self.root, self.db, None, strict=False)
        self.assertFalse(result["ok"])
    def test_check_detects_stale_skill_and_manifest(self) -> None:
        self.add_skill("alpha", "Alpha handles one coherent job.", "# Instructions\n\nWork.\n#alpha")
        manifest = {"schema_version": 1, "skills": [{"id": "alpha", "relations": []}]}
        manifest_path = self.root / "graph.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, manifest_path, strict=False)["ok"])
        self.assertTrue(skill_graph.check_index(self.db, self.root, manifest_path)["ok"])
        (self.root / "alpha" / "SKILL.md").write_text(
            skill("alpha", "Alpha now handles a different job."), encoding="utf-8"
        )
        stale = skill_graph.check_index(self.db, self.root, manifest_path)
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["changed_skills"], ["alpha"])
        self.assertTrue(stale["stale"])

    def test_route_assigns_bounded_roles_from_typed_graph(self) -> None:
        self.add_skill("lead", "Lead indexes and routes tasks.", "# Instructions\\n\\nIndex tasks.\\n#routing")
        self.add_skill("compose", "Compose transforms routed tasks.", "# Instructions\\n\\nTransform.\\n#routing")
        self.add_skill("dependency", "Dependency supplies required context.", "# Instructions\\n\\nSupply context.\\n#routing")
        self.add_skill("validator", "Validator checks routed output.", "# Instructions\\n\\nCheck output.\\n#validation")
        self.add_skill("alternative", "Alternative is a fallback approach.", "# Instructions\\n\\nFallback.\\n#routing")
        manifest = {
            "schema_version": 1,
            "skills": [
                {"id": "lead", "relations": [
                    {"type": "composes", "target": "compose", "weight": 0.9},
                    {"type": "requires", "target": "dependency", "weight": 0.8},
                    {"type": "validates", "target": "validator", "weight": 0.95},
                    {"type": "alternative-to", "target": "alternative", "weight": 0.7},
                ]},
            ],
        }
        manifest_path = self.root / "graph.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, manifest_path, strict=False)["ok"])
        routed = skill_graph.route(self.db, "index and route tasks", None, None, 0.0, 5, 1)
        self.assertEqual(routed["lead"]["skill_id"], "lead")
        self.assertEqual([item["skill_id"] for item in routed["support"]], ["compose", "dependency"])
        self.assertEqual(routed["validator"]["skill_id"], "validator")
        self.assertEqual(routed["fallback"]["skill_id"], "alternative")
        self.assertLessEqual(len(routed["support"]), 3)

    def test_journal_redacts_provenance_and_links_outcomes(self) -> None:
        journal = Path(self.temp.name) / "journal.sqlite3"
        self.assertTrue(skill_graph.journal_init(journal)["ok"])
        decision = skill_graph.append_journal_event(
            journal,
            "decision",
            {"query": "deploy with token sk-live-123456789012", "authorization": "Bearer abcdefghijklmnop", "route": {"lead": "deploy"}},
            None,
            {"index": "index.sqlite3", "source_root": str(self.root), "user_email": "person@example.com"},
        )
        self.assertEqual(decision["payload"]["authorization"], "[REDACTED]")
        self.assertIn("[REDACTED_SECRET]", decision["payload"]["query"])
        self.assertNotIn("sk-live", decision["payload"]["query"])
        outcome = skill_graph.append_journal_event(
            journal,
            "outcome",
            {"status": "success", "evidence": "preview URL returned"},
            decision["event_id"],
            {"operator": "test"},
        )
        shown = skill_graph.journal_show(journal, 10)
        self.assertTrue(shown["ok"])
        self.assertEqual(shown["events"][0]["parent_event_id"], decision["event_id"])
        self.assertEqual(skill_graph.journal_verify(journal)["events"], 2)
        journal_files = [journal, Path(str(journal) + "-wal"), Path(str(journal) + "-shm")]
        raw = b"".join(path.read_bytes() for path in journal_files if path.exists())
        self.assertNotIn(b"Bearer abcdefghijklmnop", raw)
        self.assertNotIn(b"person@example.com", raw)

    def test_journal_append_only_triggers_and_failed_parent_rollback(self) -> None:
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        skill_graph.append_journal_event(journal, "note", {"message": "first"}, None, {})
        with self.assertRaises(sqlite3.IntegrityError):
            conn = skill_graph.connect_journal(journal)
            try:
                with conn:
                    conn.execute("DELETE FROM journal_events")
            finally:
                conn.close()
        before = skill_graph.journal_verify(journal)
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.append_journal_event(journal, "outcome", {"status": "success"}, "missing", {})
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.append_journal_event(journal, "outcome", {"status": "unknown"}, None, {})
        self.assertEqual(skill_graph.journal_verify(journal), before)

    def test_journal_detects_tampering_after_trigger_is_removed(self) -> None:
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        skill_graph.append_journal_event(journal, "note", {"message": "original"}, None, {})
        conn = skill_graph.connect_journal(journal)
        try:
            with conn:
                conn.execute("DROP TRIGGER journal_events_no_update")
                conn.execute("UPDATE journal_events SET payload_json='{\"message\":\"changed\"}' WHERE sequence=1")
        finally:
            conn.close()
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.journal_verify(journal)

    def test_dashboard_aggregates_local_graph_journal_and_reports(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\\n\\nDeploy safely.")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        journal = Path(self.temp.name) / "execution.sqlite3"
        skill_graph.journal_init(journal)
        decision = skill_graph.append_journal_event(journal, "decision", {"query": "index catalogs", "route": {"lead": {"skill_id": "alpha", "confidence": 0.9}}}, None, {})
        skill_graph.append_journal_event(journal, "outcome", {"status": "success"}, decision["event_id"], {})
        reports = Path(self.temp.name) / "reports"
        reports.mkdir()
        (reports / "calibration.json").write_text(json.dumps({"created_at": "2026-01-01", "calibration": {"global_policy": {"threshold": 0.8, "samples": 4, "eligible": True, "selected_wilson_lower": 0.5}, "domain_policies": {"software": {"threshold": 0.7, "samples": 3, "eligible": True}}}, "temporal_drift": {"status": "in_sync"}, "heldout": {"metrics": {"positive_hit_rate": 1.0}}}), encoding="utf-8")
        (reports / "benchmark.json").write_text(json.dumps({"benchmark": "synthetic-skill-corpus", "passed": True, "total_seconds": 1.2, "results": [{"count": 2, "status": "completed"}]}), encoding="utf-8")
        (reports / "weekly.json").write_text(json.dumps({
            "schema_version": 1,
            "report": "weekly-operations",
            "read_only": True,
            "period": {"start": "2026-01-01", "end": "2026-01-08", "days": 7},
            "action_items": [
                {"id": "routing_failures", "priority": "high", "status": "open", "signal": "routing_failures", "recommended_action": "Inspect the attributed skill.", "evidence": {"failed_outcomes": 2, "by_skill": {"alpha": 2}}, "requires_human_review": True},
                {"id": "insufficient_drift_samples", "priority": "low", "status": "resolved", "signal": "insufficient_drift_samples", "recommended_action": "Keep collecting outcomes.", "evidence": {"observations": 1}, "requires_human_review": True},
            ],
        }), encoding="utf-8")
        data = dashboard.DashboardData(self.db, journal, reports)
        overview = data.overview()
        self.assertTrue(overview["graph"]["ok"])
        self.assertEqual(overview["graph"]["counts"]["skills"], 2)
        self.assertEqual(overview["journal"]["routes"], 1)
        self.assertEqual(data.calibration()["latest"]["global_policy"]["threshold"], 0.8)
        self.assertEqual(data.benchmarks()["latest"]["cases"], 1)
        weekly = data.weekly()
        self.assertEqual(weekly["status"], "ready")
        self.assertEqual(weekly["latest"]["counts"], {"action_items": 2, "open_items": 1, "by_priority": {"high": 1, "low": 1}})
        self.assertEqual(weekly["latest"]["action_items"][0]["status"], "open")
        self.assertEqual(weekly["latest"]["action_items"][0]["affected_skills"], ["alpha"])
        freshness = weekly["latest"]["freshness"]
        self.assertEqual(freshness["status"], "stale")
        self.assertEqual(freshness["report_period_end"], "2026-01-08")
        self.assertIsNotNone(freshness["report_modified_at"])
        self.assertEqual(freshness["journal_head_at"], data.journal(1)["events"][0]["created_at"])
        self.assertEqual(freshness["period_vs_journal_head"], "behind")
        self.assertIn("report_period_precedes_journal_head", freshness["reasons"])
        os.utime(reports / "weekly.json", (0, 0))
        self.assertEqual(data.weekly()["latest"]["freshness"]["file_vs_journal_head"], "older")
        self.assertEqual(overview["weekly"]["counts"]["open_items"], 1)
        self.assertEqual(weekly["scan"]["max_entries"], dashboard.DashboardData.REPORT_SCAN_MAX_ENTRIES)
        self.assertIn("elapsed_ms", weekly["scan"])
        self.assertEqual(data.graph()["edges"], [])

    def test_dashboard_scan_excludes_benchmark_artifact_trees(self) -> None:
        reports = Path(self.temp.name) / "curated-reports"
        reports.mkdir()
        (reports / "weekly.json").write_text(json.dumps({"report": "weekly-operations", "period": {}, "action_items": []}), encoding="utf-8")
        (reports / "benchmark-full.json").write_text(json.dumps({"benchmark": "synthetic", "results": []}), encoding="utf-8")
        benchmark_tree = reports / "bench-full"
        (benchmark_tree / "skills" / "one").mkdir(parents=True)
        (benchmark_tree / "skills" / "one" / "SKILL.md").write_text("# noise", encoding="utf-8")
        (benchmark_tree / "benchmark.json").write_text(json.dumps({"benchmark": "should-be-separated"}), encoding="utf-8")
        data = dashboard.DashboardData(self.db, self.db, reports)
        files, scan = data._scan_report_files()
        names = {path.name for path in files}
        self.assertEqual(names, {"weekly.json", "benchmark-full.json"})
        self.assertTrue(scan["curated_only"])
        self.assertEqual(scan["skipped_benchmark_trees"], 1)
        self.assertEqual(scan["skipped_benchmark_tree_names"], ["bench-full"])
        self.assertTrue(any("bench-full" in path for path in scan["benchmark_roots"]))
        benchmark_result = data.benchmarks()
        self.assertEqual({report["name"] for report in benchmark_result["reports"]}, {"benchmark-full.json", "benchmark.json"})
        self.assertTrue(benchmark_result["scan"]["independent_from_curated_scan"])
        self.assertTrue(any("bench-full" in path for path in benchmark_result["scan"]["benchmark_roots"]))

    def test_dashboard_curated_and_benchmark_apis_use_independent_scan_statistics(self) -> None:
        reports = Path(self.temp.name) / "separated-report-apis"
        benchmark_tree = reports / "bench-smoke"
        nested_results = benchmark_tree / "results"
        nested_results.mkdir(parents=True)
        operational = reports / "operational.json"
        top_benchmark = reports / "top-benchmark.json"
        nested_benchmark = nested_results / "benchmark.json"
        operational.write_text(json.dumps({"report": "weekly-operations", "period": {}, "action_items": []}), encoding="utf-8")
        top_benchmark.write_text(json.dumps({"benchmark": "top-level", "results": [{"count": 3, "status": "completed"}]}), encoding="utf-8")
        nested_benchmark.write_text(json.dumps({"benchmark": "tree-artifact", "results": [{"count": 10, "status": "completed"}]}), encoding="utf-8")
        data = dashboard.DashboardData(self.db, self.db, reports)
        curated = data.curated_reports()
        benchmarks = data.benchmarks()
        self.assertEqual([report["name"] for report in curated["reports"]], ["operational.json"])
        self.assertEqual(curated["benchmark_documents_separated"], 1)
        self.assertEqual(curated["scan"]["scope"], "curated_reports")
        self.assertTrue(curated["scan"]["independent_from_benchmark_scan"])
        self.assertEqual({report["name"] for report in benchmarks["reports"]}, {"top-benchmark.json", "benchmark.json"})
        benchmark_scan = benchmarks["scan"]
        self.assertEqual(benchmark_scan["scope"], "benchmark_reports")
        self.assertTrue(benchmark_scan["independent_from_curated_scan"])
        self.assertFalse(benchmark_scan["cache"]["shared_with_curated_scan"])
        self.assertTrue(any("bench-smoke" in path for path in benchmark_scan["benchmark_roots"]))
        self.assertNotEqual(curated["scan"].get("entries_scanned"), benchmark_scan["entries_scanned"])
        self.assertIn(str(nested_benchmark), {report["path"] for report in benchmarks["reports"]})

        dashboard.DashboardHandler.data = data
        local_data = dashboard.DashboardHandler.data
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(f"{base}/api/curated-reports?scan_max_depth=2", timeout=3) as response:
                http_curated = json.loads(response.read().decode("utf-8"))
            with urlopen(f"{base}/api/benchmarks?scan_max_depth=2", timeout=3) as response:
                http_benchmarks = json.loads(response.read().decode("utf-8"))
            with urlopen(f"{base}/api/overview", timeout=3) as response:
                overview = json.loads(response.read().decode("utf-8"))
            self.assertEqual(http_curated["selection_mode"], "prefix_curation")
            self.assertEqual(http_benchmarks["scan"]["scope"], "benchmark_reports")
            self.assertTrue(http_benchmarks["scan"]["independent_from_curated_scan"])
            self.assertTrue(overview["curated_reports"]["scan"]["cache"]["status"] in {"empty", "miss", "rebuilt", "hit", "invalidated", "bypassed"})
            self.assertTrue(overview["benchmarks"]["scan"]["independent_from_curated_scan"])
        finally:
            dashboard.DashboardHandler.data = local_data
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_dashboard_skipped_benchmark_tree_inventory_is_shallow_and_non_recursive(self) -> None:
        reports = Path(self.temp.name) / "tree-inventory-reports"
        benchmark_tree = reports / "bench-smoke"
        nested = benchmark_tree / "nested"
        nested.mkdir(parents=True)
        direct = benchmark_tree / "direct.json"
        nested_file = nested / "deep.json"
        direct.write_text('{"size":"direct"}', encoding="utf-8")
        nested_file.write_text(json.dumps({"payload": "x" * 2_000}), encoding="utf-8")
        configured = Path(self.temp.name) / "configured-benchmark"
        configured.mkdir()
        (configured / "configured.json").write_text('{"configured":true}', encoding="utf-8")
        missing = Path(self.temp.name) / "missing-benchmark"
        data = dashboard.DashboardData(self.db, self.db, reports, benchmark_trees=[configured, missing])
        inventory = data.skipped_benchmark_trees()
        self.assertTrue(inventory["ok"])
        self.assertFalse(inventory["recursive_traversal"])
        self.assertEqual(inventory["scope"], "skipped_benchmark_trees")
        self.assertEqual(inventory["counts"]["trees"], 3)
        self.assertEqual(inventory["counts"]["errors"], 1)
        trees = {Path(tree["path"]).name: tree for tree in inventory["trees"]}
        smoke = trees["bench-smoke"]
        self.assertTrue(smoke["active"])
        self.assertIn("bench-", smoke["exclusion_sources"])
        self.assertEqual(smoke["direct_file_count"], 1)
        self.assertEqual(smoke["direct_directory_count"], 1)
        self.assertEqual(smoke["direct_file_bytes"], direct.stat().st_size)
        self.assertEqual(smoke["shallow_size_bytes"], smoke["root_metadata_size_bytes"] + direct.stat().st_size)
        self.assertLess(smoke["shallow_size_bytes"], nested_file.stat().st_size)
        self.assertIn("configured", trees["configured-benchmark"]["exclusion_sources"])
        self.assertIsNotNone(trees["missing-benchmark"]["error"])

        dashboard.DashboardHandler.data = data
        local_data = dashboard.DashboardHandler.data
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/skipped-benchmark-trees", timeout=3) as response:
                http_inventory = json.loads(response.read().decode("utf-8"))
            self.assertEqual(http_inventory["scope"], "skipped_benchmark_trees")
            self.assertFalse(http_inventory["recursive_traversal"])
            self.assertEqual(http_inventory["counts"], inventory["counts"])
        finally:
            dashboard.DashboardHandler.data = local_data
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_dashboard_curated_report_manifest_is_authoritative_allowlist(self) -> None:
        reports = Path(self.temp.name) / "manifest-reports"
        benchmark_tree = reports / "bench-smoke"
        benchmark_tree.mkdir(parents=True)
        weekly_path = reports / "weekly.json"
        benchmark_path = benchmark_tree / "operational.json"
        weekly_path.write_text(json.dumps({"report": "weekly-operations", "period": {"start": "2026-01-01", "end": "2026-01-08"}, "action_items": []}), encoding="utf-8")
        benchmark_path.write_text(json.dumps({"report": "weekly-operations", "period": {"start": "2026-01-08", "end": "2026-01-15"}, "action_items": []}), encoding="utf-8")
        (reports / "unlisted.json").write_text(json.dumps({"report": "weekly-operations", "action_items": []}), encoding="utf-8")
        manifest = Path(self.temp.name) / "curated-reports.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "kind": "skill-supermind-curated-report-manifest",
            "reports": ["weekly.json", "bench-smoke/operational.json"],
        }), encoding="utf-8")
        data = dashboard.DashboardData(self.db, self.db, reports, report_manifest=manifest)
        files, scan = data._scan_report_files()
        self.assertEqual(files, [weekly_path, benchmark_path])
        self.assertEqual(scan["selection_mode"], "explicit_manifest")
        self.assertEqual(scan["skipped_benchmark_trees"], 0)
        self.assertEqual(scan["report_manifest"]["report_count"], 2)
        health_manifest = data.scan_configuration()["report_manifest"]
        self.assertTrue(health_manifest["enabled"])
        self.assertEqual(health_manifest["reports"], ["weekly.json", "bench-smoke/operational.json"])
        self.assertEqual(len(health_manifest["sha256"]), 64)
        dry_run = data.dry_run_scan()
        self.assertEqual(dry_run["selection_mode"], "explicit_manifest")
        self.assertEqual(dry_run["counts"]["included"], 2)
        self.assertFalse(dry_run["unlisted_paths_enumerated"])
        self.assertEqual({item["path"] for item in dry_run["paths"]["included"]}, {"weekly.json", "bench-smoke/operational.json"})
        with data.report_scan_limit_overrides({"scan_max_files": "1"}):
            capped = data.dry_run_scan()
        self.assertEqual([item["path"] for item in capped["paths"]["included"]], ["weekly.json"])
        self.assertIn("bench-smoke/operational.json", {item["path"] for item in capped["paths"]["capped"]})
        self.assertEqual(dashboard.build_parser().parse_args(["--report-manifest", str(manifest)]).report_manifest, manifest)

    def test_dashboard_curated_report_manifest_rejects_unsafe_documents(self) -> None:
        reports = Path(self.temp.name) / "invalid-manifest-reports"
        reports.mkdir()
        manifest = Path(self.temp.name) / "invalid-curated-reports.json"
        invalid_documents = [
            {"schema_version": 2, "kind": "skill-supermind-curated-report-manifest", "reports": []},
            {"schema_version": 1, "kind": "wrong-kind", "reports": []},
            {"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": "weekly.json"},
            {"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": ["../outside.json"]},
            {"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": ["C:/outside.json"]},
            {"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": ["folder\\weekly.json"]},
            {"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": ["weekly.txt"]},
            {"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": ["weekly.json", "weekly.json"]},
        ]
        for document in invalid_documents:
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                dashboard.DashboardData(self.db, self.db, reports, report_manifest=manifest)
        with self.assertRaises(ValueError):
            dashboard.DashboardData(self.db, self.db, reports, report_manifest=Path(self.temp.name) / "missing-manifest.json")

    def test_dashboard_scan_limits_are_configurable_and_validated(self) -> None:
        reports = Path(self.temp.name) / "configured-reports"
        reports.mkdir()
        report_path = reports / "weekly.json"
        report_path.write_text(json.dumps({"report": "weekly-operations", "action_items": []}), encoding="utf-8")
        data = dashboard.DashboardData(self.db, self.db, reports, report_scan_max_entries=7, report_scan_max_depth=2, report_scan_max_files=3, report_scan_max_file_bytes=1234)
        self.assertEqual(data.scan_configuration()["limits"], {"max_entries": 7, "max_depth": 2, "max_files": 3, "max_file_bytes": 1234})
        _, first = data._scan_report_files()
        _, second = data._scan_report_files()
        self.assertEqual(first["cache"]["status"], "rebuilt")
        self.assertEqual(first["cache"]["checks"], 1)
        self.assertEqual(first["cache"]["hit_rate"], 0)
        self.assertIsNotNone(first["cache"]["last_rebuilt_at"])
        self.assertEqual(second["cache"]["status"], "hit")
        self.assertEqual(second["cache"]["freshness"], "fresh")
        self.assertEqual(second["cache"]["hits"], 1)
        self.assertEqual(second["cache"]["checks"], 2)
        self.assertEqual(second["cache"]["hit_rate"], 0.5)
        self.assertEqual(second["cache"]["last_rebuilt_at"], first["cache"]["last_rebuilt_at"])
        self.assertEqual(second["cache"]["validation"], "directory_and_entry_metadata")
        report_path.write_text(json.dumps({"report": "weekly-operations", "action_items": [{"id": "new"}]}), encoding="utf-8")
        _, invalidated = data._scan_report_files()
        self.assertEqual(invalidated["cache"]["status"], "rebuilt")
        self.assertTrue(any(reason.startswith("entry_changed:") for reason in invalidated["cache"]["last_invalidation_reasons"]))
        (reports / "new-report.json").write_text(json.dumps({"report": "weekly-operations", "action_items": []}), encoding="utf-8")
        _, directory_invalidated = data._scan_report_files()
        self.assertTrue(any(reason.startswith("directory_changed:") for reason in directory_invalidated["cache"]["last_invalidation_reasons"]))
        with self.assertRaises(ValueError):
            dashboard.DashboardData(self.db, self.db, reports, report_scan_max_entries=0)

    def test_dashboard_cache_content_hash_detects_metadata_preserving_changes(self) -> None:
        reports = Path(self.temp.name) / "hashed-reports"
        reports.mkdir()
        report_path = reports / "weekly.json"
        report_path.write_text('{"value":"one"}', encoding="utf-8")
        metadata_only = dashboard.DashboardData(self.db, self.db, reports)
        content_hashed = dashboard.DashboardData(self.db, self.db, reports, cache_content_hash=True)
        self.assertEqual(metadata_only.scan_configuration()["cache"]["validation"], "directory_and_entry_metadata")
        self.assertEqual(content_hashed.scan_configuration()["cache"]["validation"], "directory_and_entry_metadata+sha256")
        self.assertFalse(dashboard.build_parser().parse_args([]).cache_content_hash)
        self.assertTrue(dashboard.build_parser().parse_args(["--cache-content-hash"]).cache_content_hash)
        for data in (metadata_only, content_hashed):
            _, first = data._scan_report_files()
            _, second = data._scan_report_files()
            self.assertEqual(first["cache"]["status"], "rebuilt")
            self.assertEqual(second["cache"]["status"], "hit")
        self.assertEqual(content_hashed.scan_configuration()["cache"]["content_hashed_files"], 1)

        original_stat = report_path.stat()
        report_path.write_text('{"value":"two"}', encoding="utf-8")
        self.assertEqual(report_path.stat().st_size, original_stat.st_size)
        os.utime(report_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        _, metadata_hit = metadata_only._scan_report_files()
        self.assertEqual(metadata_hit["cache"]["status"], "hit")
        _, content_rebuilt = content_hashed._scan_report_files()
        self.assertEqual(content_rebuilt["cache"]["status"], "rebuilt")
        self.assertEqual(content_rebuilt["cache"]["invalidations"], 1)
        self.assertTrue(any(reason.startswith("entry_content_changed:") for reason in content_rebuilt["cache"]["last_invalidation_reasons"]))
        _, content_hit = content_hashed._scan_report_files()
        self.assertEqual(content_hit["cache"]["status"], "hit")
        with self.assertRaises(ValueError):
            dashboard.DashboardData(self.db, self.db, reports, cache_content_hash=1)

    def test_dashboard_scan_limit_overrides_are_request_scoped_and_bypass_shared_cache(self) -> None:
        reports = Path(self.temp.name) / "override-reports"
        nested = reports / "nested"
        nested.mkdir(parents=True)
        top_report = reports / "top.json"
        nested_report = nested / "child.json"
        top_report.write_text(json.dumps({"report": "weekly-operations", "action_items": []}), encoding="utf-8")
        nested_report.write_text(json.dumps({"report": "weekly-operations", "action_items": []}), encoding="utf-8")
        data = dashboard.DashboardData(self.db, self.db, reports, report_scan_max_entries=20, report_scan_max_depth=3, report_scan_max_files=10, report_scan_max_file_bytes=1024)
        data._scan_report_files()  # Warm nested-directory metadata before asserting stable cache hits.
        data._scan_report_files()
        default_files, first = data._scan_report_files()
        cached_files, second = data._scan_report_files()
        self.assertEqual({path.name for path in default_files}, {"top.json", "child.json"})
        self.assertEqual(first["cache"]["status"], "hit")
        self.assertEqual(second["cache"]["status"], "hit")
        self.assertEqual(data.scan_configuration()["cache"]["checks"], 4)

        with data.report_scan_limit_overrides({"scan_max_depth": "1", "scan_max_files": "2"}):
            overridden_files, overridden = data._scan_report_files()
            configuration = data.scan_configuration()
        self.assertEqual({path.name for path in overridden_files}, {"top.json", "child.json"})
        self.assertEqual(overridden["max_depth"], 1)
        self.assertEqual(overridden["max_files"], 2)
        self.assertEqual(overridden["request_limit_overrides"], {"scan_max_depth": 1, "scan_max_files": 2})
        self.assertEqual(overridden["cache"]["status"], "bypassed")
        self.assertTrue(overridden["cache"]["bypassed_for_limit_overrides"])
        self.assertEqual(overridden["cache"]["checks"], 4)
        self.assertEqual(configuration["limits"], {"max_entries": 20, "max_depth": 1, "max_files": 2, "max_file_bytes": 1024})
        self.assertEqual(configuration["configured_limits"], {"max_entries": 20, "max_depth": 3, "max_files": 10, "max_file_bytes": 1024})
        self.assertEqual(configuration["limit_overrides"], {"scan_max_depth": 1, "scan_max_files": 2})

        post_override_files, post_override = data._scan_report_files()
        self.assertEqual({path.name for path in post_override_files}, {path.name for path in cached_files})
        self.assertEqual(post_override["cache"]["status"], "hit")
        self.assertEqual(data.scan_configuration()["limits"], {"max_entries": 20, "max_depth": 3, "max_files": 10, "max_file_bytes": 1024})
        for invalid in ({"scan_max_entries": "0"}, {"scan_max_depth": "not-an-integer"}, {"scan_max_files": str(dashboard.DashboardData.REPORT_SCAN_OVERRIDE_MAX_FILES + 1)}, {"unknown": "1"}, {"scan_max_depth": 1.5}):
            with self.assertRaises(ValueError):
                with data.report_scan_limit_overrides(invalid):
                    self.fail("invalid override entered request scope")

    def test_dashboard_scan_limit_override_http_contract_is_validated(self) -> None:
        reports = Path(self.temp.name) / "override-http-reports"
        reports.mkdir()
        (reports / "weekly.json").write_text(json.dumps({"report": "weekly-operations", "period": {}, "action_items": []}), encoding="utf-8")
        (reports / "second.json").write_text(json.dumps({"report": "weekly-operations", "period": {}, "action_items": []}), encoding="utf-8")
        report_manifest = Path(self.temp.name) / "http-curated-reports.json"
        report_manifest.write_text(json.dumps({"schema_version": 1, "kind": "skill-supermind-curated-report-manifest", "reports": ["weekly.json", "second.json"]}), encoding="utf-8")
        dashboard.DashboardHandler.data = dashboard.DashboardData(self.db, self.db, reports, report_scan_max_entries=9, report_scan_max_depth=2, report_scan_max_files=3, report_scan_max_file_bytes=1234, report_manifest=report_manifest)
        local_data = dashboard.DashboardHandler.data
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(f"{base}/api/health?scan_max_entries=7&scan_max_depth=1&scan_max_files=2&scan_max_file_bytes=512", timeout=3) as response:
                health = json.loads(response.read().decode("utf-8"))["scan"]
            self.assertEqual(health["limits"], {"max_entries": 7, "max_depth": 1, "max_files": 2, "max_file_bytes": 512})
            self.assertEqual(health["configured_limits"], {"max_entries": 9, "max_depth": 2, "max_files": 3, "max_file_bytes": 1234})
            self.assertEqual(health["limit_overrides"], {"scan_max_entries": 7, "scan_max_depth": 1, "scan_max_files": 2, "scan_max_file_bytes": 512})
            self.assertTrue(health["report_manifest"]["enabled"])
            self.assertEqual(health["report_manifest"]["reports"], ["weekly.json", "second.json"])
            with urlopen(f"{base}/api/weekly?scan_max_depth=1", timeout=3) as response:
                weekly = json.loads(response.read().decode("utf-8"))
            self.assertEqual(weekly["scan"]["max_depth"], 1)
            self.assertEqual(weekly["scan"]["cache"]["status"], "bypassed")
            with urlopen(f"{base}/api/weekly?scan_max_entries=1&scan_max_files=1", timeout=3) as response:
                capped = json.loads(response.read().decode("utf-8"))["scan"]
            self.assertEqual(capped["max_entries"], 1)
            self.assertEqual(capped["max_files"], 1)
            self.assertTrue(capped["truncated"])
            with urlopen(f"{base}/api/weekly?scan_max_file_bytes=10", timeout=3) as response:
                byte_capped = json.loads(response.read().decode("utf-8"))["scan"]
            self.assertEqual(byte_capped["max_file_bytes"], 10)
            self.assertEqual(byte_capped["files_returned"], 0)
            self.assertEqual(byte_capped["skipped_large"], 2)
            with urlopen(f"{base}/api/scan/dry-run?scan_max_file_bytes=512", timeout=3) as response:
                dry_run = json.loads(response.read().decode("utf-8"))
            self.assertTrue(dry_run["dry_run"])
            self.assertEqual(dry_run["schema_version"], 1)
            self.assertEqual(dry_run["limit_overrides"], {"scan_max_file_bytes": 512})
            self.assertEqual(dry_run["cache"], {"status": "bypassed", "reason": "dry_run"})
            with self.assertRaises(HTTPError) as invalid_dry_run:
                urlopen(f"{base}/api/scan/dry-run?scan_max_depth=0", timeout=3)
            self.assertEqual(invalid_dry_run.exception.code, 400)
            invalid_dry_run.exception.close()
            for query in ("scan_max_depth=0", "scan_max_depth=abc", "scan_max_dept=1", "scan_max_depth=1&scan_max_depth=2", f"scan_max_files={dashboard.DashboardData.REPORT_SCAN_OVERRIDE_MAX_FILES + 1}"):
                with self.assertRaises(HTTPError) as invalid:
                    urlopen(f"{base}/api/weekly?{query}", timeout=3)
                self.assertEqual(invalid.exception.code, 400)
                invalid.exception.close()
            self.assertEqual(local_data.scan_configuration()["limits"], {"max_entries": 9, "max_depth": 2, "max_files": 3, "max_file_bytes": 1234})
        finally:
            dashboard.DashboardHandler.data = local_data
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_dashboard_dry_run_scan_explains_included_skipped_capped_and_rejected_paths(self) -> None:
        reports = Path(self.temp.name) / "dry-run-reports"
        (reports / "bench-smoke").mkdir(parents=True)
        (reports / "deep" / "nested").mkdir(parents=True)
        (reports / "deep" / "nested" / "child.json").write_text(json.dumps({"report": "weekly-operations"}), encoding="utf-8")
        (reports / "bench-smoke" / "artifact.json").write_text(json.dumps({"benchmark": "smoke"}), encoding="utf-8")
        included = reports / "included.json"
        invalid = reports / "invalid.json"
        non_object = reports / "array.json"
        included.write_text(json.dumps({"report": "weekly-operations", "action_items": []}), encoding="utf-8")
        invalid.write_text('{"report":', encoding="utf-8")
        non_object.write_text("[]", encoding="utf-8")
        oversized = reports / "oversized.json"
        oversized.write_text(json.dumps({"value": "x" * 100}), encoding="utf-8")
        (reports / "notes.txt").write_text("operator notes", encoding="utf-8")
        selected_time = 2_000_000_000
        for path in (included, invalid):
            os.utime(path, ns=(selected_time * 1_000_000_000, selected_time * 1_000_000_000))
        data = dashboard.DashboardData(self.db, self.db, reports, report_scan_max_entries=100, report_scan_max_depth=1, report_scan_max_files=2, report_scan_max_file_bytes=100)
        data.weekly()
        cache_before = data.scan_configuration()["cache"]
        result = data.dry_run_scan()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["effective_limits"], {"max_entries": 100, "max_depth": 1, "max_files": 2, "max_file_bytes": 100})
        self.assertEqual(result["counts"], {"included": 1, "skipped": 2, "capped": 2, "rejected": 2, "total": 7})
        self.assertEqual([item["path"] for item in result["paths"]["included"]], [str(included)])
        self.assertEqual({item["reason"] for item in result["paths"]["skipped"]}, {"benchmark_tree", "non_report_extension"})
        self.assertEqual({item["reason"] for item in result["paths"]["capped"]}, {"max_depth", "max_files"})
        self.assertEqual({item["reason"] for item in result["paths"]["rejected"]}, {"invalid_json", "max_file_bytes"})
        self.assertEqual(result["cache"], {"status": "bypassed", "reason": "dry_run"})
        self.assertTrue(result["unseen_paths_enumerated"])
        self.assertEqual(data.scan_configuration()["cache"], cache_before)
        with data.report_scan_limit_overrides({"scan_max_files": "10"}):
            expanded = data.dry_run_scan()
        self.assertIn("non_object_document", {item["reason"] for item in expanded["paths"]["rejected"]})
        self.assertEqual(data.scan_configuration()["cache"], cache_before)
        with data.report_scan_limit_overrides({"scan_max_entries": "1"}):
            capped_entries = data.dry_run_scan()
        self.assertTrue(capped_entries["truncated"])
        self.assertFalse(capped_entries["unseen_paths_enumerated"])
        self.assertEqual(data.scan_configuration()["cache"], cache_before)

    def test_dashboard_report_scan_is_bounded_and_observable(self) -> None:
        reports = Path(self.temp.name) / "bounded-reports"
        reports.mkdir()
        for index in range(3):
            (reports / f"report-{index}.json").write_text(json.dumps({"index": index}), encoding="utf-8")
        original_limits = (
            dashboard.DashboardData.REPORT_SCAN_MAX_ENTRIES,
            dashboard.DashboardData.REPORT_SCAN_MAX_DEPTH,
            dashboard.DashboardData.REPORT_SCAN_MAX_FILES,
        )
        try:
            dashboard.DashboardData.REPORT_SCAN_MAX_ENTRIES = 2
            dashboard.DashboardData.REPORT_SCAN_MAX_DEPTH = 1
            dashboard.DashboardData.REPORT_SCAN_MAX_FILES = 1
            data = dashboard.DashboardData(self.db, self.db, reports)
            files, scan = data._scan_report_files()
        finally:
            (dashboard.DashboardData.REPORT_SCAN_MAX_ENTRIES, dashboard.DashboardData.REPORT_SCAN_MAX_DEPTH, dashboard.DashboardData.REPORT_SCAN_MAX_FILES) = original_limits
        self.assertEqual(len(files), 1)
        self.assertEqual(scan["entries_scanned"], 2)
        self.assertTrue(scan["truncated"])
        self.assertEqual(scan["max_entries"], 2)
        self.assertEqual(scan["max_depth"], 1)
        self.assertEqual(scan["max_files"], 1)
        self.assertEqual(scan["skipped_links"], 0)

    def test_dashboard_action_overlay_persists_without_mutating_weekly_report(self) -> None:
        reports = Path(self.temp.name) / "weekly-reports"
        reports.mkdir()
        report_path = reports / "weekly.json"
        report_path.write_text(json.dumps({
            "schema_version": 1,
            "report": "weekly-operations",
            "period": {"start": "2026-01-01", "end": "2026-01-08"},
            "action_items": [{"id": "routing_failures", "priority": "high", "signal": "routing_failures", "status": "open"}],
        }), encoding="utf-8")
        source_before = report_path.read_bytes()
        state_path = Path(self.temp.name) / "operator-state.json"
        data = dashboard.DashboardData(self.db, self.db, reports, state_path)
        weekly = data.weekly()
        report_id = weekly["latest"]["report_id"]
        self.assertEqual(weekly["latest"]["action_items"][0]["status"], "open")

        result = data.set_action_status(report_id, "routing_failures", "acknowledged")
        self.assertEqual(result["status"], "acknowledged")
        self.assertEqual(report_path.read_bytes(), source_before)
        persisted = dashboard.DashboardData(self.db, self.db, reports, state_path).weekly()
        self.assertEqual(persisted["latest"]["action_items"][0]["status"], "acknowledged")
        self.assertEqual(persisted["latest"]["action_items"][0]["status_source"], "operator")
        self.assertEqual(persisted["latest"]["status_counts"], {"acknowledged": 1})
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["items"][report_id]["routing_failures"]["status"], "acknowledged")

        reopened = data.set_action_status(report_id, "routing_failures", "reopen", "Evidence is incomplete; revisit the route.", "on-call@example")
        self.assertEqual(reopened["status"], "reopened")
        reopened_item = dashboard.DashboardData(self.db, self.db, reports, state_path).weekly()["latest"]["action_items"][0]
        self.assertEqual(reopened_item["status"], "open")
        self.assertEqual(reopened_item["operator_status"], "reopened")
        self.assertEqual(reopened_item["operator_note"], "Evidence is incomplete; revisit the route.")
        self.assertEqual(reopened_item["actor"], "on-call@example")
        self.assertEqual(reopened_item["status_source"], "operator")
        self.assertEqual(dashboard.DashboardData(self.db, self.db, reports, state_path).weekly()["latest"]["status_counts"], {"open": 1})
        with self.assertRaises(ValueError):
            data.set_action_status(report_id, "routing_failures", "reopen", " ")
        with self.assertRaises(ValueError):
            data.set_action_status(report_id, "routing_failures", "reopen", "x" * 2_001)
        with self.assertRaises(ValueError):
            data.set_action_status(report_id, "routing_failures", "reopen", "valid note", "x" * 257)
        with self.assertRaises(ValueError):
            data.set_action_status(report_id, "routing_failures", "open")
        with self.assertRaises(ValueError):
            data.set_action_status(report_id, "missing", "resolved")
        with self.assertRaises(ValueError):
            dashboard.DashboardData(self.db, self.db, reports, self.db).set_action_status(report_id, "routing_failures", "resolved")
        self.assertFalse(self.db.exists())
        state_path.write_text("not json", encoding="utf-8")
        invalid = dashboard.DashboardData(self.db, self.db, reports, state_path).weekly()
        self.assertIsNotNone(invalid["action_state"]["error"])
        with self.assertRaises(ValueError):
            data.set_action_status(report_id, "routing_failures", "resolved")
        self.assertEqual(report_path.read_bytes(), source_before)

    def test_dashboard_can_reopen_source_resolved_action_without_mutating_report(self) -> None:
        reports = Path(self.temp.name) / "resolved-reports"
        reports.mkdir()
        report_path = reports / "weekly.json"
        report_path.write_text(json.dumps({
            "report": "weekly-operations",
            "period": {"start": "2026-01-01", "end": "2026-01-08"},
            "action_items": [{"id": "closed_signal", "priority": "low", "status": "resolved"}],
        }), encoding="utf-8")
        source_before = report_path.read_bytes()
        state_path = Path(self.temp.name) / "resolved-state.json"
        data = dashboard.DashboardData(self.db, self.db, reports, state_path)
        report_id = data.weekly()["latest"]["report_id"]
        result = data.set_action_status(report_id, "closed_signal", "reopen", "Reopened after the source marked it resolved.", "reviewer")
        self.assertEqual(result["status"], "reopened")
        item = data.weekly()["latest"]["action_items"][0]
        self.assertEqual(item["source_status"], "resolved")
        self.assertEqual(item["status"], "open")
        self.assertEqual(item["operator_status"], "reopened")
        self.assertEqual(report_path.read_bytes(), source_before)
        persisted = json.loads(state_path.read_text(encoding="utf-8"))["items"][report_id]["closed_signal"]
        self.assertEqual(persisted["operator_note"], "Reopened after the source marked it resolved.")
        self.assertEqual(persisted["actor"], "reviewer")

    def test_dashboard_action_and_cache_http_endpoints_are_local_and_validated(self) -> None:
        reports = Path(self.temp.name) / "http-reports"
        reports.mkdir()
        report_path = reports / "weekly.json"
        report_path.write_text(json.dumps({
            "report": "weekly-operations",
            "period": {"start": "2026-01-01", "end": "2026-01-08"},
            "action_items": [{"id": "drift", "priority": "medium", "signal": "drift", "status": "open"}],
        }), encoding="utf-8")
        report_source_before = report_path.read_bytes()
        state_path = Path(self.temp.name) / "http-state.json"
        dashboard.DashboardHandler.data = dashboard.DashboardData(self.db, self.db, reports, state_path, report_scan_max_entries=7, report_scan_max_depth=2, report_scan_max_files=3, report_scan_max_file_bytes=1234)
        local_data = dashboard.DashboardHandler.data
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/health", timeout=3) as response:
                health = json.loads(response.read().decode("utf-8"))
            self.assertEqual(health["scan"]["limits"], {"max_entries": 7, "max_depth": 2, "max_files": 3, "max_file_bytes": 1234})
            weekly = dashboard.DashboardHandler.data.weekly()
            report_id = weekly["latest"]["report_id"]
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/action-items/status",
                data=json.dumps({"report_id": report_id, "action_id": "drift", "status": "resolved"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(result["status"], "resolved")
            self.assertEqual(dashboard.DashboardHandler.data.weekly()["latest"]["action_items"][0]["status"], "resolved")
            reopen_request = Request(
                f"http://127.0.0.1:{server.server_port}/api/action-items/status",
                data=json.dumps({"report_id": report_id, "action_id": "drift", "status": "reopen", "operator_note": "Reopened for a fresh review.", "actor": "operator-7"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(reopen_request, timeout=3) as response:
                reopened = json.loads(response.read().decode("utf-8"))
            self.assertEqual(reopened["status"], "reopened")
            reopened_item = dashboard.DashboardHandler.data.weekly()["latest"]["action_items"][0]
            self.assertEqual(reopened_item["status"], "open")
            self.assertEqual(reopened_item["operator_status"], "reopened")
            self.assertEqual(reopened_item["operator_note"], "Reopened for a fresh review.")
            self.assertEqual(reopened_item["actor"], "operator-7")
            with self.assertRaises(HTTPError) as invalid_reopen:
                urlopen(Request(
                    f"http://127.0.0.1:{server.server_port}/api/action-items/status",
                    data=json.dumps({"report_id": report_id, "action_id": "drift", "status": "reopen", "operator_note": " "}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ), timeout=3)
            self.assertEqual(invalid_reopen.exception.code, 400)
            invalid_reopen.exception.close()
            with self.assertRaises(HTTPError) as invalid:
                urlopen(Request(
                    f"http://127.0.0.1:{server.server_port}/api/action-items/status",
                    data=b"{}",
                    headers={"Content-Type": "text/plain"},
                    method="POST",
                ), timeout=3)
            self.assertEqual(invalid.exception.code, 415)
            invalid.exception.close()

            directory_stat = reports.stat()
            externally_added = reports / "externally-added.json"
            externally_added.write_text(json.dumps({"report": "weekly-operations", "period": {"start": "2026-01-08", "end": "2026-01-15"}, "action_items": []}), encoding="utf-8")
            os.utime(reports, ns=(directory_stat.st_atime_ns, directory_stat.st_mtime_ns))
            cached_files, cached_scan = local_data._scan_report_files()
            self.assertEqual(cached_scan["cache"]["status"], "hit")
            self.assertNotIn(externally_added, cached_files)
            state_before_invalidation = state_path.read_bytes()

            invalidate_url = f"http://127.0.0.1:{server.server_port}/api/cache/invalidate"
            with urlopen(Request(invalidate_url, data=b"", method="POST"), timeout=3) as response:
                invalidated = json.loads(response.read().decode("utf-8"))
            self.assertTrue(invalidated["invalidated"])
            self.assertEqual(invalidated["reason"], "operator_request")
            self.assertEqual(invalidated["next_scan"], {"counted_as": "miss", "expected_status": "rebuilt"})
            self.assertEqual(invalidated["cache"]["status"], "invalidated")
            self.assertEqual(invalidated["cache"]["freshness"], "unknown")
            self.assertEqual(invalidated["cache"]["invalidations"], 1)
            self.assertEqual(invalidated["cache"]["last_invalidation_reasons"], ["operator_request"])
            self.assertEqual(report_path.read_bytes(), report_source_before)
            self.assertEqual(state_path.read_bytes(), state_before_invalidation)
            rebuilt_weekly = local_data.weekly()
            rebuilt = rebuilt_weekly["scan"]["cache"]
            self.assertEqual(rebuilt["status"], "rebuilt")
            self.assertEqual(rebuilt["misses"], 2)
            self.assertEqual(rebuilt["invalidations"], 1)
            self.assertEqual(rebuilt["last_invalidation_reasons"], ["operator_request"])
            self.assertIn("externally-added.json", {report["name"] for report in rebuilt_weekly["reports"]})
            with urlopen(Request(invalidate_url, data=b"", method="POST"), timeout=3) as response:
                repeated = json.loads(response.read().decode("utf-8"))
            self.assertEqual(repeated["cache"]["invalidations"], 2)
            self.assertEqual(report_path.read_bytes(), report_source_before)
            self.assertEqual(state_path.read_bytes(), state_before_invalidation)

            remote_data = dashboard.DashboardData(self.db, self.db, reports, state_path, local_only=False)
            remote_data.weekly()
            dashboard.DashboardHandler.data = remote_data
            with self.assertRaises(HTTPError) as forbidden:
                urlopen(Request(invalidate_url, data=b"", method="POST"), timeout=3)
            self.assertEqual(forbidden.exception.code, 403)
            self.assertEqual(json.loads(forbidden.exception.read().decode("utf-8"))["error"], "cache invalidation is disabled for non-local bindings")
            forbidden.exception.close()
            self.assertEqual(remote_data.scan_configuration()["cache"]["invalidations"], 0)
        finally:
            dashboard.DashboardHandler.data = local_data
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_dashboard_exposes_action_filter_and_url_state_contract(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "assets" / "dashboard.html").read_text(encoding="utf-8")
        for key in ("priority", "status", "period", "skill"):
            self.assertIn(f'data-filter="{key}"', html)
        self.assertIn("URLSearchParams", html)
        self.assertIn("history.replaceState", html)
        self.assertIn("affected_skills", html)
        self.assertIn("No action items match these filters", html)
        self.assertIn("freshnessIndicator", html)
        self.assertIn("report_period_end", html)
        self.assertIn("report_modified_at", html)
        self.assertIn("journal_head_at", html)
        self.assertIn("curated only", html)
        self.assertIn("skipped_benchmark_trees", html)
        self.assertIn("cache?.status", html)
        self.assertIn("Report cache", html)
        self.assertIn("renderCachePanel", html)
        self.assertIn("cache.hit_rate", html)
        self.assertIn("cache.last_rebuilt_at", html)
        self.assertIn("cache.last_invalidation_reasons", html)
        self.assertIn("get('/api/health')", html)
        self.assertIn("Dashboard health", html)
        self.assertIn("renderDashboardHealth", html)
        self.assertIn("Effective scan limits", html)
        self.assertIn("Effective exclusions", html)
        self.assertIn("scan.configured_benchmark_trees", html)
        self.assertIn("scan.benchmark_trees", html)
        self.assertIn("limits.max_entries", html)
        self.assertIn("explicit manifest allowlist", html)
        self.assertIn("manifest.reports", html)
        self.assertIn("scan.report_manifest", html)
        self.assertIn('data-view="skippedTrees"', html)
        self.assertIn("renderSkippedBenchmarkTrees", html)
        self.assertIn("root metadata + direct files only", html)
        self.assertIn("recursive traversal is disabled", html)
        self.assertIn('data-status="reopen"', html)
        self.assertIn("operator_note", html)
        self.assertIn("Optional actor identity", html)
        self.assertIn("reopened", html)

    def test_synthetic_corpus_is_deterministic_and_indexable(self) -> None:
        first_root = Path(self.temp.name) / "first"
        second_root = Path(self.temp.name) / "second"
        first = benchmark_synthetic.generate_corpus(first_root, 12, seed=7, edge_stride=4)
        second = benchmark_synthetic.generate_corpus(second_root, 12, seed=7, edge_stride=4)
        different = benchmark_synthetic.generate_corpus(Path(self.temp.name) / "different", 12, seed=8, edge_stride=4)
        self.assertEqual(first["corpus_sha256"], second["corpus_sha256"])
        self.assertNotEqual(first["corpus_sha256"], different["corpus_sha256"])
        self.assertEqual(first["edges"], second["edges"])
        self.assertTrue(skill_graph.refresh_index(first_root, self.db, first["manifest_path"], strict=False)["ok"])
        self.assertTrue(skill_graph.check_index(self.db, first_root, first["manifest_path"])["ok"])
        self.assertEqual(skill_graph.stats(self.db)["counts"]["skills"], 12)

    def test_incremental_benchmark_compares_full_and_hash_refreshes(self) -> None:
        report = benchmark_synthetic.run_incremental_comparison(
            [12], Path(self.temp.name) / "incremental-bench", seed=3, edge_stride=4, change_ratio=0.25
        )
        self.assertTrue(report["passed"])
        result = report["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["mutation"]["changed"], 3)
        self.assertEqual(result["incremental"]["changed"], 3)
        self.assertGreater(result["full_rebuild_seconds"], 0)
        self.assertGreater(result["content_hash_refresh_seconds"], 0)
        self.assertTrue(result["checks"]["full_ok"])
        self.assertTrue(result["checks"]["incremental_ok"])

    def test_synthetic_benchmark_emits_bounded_json_report(self) -> None:
        report = benchmark_synthetic.run_benchmark(
            [3], Path(self.temp.name) / "bench", seed=2, edge_stride=3, query_count=2, route_count=1
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["results"][0]["count"], 3)
        self.assertEqual(len(report["results"][0]["queries"]["latencies_seconds"]), 2)
        self.assertEqual(len(report["results"][0]["routes"]["latencies_seconds"]), 1)
        self.assertIn("cpu_count", report["machine"])
        self.assertIsNone(report["results"][0]["run_directory"])

    def test_resource_policy_preflight_can_recommend_early_abort(self) -> None:
        policy = benchmark_synthetic.ResourcePolicy(disk_budget_bytes=1, memory_warning_bytes=1)
        report = benchmark_synthetic.run_benchmark(
            [100_000], Path(self.temp.name) / "resource-risk", policy=policy, abort_on_risk=True
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["results"][0]["status"], "early_aborted")
        recommendation = report["resource_assessments"][0]["early_abort_recommendation"]
        self.assertTrue(recommendation["should_abort"])
        self.assertIn("disk budget", " ".join(recommendation["reasons"]))

    def test_resource_report_marks_memory_warning_without_failing_run(self) -> None:
        report = benchmark_synthetic.run_benchmark(
            [3], Path(self.temp.name) / "resource-memory", policy=benchmark_synthetic.ResourcePolicy(memory_warning_bytes=1)
        )
        self.assertTrue(report["passed"])
        self.assertTrue(report["results"][0]["resources"]["memory_warning"])
        self.assertEqual(report["resource_policy"]["memory_warning_bytes"], 1)

    def test_resource_timeout_is_reported_as_explicit_failure(self) -> None:
        report = benchmark_synthetic.run_benchmark(
            [3], Path(self.temp.name) / "resource-timeout", policy=benchmark_synthetic.ResourcePolicy(timeout_seconds=0.000001)
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["results"][0]["status"], "wall-clock_timeout")
        self.assertFalse(report["results"][0]["ok"])

    def test_route_journaling_is_explicit_and_withholds_content_by_default(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.\\n#alpha")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        before = skill_graph.journal_verify(journal)
        default = skill_graph.route_and_journal(self.db, "index catalogs", None, None, 0.0, 5, 1)
        self.assertFalse(default["journal"]["stored"])
        self.assertEqual(skill_graph.journal_verify(journal), before)
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.route_and_journal(self.db, "index catalogs", None, None, 0.0, 5, 1, journal, False)
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.route_and_journal(self.db, "index catalogs", None, None, 0.0, 5, 1, journal, True, False, True)
        logged = skill_graph.route_and_journal(self.db, "index catalogs", None, None, 0.0, 5, 1, journal, True)
        self.assertTrue(logged["journal"]["stored"])
        self.assertTrue(logged["journal"]["task_content_withheld"])
        event = skill_graph.journal_show(journal, 1)["events"][0]
        self.assertEqual(event["payload"]["task_content"], "[WITHHELD]")
        self.assertNotIn("index catalogs", json.dumps(event))

    def test_route_journaling_requires_privacy_review_before_task_storage_and_redacts(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.\\n#alpha")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        text = "index catalogs with Bearer secret-token-123456 and person@example.com"
        logged = skill_graph.route_and_journal(
            self.db, text, None, None, 0.0, 5, 1, journal, True, True, True, {"custom_secret"}
        )
        self.assertTrue(logged["journal"]["task_content_stored"])
        event = skill_graph.journal_show(journal, 1)["events"][0]
        stored = event["payload"]["task_content"]
        self.assertNotIn("secret-token", stored)
        self.assertNotIn("person@example.com", stored)
        self.assertIn("[REDACTED]", stored)
        self.assertTrue(event["provenance"]["privacy"]["privacy_reviewed"])

    def test_journal_evaluation_reports_outcomes_by_skill_and_relation(self) -> None:
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        route = {
            "lead": {"skill_id": "alpha"},
            "support": [
                {"skill_id": "beta", "relation": "composes"},
                {"skill_id": "gamma", "relation": "requires"},
            ],
            "validator": {"skill_id": "validator", "relation": "validates"},
            "fallback": {"skill_id": "delta", "relation": "alternative-to"},
        }
        for status in ("success", "partial", "failure", "abstain"):
            decision = skill_graph.append_journal_event(journal, "decision", {"query": status, "route": route}, None, {})
            skill_graph.append_journal_event(journal, "outcome", {"status": status}, decision["event_id"], {})
        before = skill_graph.journal_verify(journal)
        report = skill_graph.journal_outcome_report(journal)
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertTrue(report["artifacts_unchanged"])
        self.assertEqual(report["total"]["outcomes"], 20)
        self.assertEqual(report["attributions"], 20)
        self.assertEqual(report["unlinked_outcomes"], 0)
        for skill_id in ("alpha", "beta", "gamma", "validator", "delta"):
            metrics = report["by_skill"][skill_id]
            self.assertEqual(metrics["counts"], {"abstain": 1, "failure": 1, "partial": 1, "success": 1})
            self.assertEqual(metrics["success_rate"], 0.25)
        self.assertEqual(report["by_relation"]["composes"]["counts"]["success"], 1)
        self.assertEqual(report["by_skill_relation"]["alpha::lead"]["abstention_rate"], 0.25)
        self.assertEqual(skill_graph.journal_verify(journal), before)

    def test_calibration_uses_verified_journal_and_heldout_abstention(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.\\n#alpha")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\\n\\nDeploy safely.\\n#beta")
        manifest = {
            "schema_version": 1,
            "skills": [
                {"id": "alpha", "confidence": 0.99},
                {"id": "beta", "confidence": 0.5},
            ],
        }
        manifest_path = self.root / "graph.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, manifest_path, strict=False)["ok"])
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        for _ in range(2):
            decision = skill_graph.append_journal_event(
                journal,
                "decision",
                {"query": "index catalogs", "route": {"lead": {"skill_id": "alpha", "confidence": 0.99}}},
                None,
                {"index": self.db.name},
            )
            skill_graph.append_journal_event(
                journal,
                "outcome",
                {"status": "success", "evidence": "catalog indexed"},
                decision["event_id"],
                {},
            )
        heldout = self.root / "heldout.json"
        heldout.write_text(json.dumps([
            {"id": "positive", "query": "index catalogs", "expected": ["alpha"]},
            {"id": "negative", "query": "deploy actions", "expected": []},
        ]), encoding="utf-8")
        before_index = skill_graph.stats(self.db)
        before_journal = skill_graph.journal_verify(journal)
        result = skill_graph.calibrate_routes(journal, self.db, heldout, 2, 5, 0.8)
        self.assertTrue(result["ok"])
        self.assertFalse(result["policy_mutated"])
        self.assertFalse(result["routing_policy_changed"])
        self.assertFalse(result["index_mutated"])
        self.assertFalse(result["journal_mutated"])
        self.assertTrue(result["artifacts_unchanged"])
        self.assertFalse(result["thresholds_fitted_on_holdout"])
        self.assertEqual(result["calibration"]["global_policy"]["threshold"], 0.95)
        self.assertEqual(result["heldout"]["metrics"]["negative_abstention_rate"], 1.0)
        self.assertEqual(result["heldout"]["metrics"]["positive_hit_rate"], 1.0)
        self.assertEqual(result["heldout"]["results"][1]["abstention_reason"], "confidence_below_policy")
        self.assertEqual(skill_graph.stats(self.db), before_index)
        self.assertEqual(skill_graph.journal_verify(journal), before_journal)

    def test_wilson_bound_drives_conservative_threshold_selection(self) -> None:
        observations = [
            {"confidence": 0.95, "outcome_score": 1.0},
            {"confidence": 0.96, "outcome_score": 1.0},
            {"confidence": 0.97, "outcome_score": 1.0},
            {"confidence": 0.98, "outcome_score": 1.0},
            {"confidence": 0.99, "outcome_score": 1.0},
            {"confidence": 0.99, "outcome_score": 0.0},
            {"confidence": 0.99, "outcome_score": 0.0},
            {"confidence": 0.99, "outcome_score": 0.0},
        ]
        policy = skill_graph._calibration_policy(observations, 3, 0.5)
        self.assertEqual(policy["selection_method"], "max_wilson_lower_bound")
        self.assertIsNotNone(policy["selected_wilson_lower"])
        self.assertGreaterEqual(policy["selected_wilson_lower"], 0)

    def test_temporal_drift_compares_recent_and_baseline_windows(self) -> None:
        observations = [
            {"confidence": 0.9, "outcome_score": 1.0, "observed_at": "2025-01-01T00:00:00+00:00"},
            {"confidence": 0.9, "outcome_score": 1.0, "observed_at": "2025-01-02T00:00:00+00:00"},
            {"confidence": 0.9, "outcome_score": 0.0, "observed_at": "2025-02-01T00:00:00+00:00"},
            {"confidence": 0.9, "outcome_score": 0.0, "observed_at": "2025-02-02T00:00:00+00:00"},
        ]
        report = skill_graph.temporal_calibration_drift(observations, window_days=30, minimum_samples=2)
        self.assertTrue(report["drift_detected"])
        self.assertEqual(report["status"], "drift_detected")
        self.assertEqual(report["success_rate_delta"], -1.0)

    def test_calibration_generates_per_domain_policies(self) -> None:
        journal = Path(self.temp.name) / "domain-journal.sqlite3"
        skill_graph.journal_init(journal)
        for domain, status in (("software", "success"), ("research", "failure")):
            decision = skill_graph.append_journal_event(
                journal,
                "decision",
                {"route": {"lead": {"skill_id": domain, "domain": domain, "confidence": 0.9}}},
                None,
                {},
            )
            skill_graph.append_journal_event(journal, "outcome", {"status": status}, decision["event_id"], {})
        report = skill_graph.load_route_observations(journal, 1, 0.5)
        self.assertIn("software", report["domain_policies"])
        self.assertIn("research", report["domain_policies"])
        self.assertEqual(report["domain_policies"]["software"]["threshold"], 0.9)
        self.assertIsNone(report["domain_policies"]["research"]["threshold"])

    def test_calibration_does_not_invent_policy_without_minimum_samples(self) -> None:
        journal = Path(self.temp.name) / "journal.sqlite3"
        skill_graph.journal_init(journal)
        decision = skill_graph.append_journal_event(journal, "decision", {"skill_id": "alpha", "confidence": 0.99}, None, {})
        skill_graph.append_journal_event(journal, "outcome", {"status": "success"}, decision["event_id"], {})
        heldout = Path(self.temp.name) / "heldout.json"
        heldout.write_text("[]", encoding="utf-8")
        self.add_skill("alpha", "Alpha handles indexing.", "# Instructions\\n\\nIndex.\\n#alpha")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        result = skill_graph.calibrate_routes(journal, self.db, heldout, 2, 5, 0.8)
        self.assertFalse(result["calibration"]["global_policy"]["eligible"])
        self.assertIsNone(result["calibration"]["global_policy"]["threshold"])
        self.assertEqual(result["heldout"]["cases"], 0)

    def test_domain_benchmark_scores_graded_relevance_and_negative_controls(self) -> None:
        self.add_skill("alpha", "Alpha handles React performance and waterfalls.", "# Instructions\\n\\nReview React performance.\\n#react")
        self.add_skill("beta", "Beta handles Vercel deployments.", "# Instructions\\n\\nDeploy to Vercel.\\n#delivery")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        cases = self.root / "domain-benchmark.json"
        cases.write_text(json.dumps({
            "schema_version": 1,
            "cases": [
                {"id": "react", "domain": "software", "split": "heldout", "query": "Review React waterfalls and performance.", "judgments": {"alpha": 3, "beta": 0}},
                {"id": "related", "domain": "software", "split": "heldout", "query": "Improve deployment performance for a React app.", "judgments": {"alpha": 2, "beta": 1}},
                {"id": "negative", "domain": "no-trigger", "split": "heldout", "query": "What is the capital of France?", "judgments": {"alpha": 0, "beta": 0}},
            ],
        }), encoding="utf-8")
        result = skill_graph.evaluate_domain_bench(self.db, cases, 5, 3)
        self.assertEqual(result["cases"], 3)
        self.assertEqual(result["k"], 3)
        self.assertEqual(result["metrics"]["positive_cases"], 2)
        self.assertEqual(result["metrics"]["negative_cases"], 1)
        self.assertIn("ndcg_at_k", result["metrics"])
        self.assertIn("software", result["by_domain"])
        self.assertTrue(all(case["split"] == "heldout" for case in result["results"]))

    def test_realistic_heldout_corpus_has_labels_groups_and_no_trigger_controls(self) -> None:
        corpus = SCRIPT.parents[1] / "assets" / "heldout-evaluation.example.json"
        document = json.loads(corpus.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)
        self.assertGreaterEqual(len(document["cases"]), 12)
        self.assertTrue(all(case["split"] == "heldout" for case in document["cases"]))
        self.assertTrue(all(all(isinstance(grade, int) and 0 <= grade <= 3 for grade in case["judgments"].values()) for case in document["cases"]))
        groups = {case["group_id"] for case in document["cases"]}
        self.assertGreaterEqual(len(groups), 4)
        self.assertGreaterEqual(sum(case["domain"] == "no-trigger" for case in document["cases"]), 8)

    def test_domain_benchmark_scores_repeated_groups_and_false_activation(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\\n\\nDeploy safely.")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        cases = self.root / "grouped-heldout.json"
        cases.write_text(json.dumps({
            "schema_version": 1,
            "cases": [
                {"id": "positive-1", "group_id": "positive", "domain": "software", "split": "heldout", "query": "index catalogs", "judgments": {"alpha": 3, "beta": 0}},
                {"id": "positive-2", "group_id": "positive", "domain": "software", "split": "heldout", "query": "catalog indexing", "judgments": {"alpha": 3, "beta": 0}},
                {"id": "negative-1", "group_id": "negative", "domain": "no-trigger", "split": "heldout", "query": "alpha indexing", "judgments": {"alpha": 0, "beta": 0}},
                {"id": "negative-2", "group_id": "negative", "domain": "no-trigger", "split": "heldout", "query": "alpha catalogs", "judgments": {"alpha": 0, "beta": 0}},
            ],
        }), encoding="utf-8")
        result = skill_graph.evaluate_domain_bench(self.db, cases, 5, 3)
        self.assertEqual(result["repeated_query_groups"]["groups"], 2)
        self.assertEqual(result["repeated_query_groups"]["repeated_groups"], 2)
        self.assertEqual(result["repeated_query_groups"]["consistency_rate"], 1.0)
        self.assertEqual(result["false_activation_analysis"]["negative_cases"], 2)
        self.assertEqual(result["false_activation_analysis"]["false_activations"], 2)
        self.assertEqual(result["false_activation_analysis"]["false_activation_rate"], 1.0)
        self.assertEqual(result["results"][0]["relevant"], ["alpha"])

    def test_domain_benchmark_rejects_non_heldout_or_invalid_judgments(self) -> None:
        self.add_skill("alpha", "Alpha handles React performance.", "# Instructions\\n\\nReview React.\\n#react")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        cases = self.root / "bad-domain.json"
        cases.write_text(json.dumps({"schema_version": 1, "cases": [{"id": "x", "domain": "software", "split": "train", "query": "React", "judgments": {"alpha": 3}}]}), encoding="utf-8")
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.evaluate_domain_bench(self.db, cases, 5, 3)
        cases.write_text(json.dumps({"schema_version": 1, "cases": [{"id": "x", "domain": "software", "split": "heldout", "query": "React", "judgments": {"alpha": 9}}]}), encoding="utf-8")
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.evaluate_domain_bench(self.db, cases, 5, 3)

    def _calibration_report_for_policy(self) -> dict:
        return {
            "ok": True,
            "minimum_samples": 2,
            "target_success_rate": 0.8,
            "index_fingerprint_after": "index-v1",
            "journal_fingerprint_after": "journal-v1",
            "calibration": {
                "global_policy": {"eligible": True, "threshold": 0.8, "samples": 4},
                "policies": {"alpha": {"eligible": True, "threshold": 0.7, "samples": 3}},
            },
            "heldout": {"metrics": {"coverage": 0.5}},
        }

    def test_calibration_policy_artifact_promotes_and_rolls_back_versions(self) -> None:
        artifact = Path(self.temp.name) / "calibration-policy.json"
        report = self._calibration_report_for_policy()
        created = skill_graph.create_calibration_policy_artifact(artifact, report, "test")
        self.assertTrue(created["ok"])
        self.assertIsNone(created["active_version"])
        self.assertEqual(created["versions"][0]["status"], "candidate")
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.promote_calibration_policy(artifact, 1, "operator")
        approved = skill_graph.approve_calibration_policy(artifact, 1, "reviewer", "held-out review passed")
        self.assertEqual(approved["versions"][0]["status"], "approved")
        promoted = skill_graph.promote_calibration_policy(artifact, 1, "operator")
        self.assertEqual(promoted["active_version"], 1)
        report_v2 = json.loads(json.dumps(report))
        report_v2["calibration"]["global_policy"]["threshold"] = 0.9
        report_v2["journal_fingerprint_after"] = "journal-v2"
        skill_graph.create_calibration_policy_artifact(artifact, report_v2, "test")
        skill_graph.approve_calibration_policy(artifact, 2, "reviewer")
        skill_graph.promote_calibration_policy(artifact, 2, "operator")
        rolled_back = skill_graph.rollback_calibration_policy(artifact, "operator", "regression")
        self.assertEqual(rolled_back["active_version"], 1)
        statuses = {item["version"]: item["status"] for item in rolled_back["versions"]}
        self.assertEqual(statuses, {1: "active", 2: "rolled_back"})
        self.assertTrue(rolled_back["integrity"]["payload_sha256"])

    def test_calibration_policy_artifact_rejects_tampering_and_requires_approval(self) -> None:
        artifact = Path(self.temp.name) / "calibration-policy.json"
        report = self._calibration_report_for_policy()
        skill_graph.create_calibration_policy_artifact(artifact, report)
        raw = json.loads(artifact.read_text(encoding="utf-8"))
        raw["versions"][0]["policy"]["global"]["threshold"] = 0.1
        artifact.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(skill_graph.SkillError):
            skill_graph.calibration_policy_artifact_verify(artifact)

    def test_calibration_policy_drift_reports_policy_and_source_changes(self) -> None:
        artifact = Path(self.temp.name) / "calibration-policy.json"
        report = self._calibration_report_for_policy()
        skill_graph.create_calibration_policy_artifact(artifact, report)
        skill_graph.approve_calibration_policy(artifact, 1, "reviewer")
        skill_graph.promote_calibration_policy(artifact, 1, "operator")
        self.assertTrue(skill_graph.monitor_calibration_policy_drift(artifact, report)["in_sync"])
        changed = json.loads(json.dumps(report))
        changed["calibration"]["policies"]["alpha"]["threshold"] = 0.9
        changed["index_fingerprint_after"] = "index-v2"
        drift = skill_graph.monitor_calibration_policy_drift(artifact, changed)
        self.assertTrue(drift["drift_detected"])
        self.assertIn("policy.by_skill.alpha.threshold", drift["policy_changes"])
        self.assertEqual(drift["source_changes"], ["index_fingerprint"])

    def test_route_can_apply_only_the_promoted_policy_version(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        artifact = Path(self.temp.name) / "route-policy.json"
        report = self._calibration_report_for_policy()
        skill_graph.create_calibration_policy_artifact(artifact, report)
        skill_graph.approve_calibration_policy(artifact, 1, "reviewer")
        skill_graph.promote_calibration_policy(artifact, 1, "operator")
        result = skill_graph.route(self.db, "index catalogs", None, None, 0.0, 8, 1, artifact)
        self.assertEqual(result["calibration_policy"]["version"], 1)
        self.assertTrue(result["calibration_policy"]["abstention_enabled"])

    def test_negative_evidence_gate_abstains_on_generic_queries(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs. Next steps are documented.\\n#alpha")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\\n\\nDeploy safely. Next steps are documented.\\n#beta")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        result = skill_graph.route(self.db, "What is the weather in Paris next Tuesday?", None, None, 0.0, 5, 1)
        self.assertIsNone(result["lead"])
        self.assertTrue(result["abstained"])
        self.assertEqual(result["abstention_reason"], "negative_evidence_gate")
        self.assertEqual(result["negative_evidence_gate"]["candidates_rejected"], 2)
        positive = skill_graph.route(self.db, "index catalogs", None, None, 0.0, 5, 1)
        self.assertEqual(positive["lead"]["skill_id"], "alpha")
        self.assertFalse(positive.get("abstained", False))

    def test_adversarial_heldout_controls_do_not_activate_on_keywords(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.\\n#alpha")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\\n\\nDeploy safely.\\n#beta")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        corpus = SCRIPT.parents[1] / "assets" / "heldout-evaluation.example.json"
        document = json.loads(corpus.read_text(encoding="utf-8"))
        cases = [case for case in document["cases"] if case["id"].startswith("no-trigger-")]
        self.assertGreaterEqual(len(cases), 8)
        for case in cases:
            result = skill_graph.route(self.db, case["query"], None, None, 0.0, 5, 1)
            self.assertIsNone(result["lead"], case["id"])

    def test_weekly_report_renders_outcomes_abstentions_failures_and_drift(self) -> None:
        journal = Path(self.temp.name) / "weekly.sqlite3"
        skill_graph.journal_init(journal)
        cases = [
            ("success", {"lead": {"skill_id": "alpha", "confidence": 0.9}}, {"status": "success", "evidence": "completed"}),
            ("partial", {"lead": {"skill_id": "alpha", "confidence": 0.7}}, {"status": "partial", "evidence": "needs follow-up"}),
            ("abstain", {"abstained": True, "abstention_reason": "negative_evidence_gate"}, {"status": "abstain", "evidence": "no trigger"}),
            ("failure", {"lead": {"skill_id": "beta", "confidence": 0.8}}, {"status": "failure", "evidence": "routing failed"}),
        ]
        for name, decision_payload, outcome_payload in cases:
            decision = skill_graph.append_journal_event(journal, "decision", {"query": name, "route": decision_payload}, None, {})
            skill_graph.append_journal_event(journal, "outcome", outcome_payload, decision["event_id"], {})
        report = skill_graph.weekly_report_data(journal, window_days=30, minimum_samples=2)
        text = skill_graph.render_weekly_report(report)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["events"]["decisions"], 4)
        self.assertEqual(report["outcomes"]["counts"], {"abstain": 1, "failure": 1, "partial": 1, "success": 1})
        self.assertEqual(report["abstentions"]["decisions"], 1)
        self.assertEqual(report["routing_failures"]["failed_outcomes"], 1)
        self.assertEqual(report["routing_failures"]["by_skill"], {"beta": 1})
        self.assertEqual(report["calibration_drift"]["status"], "insufficient_data")
        action_ids = {item["id"] for item in report["action_items"]}
        self.assertIn("routing_failures", action_ids)
        self.assertIn("unlinked_outcomes", action_ids)
        self.assertTrue(all(item["requires_human_review"] for item in report["action_items"]))
        self.assertIn("WEEKLY SKILL ROUTING REPORT", text)
        self.assertIn("negative_evidence_gate", text)
        self.assertIn("Routing failures", text)
        self.assertIn("ACTION ITEMS", text)
        self.assertIn("routing_failures", text)

    def test_weekly_report_json_format_is_an_automation_contract(self) -> None:
        journal = Path(self.temp.name) / "weekly-json.sqlite3"
        skill_graph.journal_init(journal)
        decision = skill_graph.append_journal_event(journal, "decision", {"lead": {"skill_id": "alpha", "confidence": 0.9}}, None, {})
        skill_graph.append_journal_event(journal, "outcome", {"status": "success"}, decision["event_id"], {})
        output = Path(self.temp.name) / "weekly.json"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = skill_graph.main(["weekly-report", str(journal), "--format", "json", "--output", str(output)])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("weekly json report written", stderr.getvalue())
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["outcomes"]["counts"]["success"], 1)
        self.assertIn("action_items", report)

    def _ci_fixture(self) -> tuple[Path, Path, Path, Path]:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\\n\\nIndex catalogs.")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\\n\\nDeploy safely.")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        cases = self.root / "ci-cases.json"
        cases.write_text(json.dumps([
            {"id": "positive", "query": "index catalogs", "expected": ["alpha"], "forbidden": ["beta"]},
            {"id": "negative", "query": "write a poem", "expected": [], "forbidden": ["alpha", "beta"]},
        ]), encoding="utf-8")
        journal = Path(self.temp.name) / "ci-journal.sqlite3"
        skill_graph.journal_init(journal)
        decision = skill_graph.append_journal_event(journal, "decision", {"route": {"lead": {"skill_id": "alpha", "confidence": 0.9}}}, None, {})
        skill_graph.append_journal_event(journal, "outcome", {"status": "success"}, decision["event_id"], {})
        baseline = self.root / "ci-baseline.json"
        baseline.write_text(json.dumps({
            "schema_version": 1,
            "routing": skill_graph.evaluate_index(self.db, cases, 5),
            "calibration_drift": {"status": "in_sync", "drift_detected": False},
        }), encoding="utf-8")
        return self.db, journal, cases, baseline

    def test_ci_quality_gate_passes_and_preserves_input_artifacts(self) -> None:
        db, journal, cases, baseline = self._ci_fixture()
        result = skill_graph.ci_quality_gate(db, journal, cases, baseline, limit=5, minimum_samples=2)
        self.assertTrue(result["passed"])
        self.assertTrue(result["read_only"])
        self.assertTrue(result["artifacts_unchanged"])
        self.assertTrue(result["routing"]["passed"])
        self.assertTrue(result["journal"]["passed"])
        self.assertFalse(result["calibration_drift"]["newly_detected"])

    def test_ci_quality_gate_fails_routing_regressions(self) -> None:
        db, journal, cases, baseline = self._ci_fixture()
        document = json.loads(baseline.read_text(encoding="utf-8"))
        document["routing"]["metrics"]["hit_rate"] = 1.0
        document["routing"]["metrics"]["forbidden_rate"] = 0.0
        document["routing"]["metrics"]["no_trigger_false_activation_rate"] = 0.0
        baseline.write_text(json.dumps(document), encoding="utf-8")
        cases.write_text(json.dumps([
            {"id": "regressed", "query": "index catalogs", "expected": ["beta"], "forbidden": ["alpha"]},
            {"id": "negative", "query": "write a poem", "expected": [], "forbidden": ["alpha", "beta"]},
        ]), encoding="utf-8")
        result = skill_graph.ci_quality_gate(db, journal, cases, baseline, limit=5, minimum_samples=2)
        self.assertFalse(result["passed"])
        self.assertFalse(result["routing"]["passed"])
        self.assertTrue(result["routing"]["regressions"])

    def test_ci_quality_gate_cli_returns_nonzero_on_regression(self) -> None:
        db, journal, cases, baseline = self._ci_fixture()
        document = json.loads(baseline.read_text(encoding="utf-8"))
        document["routing"]["metrics"]["hit_rate"] = 1.0
        baseline.write_text(json.dumps(document), encoding="utf-8")
        cases.write_text(json.dumps([
            {"id": "regressed", "query": "index catalogs", "expected": ["beta"], "forbidden": ["alpha"]},
            {"id": "negative", "query": "write a poem", "expected": [], "forbidden": ["alpha", "beta"]},
        ]), encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = skill_graph.main(["ci-check", str(db), str(journal), str(cases), str(baseline), "--limit", "5", "--minimum-samples", "2"])
        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "")
        self.assertFalse(json.loads(stdout.getvalue())["passed"])

    def test_ci_quality_gate_fails_invalid_journal_chain(self) -> None:
        db, journal, cases, baseline = self._ci_fixture()
        conn = sqlite3.connect(journal)
        conn.execute("DROP TRIGGER journal_events_no_update")
        conn.execute("UPDATE journal_events SET payload_json='{}' WHERE sequence=1")
        conn.commit()
        conn.close()
        result = skill_graph.ci_quality_gate(db, journal, cases, baseline, limit=5, minimum_samples=2)
        self.assertFalse(result["passed"])
        self.assertFalse(result["journal"]["passed"])
        self.assertIn("journal chain verification failed", result["failures"])
        self.assertFalse(result["calibration_drift"]["evaluated"])
        self.assertTrue(result["artifacts_unchanged"])

    def test_ci_quality_gate_fails_new_calibration_drift(self) -> None:
        db, journal, cases, baseline = self._ci_fixture()
        drift = {"status": "drift_detected", "drift_detected": True, "success_rate_delta": -0.4}
        with mock.patch.object(skill_graph, "weekly_report_data", return_value={"calibration_drift": drift}):
            result = skill_graph.ci_quality_gate(db, journal, cases, baseline, limit=5, minimum_samples=2)
        self.assertFalse(result["passed"])
        self.assertTrue(result["calibration_drift"]["newly_detected"])
        self.assertIn("calibration drift detected", result["failures"])

    def test_evaluate_reports_positive_and_negative_metrics(self) -> None:
        self.add_skill("alpha", "Alpha handles indexing and catalogs.", "# Instructions\n\nIndex catalogs.\n#alpha")
        self.add_skill("beta", "Beta handles deployment actions.", "# Instructions\n\nDeploy safely.\n#beta")
        self.assertTrue(skill_graph.refresh_index(self.root, self.db, None, strict=False)["ok"])
        cases = self.root / "cases.json"
        cases.write_text(json.dumps([
            {"id": "positive", "query": "index catalogs", "expected": ["alpha"], "forbidden": ["beta"]},
            {"id": "negative", "query": "write a poem", "expected": [], "forbidden": ["beta"]},
            {"id": "adversarial", "query": "React Vercel queue deployment performance in one sentence", "expected": [], "forbidden": ["alpha", "beta"]},
        ]), encoding="utf-8")
        result = skill_graph.evaluate_index(self.db, cases, 5)
        self.assertEqual(result["cases"], 3)
        self.assertEqual(result["metrics"]["hit_rate"], 1.0)
        self.assertEqual(result["metrics"]["forbidden_rate"], 0.0)
        self.assertEqual(result["metrics"]["no_trigger_false_activation_rate"], 0.0)
        self.assertTrue(result["passed"])
        self.assertEqual(result["results"][1]["selected"], [])
        self.assertEqual(result["results"][2]["selected"], [])


if __name__ == "__main__":
    unittest.main()
