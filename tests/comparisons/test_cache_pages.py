"""Offline regression tests for dump identity, JSON comparisons and source selection."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from history import generator as cp
from history.normalization import ReferenceIndex, normalized_changes


def parse(text, source="config/dump.obj"):
    return cp.parse_dump(text.splitlines(), source)


def commit(sha="a" * 40, title="2026-11-23-rev951", parent="b" * 40):
    return {"sha": sha, "commit": {"message": title + "\n\nref: https://archive.openrs2.org/caches/runescape/2773"},
            "parents": [{"sha": parent}] if parent else []}


BEFORE = cp.Revision.from_commit(commit("b" * 40, "2026-11-17-rev951"))
AFTER = cp.Revision.from_commit(commit())


class ParserTests(unittest.TestCase):
    def test_real_format_and_repeated_fields(self):
        records = parse("// 0\n[mcannonremains]\nname=Dwarf remains\nparam=destroyondrop,1\n"
                        "param=protect_on_death,1\nmodel=one\nmodel=two\n// 18\n[empty]\n")
        self.assertEqual(set(records), {"0", "18"})
        self.assertEqual(records["0"].fields()["param[protect_on_death]"], ("1",))
        self.assertEqual(records["0"].fields()["model"], ("one", "two"))
        self.assertEqual(records["18"].fields(), {})

    def test_interface_component_ids(self):
        records = parse("// 0:0\r\r\n[100_q5]\r\r\ntype=model\r\r\n"
                        "// 0:20\r\r\n[content_layer]\r\r\ntype=layer\r\r\n", "interface/guide.if3")
        self.assertEqual(set(records), {"0:0", "0:20"})

    def test_unnamed_interface_components_keep_their_numeric_identity(self):
        records = parse("// 490:3\n[]\ntype=text\ntext=Current honour points\n"
                        "// 490:4\n[]\ntype=text\ntext=Next level\n", "interface/barbassault_playerstat.if3")
        self.assertEqual(set(records), {"490:3", "490:4"})
        self.assertEqual(records["490:3"].symbol, "")
        self.assertEqual(records["490:3"].fields()["text"], ("Current honour points",))
        renamed = parse("// 490:3\n[honour_points]\ntype=text\ntext=Current honour points\n")
        self.assertEqual(normalized_changes(records["490:3"], renamed["490:3"], "interface",
                                            ReferenceIndex(), ReferenceIndex()), [])

    def test_values_keep_commas_equals_quotes(self):
        record = parse('// 5\n[test]\nparam=description,"a,b=c"\nval=4,one,two\n')["5"]
        self.assertEqual(record.fields()["param[description]"], ('"a,b=c"',))
        self.assertEqual(record.fields()["val[4]"], ("one,two",))

    def test_invalid_input_never_silently_drops_records(self):
        for text in ["// 1\n// 2\n[two]", "// 1", "[no_id]", "[]", "// 1\n[one]\ninvalid",
                     "// 1\n[one]\n// 1\n[again]", "// 1\n[one]\n[no_id]", "// 1\n[one]\n=value"]:
            with self.subTest(text=text), self.assertRaises(cp.CachePagesError):
                parse(text)

    def test_numeric_sort(self):
        self.assertEqual(sorted(["12:1", "2:10", "2:2"], key=cp.id_key), ["2:2", "2:10", "12:1"])

    def test_duplicate_id_across_interface_files(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "one.if3"
            p.write_text("// 0:0\n[foo]\n", encoding="utf-8")
            with self.assertRaisesRegex(cp.CachePagesError, "Duplicate ID"):
                cp.read_records([("one.if3", p), ("two.if3", p)])


class DiffTests(unittest.TestCase):
    def compare(self, old, new, kind="obj"):
        return cp.compare_records(kind, parse(old), parse(new), ReferenceIndex(), ReferenceIndex())

    def test_sparse_ids_added_removed_cleared_and_renamed(self):
        data, counts = self.compare(
            "// 1\n[old_name]\nname=Old\n// 4\n[removed]\n// 7\n[cleared]\nname=Gone\n",
            "// 1\n[new_name]\nname=New\n// 7\n[cleared]\n// 100\n[added]\n")
        self.assertEqual(counts, {"new": 1, "removed": 1, "changed": 2, "fields_changed": 2})
        self.assertEqual([r["id"] for r in data["added"]], [100])
        self.assertEqual([r["id"] for r in data["removed"]], [4])
        self.assertEqual([r["id"] for r in data["modified"]], [1, 7])
        self.assertEqual(data["modified"][0]["after"]["config_name"], "new_name")
        self.assertIsNone(data["modified"][1]["fields"][0]["after"])

    def test_only_changed_parameter_and_enum_entry(self):
        data, _ = self.compare("// 1\n[x]\nparam=a,1\nparam=b,2\nval=0,same\nval=1,old\n",
                               "// 1\n[x]\nparam=a,1\nparam=b,3\nval=0,same\nval=1,new\n", "enum")
        fields = data["modified"][0]["fields"]
        self.assertEqual([(f["field"], f["before"], f["after"]) for f in fields],
                         [("param[b]", ["2"], ["3"]), ("val[1]", ["old"], ["new"])])

    def test_field_order_ignored_but_repeated_order_preserved(self):
        a = "// 1\n[x]\na=1\nb=2\na=3\n"
        b = "// 1\n[x]\nb=2\na=1\na=3\n"
        c = "// 1\n[x]\na=3\na=1\nb=2\n"
        self.assertEqual(self.compare(a, b)[1]["fields_changed"], 0)
        self.assertEqual(self.compare(a, c)[0]["modified"][0]["fields"][0]["after"], ["3", "1"])

    def test_empty_diff_and_summary(self):
        data, counts = self.compare("// 5\n[x]\nname=Same\n", "// 5\n[x]\nname=Same\n")
        self.assertEqual(data, {"added": [], "removed": [], "modified": []})
        self.assertEqual(counts, {"new": 0, "removed": 0, "changed": 0, "fields_changed": 0})


class SourceTests(unittest.TestCase):
    def test_history_reused_for_both_dates_and_subsequent_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            with patch.object(source, "api", return_value=[commit(), commit("b" * 40, "2026-11-17-rev951")]) as api:
                self.assertEqual(source.resolve("2026-11-23"), AFTER)
                self.assertEqual(source.resolve("2026-11-17"), BEFORE)
                self.assertEqual(api.call_count, 1)
            second = cp.GitHubSource(Path(directory))
            with patch.object(second, "request", side_effect=AssertionError("history should be cached")):
                self.assertEqual(second.resolve("2026-11-23"), AFTER)
                self.assertEqual(second.resolve("2026-11-17"), BEFORE)

    def test_stale_history_fallback_and_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "history.json").write_text(json.dumps({
                "version": 2, "complete": True, "saved_at": 0,
                "revisions": [cp.asdict(AFTER), cp.asdict(BEFORE)],
            }), encoding="utf-8")
            source = cp.GitHubSource(cache)
            with patch.object(source, "api", side_effect=cp.CachePagesError("HTTP 403")), patch("sys.stderr", new=io.StringIO()) as stderr:
                self.assertEqual(list(source.history()), [AFTER, BEFORE])
                self.assertIn("using cached history", stderr.getvalue())
            refresh = cp.GitHubSource(cache, refresh_history=True)
            with patch.object(refresh, "api", return_value=[commit()]) as api:
                self.assertEqual(list(refresh.history()), [AFTER])
                api.assert_called_once()

    def test_failed_pagination_does_not_save_partial_history(self):
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            with patch.object(source, "api", side_effect=[[commit()] * 100, cp.CachePagesError("HTTP 403")]):
                with self.assertRaises(cp.CachePagesError):
                    list(source.history())
            self.assertFalse((Path(directory) / "history.json").exists())

    def test_commit_metadata_uses_cache_title_date(self):
        self.assertEqual(AFTER.date, "2026-11-23")
        self.assertEqual(AFTER.archive, "https://archive.openrs2.org/caches/runescape/2773")
        self.assertIsNone(cp.Revision.from_commit(commit(title="Rename symbols")))

    def test_same_day_snapshots_keep_dates_and_distinct_report_filenames(self):
        first = cp.Revision.from_commit(commit(title="2026-03-02a-rev946"))
        second = cp.Revision.from_commit(commit(title="2026-03-02b-rev946"))
        self.assertEqual((first.date, first.revision), ("2026-03-02", "946"))
        self.assertEqual(first.report_filename, "2026-03-02-rev946-a.json")
        self.assertEqual(second.report_filename, "2026-03-02-rev946-b.json")
        self.assertEqual(AFTER.report_filename, "2026-11-23-rev951.json")
        self.assertIsNone(cp.Revision.from_commit(commit(title="2026-10-19-rev951-assetnames")))

    def test_same_day_snapshots_require_unambiguous_selectors(self):
        first = cp.Revision.from_commit(commit(title="2026-03-02a-rev946"))
        second = cp.Revision.from_commit(commit(title="2026-03-02b-rev946"))
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            source._history = [second, first]
            self.assertEqual(source.resolve(first.title), first)
            with self.assertRaisesRegex(cp.CachePagesError, "Ambiguous"):
                source.resolve("2026-03-02")

    def test_old_history_cache_refreshes_to_include_same_day_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "history.json").write_text(json.dumps({
                "version": 1, "complete": True, "saved_at": cp.time.time(),
                "revisions": [cp.asdict(AFTER)],
            }), encoding="utf-8")
            source = cp.GitHubSource(cache)
            with patch.object(source, "api", return_value=[commit(title="2026-03-02b-rev946")]) as api:
                self.assertEqual(list(source.history())[0].title, "2026-03-02b-rev946")
                api.assert_called_once()

    def test_selection_and_ambiguous_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            with patch.object(source, "history", return_value=iter([AFTER, BEFORE])):
                with self.assertRaisesRegex(cp.CachePagesError, "Ambiguous"):
                    source.resolve("951")
            with patch.object(source, "history", return_value=iter([AFTER, BEFORE])):
                self.assertEqual(source.resolve("2026-11-17"), BEFORE)
            with patch.object(source, "history", return_value=iter([AFTER, BEFORE])):
                self.assertEqual(source.resolve("latest"), AFTER)

    def test_predecessor_skips_metadata_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            with patch.object(source, "api", side_effect=[commit("b" * 40, "Rename symbols", "c" * 40),
                                                         commit("c" * 40, "2026-11-16-rev951")]):
                self.assertEqual(source.predecessor(AFTER).date, "2026-11-16")

    def test_initial_snapshot_has_no_predecessor(self):
        initial = cp.Revision.from_commit(commit(parent=None))
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            with patch.object(source, "api", side_effect=AssertionError("No parent to fetch")):
                self.assertIsNone(source.predecessor(initial))

    def test_download_integrity_reuse_and_corruption(self):
        data = b"// 0\n[test]\nname=Test\n"
        entry = cp.FileEntry("config/dump.obj", cp.blob_hash(data), len(data))
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            with patch.object(source, "request", return_value=data) as request:
                path = source.download(AFTER, entry)
                source.download(AFTER, entry)
                self.assertEqual(request.call_count, 1)
                path.write_bytes(b"bad")
                source.download(AFTER, entry)
                self.assertEqual(request.call_count, 2)
            path.unlink()
            with patch.object(source, "request", return_value=b"bad"), self.assertRaisesRegex(cp.CachePagesError, "Integrity"):
                source.download(AFTER, entry)

    def test_history_pagination_keeps_later_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            source = cp.GitHubSource(Path(directory))
            first = [commit(title="Metadata")] * 100
            with patch.object(source, "api", side_effect=[first, [commit()]]) as api:
                self.assertEqual(list(source.history()), [AFTER])
                self.assertIn("page=2", api.call_args.args[0])


class IntegrationTests(unittest.TestCase):
    def test_initial_snapshot_exports_marked_inventory_without_a_false_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump = root / "dump.obj"
            data = b"// 0\n[first]\nname=First item\n// 7\n[other]\nname=Other item\n"
            dump.write_bytes(data)
            initial = cp.Revision("a" * 40, "2003-12-05-rev186", "2003-12-05", "186")
            entry = cp.FileEntry("config/dump.obj", cp.blob_hash(data), len(data))
            output = root / "initial.json"
            with patch.object(cp.GitHubSource, "resolve", return_value=initial), \
                    patch.object(cp.GitHubSource, "catalog", return_value={entry.path: entry}) as catalog, \
                    patch.object(cp.GitHubSource, "download", return_value=dump), \
                    patch.object(cp.GitHubSource, "request", side_effect=AssertionError("Offline test")), \
                    patch.object(cp, "prepare_reference_index", return_value=(ReferenceIndex(), [])) as prepare, \
                    patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(["generate", "--target", initial.sha, "--output", str(output)]), 0)
            catalog.assert_called_once_with(initial)
            self.assertEqual(prepare.call_count, 1)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["comparison_kind"], "initial_snapshot")
            self.assertEqual(report["before"], cp.EMPTY_BASELINE)
            self.assertEqual(report["after"], cp.asdict(initial))
            self.assertEqual(report["summary"]["obj"], {"new": 2, "removed": 0, "changed": 0, "fields_changed": 0})
            self.assertEqual([r["id"] for r in report["changes"]["obj"]["added"]], [0, 7])
            self.assertEqual(report["changes"]["obj"]["modified"], [])
            self.assertEqual(report["unchanged_files"], [])
            self.assertTrue(all(f["side"] == "after" for f in report["compared_files"]))

    def arguments(self, root, output=None):
        return ["generate", "--old-dir", str(root / "old"), "--new-dir", str(root / "new"),
                "--date", "2026-11-23", "--revision", "951",
                "--output", str(output or root / "report.json")]

    def test_large_json_preserves_full_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side in ("old", "new"):
                (root / side).mkdir()
            payload = "É & {{literal}} <br> " + "x" * 1_600_000 + "END_OF_FULL_RECORD"
            for kind in ("obj", "npc"):
                (root / "old" / f"dump.{kind}").write_text(
                    "// 0\n[changed]\nname=Before\nvalue=old\n// 1\n[removed]\nname=Removed\n", encoding="utf-8")
                (root / "new" / f"dump.{kind}").write_text(
                    "// 0\n[changed]\nname=After\nvalue=new\n// 2\n[added]\nname=Added\ntext="
                    + (payload if kind == "obj" else "small") + "\n", encoding="utf-8")
            with patch.object(cp.GitHubSource, "request", side_effect=AssertionError("offline")), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(self.arguments(root)), 0)
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["changes"]["obj"]["added"][0]["fields"]["text"], [payload])
            for kind in ("obj", "npc"):
                self.assertEqual(report["summary"][kind], {"new": 1, "removed": 1, "changed": 1, "fields_changed": 2})
            self.assertEqual([p.name for p in root.iterdir() if p.is_file()], ["report.json"])
            self.assertNotIn("pages", report)
            self.assertNotIn("output_sha256", report)

    def test_offline_cli_deterministic_report_and_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side in ("old", "new"):
                (root / side).mkdir()
            (root / "old/dump.obj").write_text("// 1\n[test]\nname=Old\n", encoding="utf-8")
            (root / "new/dump.obj").write_text("// 1\n[test]\nname=New\n// 2\n[added]\n", encoding="utf-8")
            for side in ("old", "new"):
                (root / side / "dump.npc").write_text("// 1\n[npc]\nname=Same\n", encoding="utf-8")
                for kind in cp.EXCLUDED_TYPES:
                    (root / side / f"dump.{kind}").write_text(f"// 0\n[excluded]\nvalue={side}\n", encoding="utf-8")
            args = self.arguments(root)
            output = root / "report.json"
            with patch.object(cp.GitHubSource, "request", side_effect=AssertionError("offline")), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(args), 0)
                first = output.read_bytes()
                self.assertEqual(cp.main(args), 0)
            self.assertEqual(first, output.read_bytes())
            report = json.loads(first)
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["tool"], "CachePages/2.0")
            self.assertEqual(set(report["changes"]), {"obj"})
            self.assertEqual(report["changes"]["obj"]["added"][0]["id"], 2)
            self.assertEqual(report["changes"]["obj"]["modified"][0]["fields"][0]["before"], ["Old"])
            self.assertEqual(report["summary"]["obj"]["new"], 1)
            self.assertEqual(report["summary"]["obj"]["changed"], 1)
            self.assertEqual(report["summary"]["npc"]["changed"], 0)
            self.assertEqual(report["unchanged_files"], ["config/dump.npc"])
            self.assertEqual(report["after"]["sha"], "")
            self.assertEqual(set(report["summary"]), {"obj", "npc"})
            self.assertEqual(set(report["coverage"]["types"]), {"obj", "npc"})
            self.assertTrue(all(entry["path"] in {"config/dump.obj", "config/dump.npc"}
                                for entry in report["compared_files"]))
            for kind in cp.EXCLUDED_TYPES:
                with patch("sys.stderr", new=io.StringIO()) as stderr:
                    self.assertEqual(cp.main(args + ["--types", kind]), 1)
                    self.assertIn("Types excluded from output", stderr.getvalue())
            self.assertEqual(first, output.read_bytes())
            with patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(args + ["--types", "obj"]), 0)
            self.assertEqual(json.loads(output.read_text())["coverage"]["types"], ["obj"])

    def test_widget_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side in ("old", "new"):
                (root / side / "config").mkdir(parents=True)
                (root / side / "interface").mkdir()
                (root / side / "config/dump.obj").write_text("// 0\n[item]\n", encoding="utf-8")
                (root / side / "interface/widgets.if3").write_text(f"// 20:4\n[widget]\ntext={side}\n", encoding="utf-8")
            with patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(self.arguments(root)), 0)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["changes"], {})
            self.assertNotIn("interface", report["summary"])
            self.assertFalse(report["coverage"]["interfaces"])
            with patch("sys.stderr", new=io.StringIO()) as stderr:
                self.assertEqual(cp.main(self.arguments(root) + ["--types", "interface"]), 1)
                self.assertIn("Types excluded from output: interface", stderr.getvalue())

    def test_default_output_is_json_relative_to_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side in ("old", "new"):
                (root / side).mkdir()
                (root / side / "dump.obj").write_text("// 0\n[item]\n", encoding="utf-8")
            args = self.arguments(root)[:-2]
            with patch.object(cp, "HERE", root), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(args), 0)
            self.assertEqual([p.name for p in (root / ".cache/reports").iterdir()], ["2026-11-23-rev951.json"])

    def test_failed_generation_preserves_existing_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side in ("old", "new"):
                (root / side).mkdir()
                (root / side / "dump.obj").write_text("// 0\n[item]\n", encoding="utf-8")
            output = root / "report.json"
            output.write_text('{"existing": true}\n')
            original = output.read_bytes()
            with patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(cp.main(self.arguments(root, root / "page.wiki")), 1)
            (root / "new/dump.obj").write_text("// 0\n[item]\ninvalid\n", encoding="utf-8")
            with patch("sys.stdout", new=io.StringIO()), patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(cp.main(self.arguments(root)), 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse((root / "page.wiki").exists())
            self.assertFalse(list(root.glob("*.tmp")))

    def test_bad_local_options_fail_cleanly(self):
        with patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(cp.main(["generate", "--old-dir", "."]), 1)
            self.assertIn("Local mode requires", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
