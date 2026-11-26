"""Semantic reference comparisons must not hide literal or identity changes."""
from pathlib import Path
import bz2
import gzip
import io
import json
import struct
import tempfile
import unittest
from unittest.mock import patch

from history import generator as cp
from history.normalization import ReferenceIndex, split_values, normalized_changes
from history.asset_names import decode_asset_names


def record(body, symbol="example", identifier="0", source="config/dump.obj"):
    return cp.Record(identifier, symbol, body, source)


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.old, self.new = ReferenceIndex(), ReferenceIndex()
        self.new.add("model", "1", "dragon_mesh")
        self.new.add("npc", "3", "dragon_pet")
        self.new.add("param", "2", "pet_npc")
        self.old.param_types["2"] = self.new.param_types["2"] = "npc"

    def diff(self, old, new, kind="obj"):
        return [(f["field"], tuple(f["before"] or ()), tuple(f["after"] or ()))
                for f in normalized_changes(old, new, kind, self.old, self.new)]

    def test_generic_and_named_references_and_parameter_keys_match(self):
        old = record("model=model_1\nparam=param_2,npc_3", "obj_0")
        new = record("model=dragon_mesh\nparam=pet_npc,dragon_pet", "dragon")
        self.assertEqual(self.diff(old, new), [])
        self.assertEqual(self.new.stats["ignored_record_names"], 1)
        self.assertEqual(self.new.stats["ignored_reference_fields"], 2)

    def test_actual_reference_changes_remain_and_keep_readable_values(self):
        self.new.add("model", "4", "different_mesh")
        self.assertEqual(self.diff(record("model=model_1"), record("model=different_mesh")),
                         [("model", ("model_1",), ("different_mesh",))])

    def test_same_text_resolving_to_a_different_id_is_a_change(self):
        self.old.add("model", "7", "reused_name")
        self.new.add("model", "8", "reused_name")
        self.assertEqual(self.diff(record("model=reused_name"), record("model=reused_name")),
                         [("model", ("reused_name",), ("reused_name",))])

    def test_unchanged_text_with_one_unresolved_argument_is_not_a_change(self):
        self.old.add("stat", "0", "attack")
        self.new.add("stat", "0", "attack")
        self.new.add("model", "90", "attack")
        self.assertEqual(self.diff(record("onload=script18264(event_com, attack)"),
                                   record("onload=script18264(event_com, attack)"), "interface"), [])

    def test_untyped_handler_arguments_do_not_prefer_component_names(self):
        self.old.add("stat", "0", "attack")
        self.new.add("stat", "0", "attack")
        self.new.add("component", "0:5", "interface_name:attack")
        self.assertEqual(self.diff(record("onload=script18264(event_com, attack)"),
                                   record("onload=script18264(event_com, attack)"), "interface"), [])

    def test_display_text_and_string_parameters_stay_literal(self):
        self.new.add("param", "5", "description")
        self.old.param_types["5"] = self.new.param_types["5"] = "string"
        diffs = self.diff(record("name=model_1\nparam=param_5,model_1\niop1=model_1"),
                          record("name=dragon_mesh\nparam=description,dragon_mesh\niop1=dragon_mesh"))
        self.assertEqual({field for field, _, _ in diffs}, {"name", "param[description]", "iop1"})

    def test_unknown_fields_are_not_guessed(self):
        self.assertEqual(len(self.diff(record("unknown999=model_1"), record("unknown999=dragon_mesh"))), 1)

    def test_enum_keys_and_outputs_are_typed(self):
        self.new.add("obj", "9", "reward")
        old = record("inputtype=obj\noutputtype=npc\nval=obj_9,npc_3\ndefault=npc_3")
        new = record("inputtype=obj\noutputtype=npc\nval=reward,dragon_pet\ndefault=dragon_pet")
        self.assertEqual(self.diff(old, new, "enum"), [])
        old_string = record("inputtype=string\noutputtype=int\nval=obj_9,1")
        new_string = record("inputtype=string\noutputtype=int\nval=reward,1")
        self.assertEqual(len(self.diff(old_string, new_string, "enum")), 2)

    def test_database_columns_and_typed_values(self):
        self.new.add("dbtable", "4", "rewards")
        self.new.add("dbcolumn", "4:0", "rewards:pet")
        self.old.column_types["4:0"] = self.new.column_types["4:0"] = ("npc", "string")
        old = record("table=dbtable_4\ndata=col0,npc_3,model_1")
        new = record("table=rewards\ndata=pet,dragon_pet,model_1")
        self.assertEqual(self.diff(old, new, "dbrow"), [])
        changed_text = record("table=rewards\ndata=pet,dragon_pet,dragon_mesh")
        self.assertEqual([d[0] for d in self.diff(old, changed_text, "dbrow")], ["data"])

    def test_interface_local_components_and_scripts(self):
        self.new.add("interface", "490", "assault")
        self.new.add("component", "490:3", "assault:points")
        self.new.add("clientscript", "42", "[clientscript,update_points]")
        old = record('layer=com_3\nonload=script42(interface_490:com_3, "model_1")', identifier="490:4")
        new = record('layer=points\nonload=update_points(assault:points, "model_1")', identifier="490:4")
        self.assertEqual(self.diff(old, new, "interface"), [])
        text_changed = record('layer=points\nonload=update_points(assault:points, "dragon_mesh")', identifier="490:4")
        self.assertEqual([d[0] for d in self.diff(old, text_changed, "interface")], ["onload"])

    def test_explicit_script_names_take_precedence_over_generic_fallbacks(self):
        self.new.add("clientscript", "900", "[clientscript,script750]")
        self.assertEqual([d[0] for d in self.diff(record("onload=script750"), record("onload=script750"), "interface")], ["onload"])

    def test_repeated_models_preserve_order(self):
        old = record("model=model_1\nmodel=model_2")
        self.new.add("model", "2", "other_mesh")
        new = record("model=dragon_mesh\nmodel=other_mesh")
        self.assertEqual(self.diff(old, new), [])
        self.assertEqual(len(self.diff(old, record("model=other_mesh\nmodel=dragon_mesh"))), 1)

    def test_symbols_and_metadata_load_from_revision_files(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "param.sym"
            p.write_text("2\tpet_npc\tnpc\n5\tdescription\tstring\n", encoding="utf-8")
            index = ReferenceIndex()
            index.load_symbols(p, "param")
            self.assertEqual(index.param_types, {"2": "npc", "5": "string"})
            self.assertEqual(index.resolve("param", "pet_npc"), ("ref", "param", "2"))

    def test_ambiguous_names_are_not_resolved(self):
        self.old.add("model", "1", "ambiguous")
        self.old.add("model", "2", "ambiguous")
        self.assertIsNone(self.old.resolve("model", "ambiguous"))

    def test_quoted_comma_fields_split_without_losing_string_text(self):
        self.assertEqual(split_values('one,"two,three",four'), ["one", '"two,three"', "four"])

    def test_material_references_and_var_parameters(self):
        self.new.add("material", "1516", "granite_wall")
        self.assertEqual(self.diff(record("retex1s=material_1516"), record("retex1s=granite_wall")), [])
        self.new.add("param", "8", "progress")
        self.old.param_types["8"] = self.new.param_types["8"] = "var_int"
        self.new.add("varbit", "60823", "quest_progress")
        self.assertEqual(self.diff(record("param=param_8,varplayerbit_60823"),
                                   record("param=progress,quest_progress")), [])

    def test_quickchat_command_arguments_without_hiding_text(self):
        self.new.add("enum", "7", "training_locations")
        old = record("phrase=Go to <listdialog(enum_7)> now")
        new = record("phrase=Go to <listdialog(training_locations)> now")
        self.assertEqual(self.diff(old, new, "quickchatphrase"), [])
        self.assertEqual(len(self.diff(old, record("phrase=Leave <listdialog(training_locations)> now"), "quickchatphrase")), 1)

    def test_conditional_vars_domains_fonts_and_material_fields(self):
        self.new.add("varbit", "22", "progress")
        self.new.add("varclansetting", "294", "clan_permissions")
        self.new.add("fontmetrics", "67", "p12_full")
        self.new.add("material", "33", "ground_stone")
        for kind, old, new in [
            ("mel", "condition=varplayerbit_22,1,5", "condition=progress,1,5"),
            ("varbit", "domain=clan_setting\nbasevar=varclansetting_294", "domain=clan_setting\nbasevar=clan_permissions"),
            ("interface", "textfont=fontmetrics_67", "textfont=p12_full"),
            ("flo", "material=material_33", "material=ground_stone"),
        ]:
            with self.subTest(kind=kind):
                self.assertEqual(self.diff(record(old), record(new), kind), [])

    def test_database_var_int_cells_and_primitive_script_arguments(self):
        self.new.add("dbtable", "4", "rewards")
        self.new.add("dbcolumn", "4:0", "rewards:progress")
        self.old.column_types["4:0"] = self.new.column_types["4:0"] = ("var_int",)
        self.new.add("varbit", "22", "quest_progress")
        self.assertEqual(self.diff(record("table=dbtable_4\ndata=col0,varplayerbit_22"),
                                   record("table=rewards\ndata=progress,quest_progress"), "dbrow"), [])
        self.new.add("model", "123", "true")
        self.assertEqual(self.diff(record("onload=script750(true)"), record("onload=script750(true)"), "interface"), [])

    def test_offline_generation_filters_name_only_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for side, symbol, model in [("old", "obj_0", "model_1"), ("new", "named_item", "dragon_mesh")]:
                folder = root / side
                (folder / "config").mkdir(parents=True)
                (folder / "symbols").mkdir()
                (folder / "config/dump.obj").write_text(f"// 0\n[{symbol}]\nname=Visible name\nmodel={model}\n", encoding="utf-8")
            (root / "new/symbols/model.sym").write_text("1\tdragon_mesh\n2\tother_mesh\n", encoding="utf-8")
            output = root / "report.json"
            args = ["generate", "--old-dir", str(root / "old"), "--new-dir", str(root / "new"),
                    "--date", "2026-10-26", "--revision", "951", "--output", str(output)]
            with patch.object(cp.GitHubSource, "request", side_effect=AssertionError("offline")), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(args), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["obj"]["changed"], 0)
            self.assertEqual(report["changes"], {})
            (root / "new/config/dump.obj").write_text("// 0\n[named_item]\nname=Visible name\nmodel=other_mesh\n", encoding="utf-8")
            with patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(cp.main(args), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["obj"]["changed"], 1)
            self.assertEqual(report["summary"]["obj"]["fields_changed"], 1)


class AssetNameTests(unittest.TestCase):
    def test_dense_and_sparse_ids_and_js5_compression(self):
        for pack_type in (1, 2):
            offsets = struct.pack(">iii", 0, -1, 6) if pack_type == 1 else struct.pack(">IiIiIi", 15, 0, 50, -1, 900, 6)
            data = struct.pack(">II", pack_type, 3) + offsets + b"STONE\0wood\0"
            for compression in (0, 1, 2):
                encoded = data if compression == 0 else bz2.compress(data, compresslevel=1)[4:] if compression == 1 else gzip.compress(data)
                container = struct.pack(">BI", compression, len(encoded)) + (struct.pack(">I", len(data)) if compression else b"") + encoded
                self.assertEqual(decode_asset_names(container), [("0", "stone"), ("2", "wood")] if pack_type == 1 else [("15", "stone"), ("900", "wood")])

    def test_malformed_offsets_fail_instead_of_guessing(self):
        data = struct.pack(">IIi", 1, 1, 5000)
        with self.assertRaisesRegex(ValueError, "offset"):
            decode_asset_names(struct.pack(">BI", 0, len(data)) + data)


if __name__ == "__main__":
    unittest.main()
