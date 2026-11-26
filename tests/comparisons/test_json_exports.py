"""Machine-readable changes must preserve source data and semantic identities."""
import unittest

from history import generator as cp
from history.normalization import ReferenceIndex


def records(text):
    return cp.parse_dump(text.splitlines(), "config/dump.obj")


class JsonExportTests(unittest.TestCase):
    def compare(self, old, new, kind="obj", old_index=None, new_index=None):
        data, summary = cp.compare_records(kind, records(old), records(new),
                                           old_index or ReferenceIndex(), new_index or ReferenceIndex())
        self.assertEqual(len(data["added"]), summary["new"])
        self.assertEqual(len(data["removed"]), summary["removed"])
        self.assertEqual(len(data["modified"]), summary["changed"])
        self.assertEqual(sum(len(record["fields"]) for record in data["modified"]), summary["fields_changed"])
        return data

    def test_full_snapshots_keep_repeated_fields_and_unescaped_text(self):
        data = self.compare('// 9\n[old]\nparam=a,1\nparam=b,2\n',
                               '// 11\n[]\nname=Élodie_2 & <br>\nparam=a,"x,y=z"\nparam=b,2\nmodel=one\nmodel=two\n')
        self.assertEqual(data["removed"][0]["id"], 9)
        self.assertEqual(data["removed"][0]["fields"]["param"], ["a,1", "b,2"])
        added = data["added"][0]
        self.assertEqual(added, {"id": 11, "config_name": "", "name": "Élodie_2 & <br>",
                                 "source": "config/dump.obj", "fields": {
                                     "name": ["Élodie_2 & <br>"], "param": ['a,"x,y=z"', "b,2"],
                                     "model": ["one", "two"]}})

    def test_missing_empty_and_literal_null_are_distinct(self):
        data = self.compare('// 1\n[one]\na=\nb=null\nc=old\n',
                               '// 1\n[one]\na=null\nc=\nd=null\n')
        changed = {field["field"]: field for field in data["modified"][0]["fields"]}
        self.assertEqual((changed["a"]["before"], changed["a"]["after"]), ([""], ["null"]))
        self.assertEqual((changed["b"]["before"], changed["b"]["after"]), (["null"], None))
        self.assertEqual(changed["b"]["after_field"], None)
        self.assertEqual((changed["c"]["before"], changed["c"]["after"]), (["old"], [""]))
        self.assertEqual((changed["d"]["before"], changed["d"]["after"]), (None, ["null"]))

    def test_reassigned_reference_exports_raw_values_and_different_ids(self):
        old_index, new_index = ReferenceIndex(), ReferenceIndex()
        old_index.add("model", "7", "same_name")
        new_index.add("model", "8", "same_name")
        data = self.compare('// 1\n[one]\nmodel=same_name\n', '// 1\n[one]\nmodel=same_name\n',
                                  old_index=old_index, new_index=new_index)
        field = data["modified"][0]["fields"][0]
        self.assertEqual(field["before"], ["same_name"])
        self.assertEqual(field["after"], ["same_name"])
        self.assertEqual(field["before_references"], [{"value_index": 0, "path": [], "type": "model", "id": 7}])
        self.assertEqual(field["after_references"][0]["id"], 8)

    def test_parameter_identity_survives_rename_and_alias_only_changes_are_omitted(self):
        old_index, new_index = ReferenceIndex(), ReferenceIndex()
        new_index.add("param", "2", "pet")
        new_index.add("npc", "4", "dragon")
        old_index.param_types["2"] = new_index.param_types["2"] = "npc"
        old = '// 1\n[obj_1]\nparam=param_2,npc_3\nmodel=model_7\n'
        new = '// 1\n[renamed]\nparam=pet,dragon\nmodel=model_7\n'
        data = self.compare(old, new, old_index=old_index, new_index=new_index)
        field = data["modified"][0]["fields"][0]
        self.assertEqual(len(data["modified"][0]["fields"]), 1)
        self.assertEqual(field["identity"], {"field": "param", "entry": {"type": "param", "id": 2}})
        self.assertEqual((field["before_field"], field["after_field"]), ("param[param_2]", "param[pet]"))
        self.assertEqual((field["before"], field["after"]), (["npc_3"], ["dragon"]))
        data = self.compare(old, new.replace("dragon", "npc_3"), old_index=old_index, new_index=new_index)
        self.assertEqual(data, {"added": [], "removed": [], "modified": []})

    def test_enum_entry_identity_and_nested_reference_positions(self):
        data = self.compare('// 1\n[e]\ninputtype=obj\noutputtype=npc\nval=obj_7,npc_3\n',
                               '// 1\n[e]\ninputtype=obj\noutputtype=npc\nval=obj_7,npc_4\n', kind="enum")
        field = data["modified"][0]["fields"][0]
        self.assertEqual(field["identity"], {"field": "val", "entry": {"type": "obj", "id": 7}})
        old_index, new_index = ReferenceIndex(), ReferenceIndex()
        old_index.column_types["4:0"] = new_index.column_types["4:0"] = ("npc", "string")
        data = self.compare('// 1\n[row]\ntable=dbtable_4\ndata=col0,npc_3,hello\n',
                               '// 1\n[row]\ntable=dbtable_4\ndata=col0,npc_4,hello\n', kind="dbrow",
                               old_index=old_index, new_index=new_index)
        field = data["modified"][0]["fields"][0]
        self.assertEqual(field["before"], ["col0,npc_3,hello"])
        self.assertEqual(field["before_references"], [{"value_index": 0, "path": [1, 0], "type": "npc", "id": 3}])


if __name__ == "__main__":
    unittest.main()
