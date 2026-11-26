import contextlib
import gzip
import io
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from builder.build import BrowserData, FILES, main, parse_dump, split_values
from builder.field_types import native_field_type


def record(id, config_name, **fields):
    return {"id": id, "name": config_name, "fields": list(fields.items())}


class ImportTests(unittest.TestCase):
    def test_recoloured_markers_keep_the_original_pixel_pattern_and_transparency(self):
        from builder.build import FRONTEND
        config = json.loads((FRONTEND.parent / 'tools/icon-palettes.json').read_text())
        def chunks(path):
            data = path.read_bytes()
            result, offset = [], 8
            while offset < len(data):
                size = struct.unpack('>I',data[offset:offset+4])[0]
                kind = data[offset+4:offset+8]
                if kind != b'PLTE':
                    result.append(data[offset:offset+12+size])
                offset += 12 + size
            return data[:8],result
        original = chunks(FRONTEND.parent / config['template'])
        for filename in config['icons']:
            self.assertEqual(chunks(FRONTEND / 'images' / filename),original,
                             f'{filename} must differ only in its palette, preserving original pixel data and alpha')

    def test_github_token_is_only_sent_to_the_github_api(self):
        from builder.build import request
        with patch.dict('os.environ',{'GITHUB_TOKEN':'test-token'}),patch('builder.build.urllib.request.urlopen') as opening:
            request('https://api.github.com/repos/owner/repo/commits/main')
            self.assertEqual(opening.call_args.args[0].get_header('Authorization'),'Bearer test-token')
            request('https://raw.githubusercontent.com/owner/repo/main/config/dump.obj')
            self.assertIsNone(opening.call_args.args[0].get_header('Authorization'))
    def test_numeric_comments_preserve_sparse_ids_and_repeated_fields(self):
        rows = list(parse_dump(io.StringIO('// 0\n[zero]\nmodel=a\nmodel=b\n\n// 42\n[last]\nname=A=B\n')))
        self.assertEqual([r["id"] for r in rows], [0, 42])
        self.assertEqual(rows[0]["fields"], [["model", "a"], ["model", "b"]])
        self.assertEqual(rows[1]["fields"], [["name", "A=B"]])

    def test_missing_ids_fail_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            list(parse_dump(["[unknown]", "value=1"]))

    def test_quoted_tuples_and_literal_apostrophes(self):
        self.assertEqual(split_values('col1,"a,b",O\'Brien,42'), ['col1', '"a,b"', "O'Brien", '42'])
        self.assertEqual(split_values("'\\\'',value"), ["'\\\''", "value"])

    def make_data(self):
        data = {p: {} for p in FILES}
        data["params"][9] = record(9, "reward", type="obj", default="null")
        data["params"][10] = record(10, "message", type="string")
        data["items"][42] = record(42, "bronze_sword", name="Bronze sword", param="message,Hello, adventurer")
        data["structs"][0] = record(0, "reward_config", param="reward,bronze_sword")
        data["enums"][3] = record(3, "item_key", inputtype="obj", outputtype="struct", val="bronze_sword,reward_config")
        data["dbtables"][7] = record(7, "rewards", column="col0,obj,string")
        data["dbrows"][12] = record(12, "reward_row", table="rewards", data='col0,bronze_sword,"Hello, world"')
        return BrowserData(data)

    def test_typed_links_zero_id_and_enum_key_references(self):
        data = self.make_data()
        rows = data.rows("enums", data.records["enums"][3])
        self.assertEqual(rows[2]["parsedKey"]["id"], 42)
        self.assertEqual(rows[2]["parsed"][0]["id"], 0)
        self.assertIn(("enums", 3), data.refs["items", 42])
        self.assertIn(("enums", 3), data.refs["structs", 0])

    def test_dbrow_tuple_types_preserve_quoted_commas(self):
        data = self.make_data()
        row = data.rows("dbrows", data.records["dbrows"][12])[1]
        self.assertEqual(row["parsed"][0]["id"], 42)
        self.assertEqual(row["parsed"][1]["text"], "Hello, world")

    def test_item_stack_variants_resolve_items_quantities_and_reverse_refs(self):
        data = self.make_data()
        item = record(5,'stackable',count1='bronze_sword,2',count2='null,3',count3='missing_item,4')
        rows = data.rows('items',item)
        self.assertEqual(rows[0]['type'],'obj, int')
        self.assertEqual(rows[0]['parsed'],[{'type':'items','id':42,'text':'bronze_sword'},{'text':'2'}])
        self.assertEqual(rows[1]['parsed'],[{'text':'null'},{'text':'3'}])
        self.assertEqual(rows[2]['parsed'],[{'text':'missing_item'},{'text':'4'}])
        self.assertIn(('items',5),data.refs['items',42])

    def test_compressed_build_keeps_bootstrap_manifest_and_plain_assets(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            dumps = root / 'dumps'; dumps.mkdir()
            for kind in FILES.values():
                (dumps / f'dump.{kind}').write_text(f'// 0\n[{kind}_0]\n',encoding='utf-8')
            (dumps / 'dump.obj').write_text('// 0\n[obj_0]\nname=Unicode: épée\ncount1=obj_0,2\n',encoding='utf-8')
            output = root / 'site'
            with patch('sys.argv',['builder.build','--dump-dir',str(dumps),'--output',str(output),'--compress-json','--no-history']):
                main()
            manifest = json.loads((output / 'data/manifest.json').read_text())
            self.assertEqual(manifest['compression'],'gzip')
            self.assertFalse((output / 'data/manifest.json.gz').exists())
            self.assertTrue((output / 'key_labels.json').exists())
            self.assertTrue((output / 'index.html').exists())
            from builder.build import FRONTEND
            images = list((FRONTEND / 'images').rglob('*'))
            self.assertTrue(any(image.name == 'struct-icon.png' for image in images))
            for image in images:
                if image.is_file():
                    self.assertEqual((output / 'images' / image.relative_to(FRONTEND / 'images')).read_bytes(),image.read_bytes())
                    if image.name.endswith('-icon.png'):
                        self.assertEqual(struct.unpack('>II',image.read_bytes()[16:24]),(11,11),'Type markers must remain native 11×11 PNGs')
            self.assertFalse((output / 'data/items/0.json').exists())
            with gzip.open(output / 'data/items/0.json.gz','rt',encoding='utf-8') as stream:
                item = json.load(stream)['0']
            self.assertEqual(item['display'],'Unicode: épée')
            self.assertEqual(item['rows'][1]['parsed'][1]['text'],'2')
            with gzip.open(output / 'data/items/index.json.gz','rt',encoding='utf-8') as stream:
                self.assertEqual(json.load(stream)[0]['id'],0)

    def test_npc_quest_arrays_resolve_each_target_and_collect_reverse_references(self):
        records = {page:{} for page in FILES}
        records['quests'] = {0:record(0,'first_quest'),257:record(257,'cooks_assistant')}
        records['npcs'] = {
            278:record(278,'cook',quest='cooks_assistant'),
            279:record(279,'multiple_quests',quest='first_quest,cooks_assistant,missing_quest,null,-1'),
        }
        records['items'] = {1:record(1,'quest_item',quest='257')}
        data = BrowserData(records)
        row = data.rows('npcs',records['npcs'][278])[0]
        self.assertEqual(row['type'],'quest[]')
        self.assertEqual(row['raw'],'cooks_assistant')
        self.assertEqual(row['parsed'],[{'type':'quests','id':257,'text':'cooks_assistant'}])
        multiple = data.rows('npcs',records['npcs'][279])[0]
        self.assertEqual([value.get('id') for value in multiple['parsed']],[0,257,None,None,None])
        self.assertEqual(multiple['parsed'][-3:],[{'text':'missing_quest'},{'text':'null'},{'text':'-1'}])
        item = data.rows('items',records['items'][1])[0]
        self.assertEqual(item['type'],'int')
        self.assertEqual(item['parsed'],[{'text':'257'}])
        self.assertEqual(data.refs['quests',257],{('npcs',278),('npcs',279)})
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            output = Path(folder)
            # Build from fresh collections so field-usage lists contain one entry per field.
            BrowserData(records).build(output)
            usage = json.loads((output/'data/npc_params/field-quest.json').read_text())['quest']
            self.assertEqual(usage['rows'][0]['parsed'][0]['id'],257)
            quest = json.loads((output/'data/quests/2.json').read_text())['257']
            self.assertEqual({(ref['type'],ref['id']) for ref in quest['references']},{('npcs',278),('npcs',279)})

    def make_quickchat_data(self):
        records = {page: {} for page in FILES}
        records['quickchatcategories'] = {
            0:{'id':0,'name':'chatcat_0','fields':[
                ['desc','Skills'],['subcat','chatcat_1,111'],['phrase','chatphrase_0,0'],['phrase','chatphrase_1,120']]},
            1:record(1,'chatcat_1',desc='Agility'),
        }
        records['quickchatphrases'] = {
            0:record(0,'chatphrase_0',phrase='Pick <listdialog(options)>; progress <tostring_varbit(progress)>.',autoresponse='chatphrase_1',searchable='no'),
            1:record(1,'chatphrase_1',phrase='Hello, adventurer!'),
        }
        records['enums'][3] = record(3,'options',inputtype='int',outputtype='string',val='1,Agility')
        records['varplayerbits'][4] = record(4,'progress')
        records['params'][9] = record(9,'suggested_phrase',type='chatphrase',default='chatphrase_0')
        return BrowserData(records,{'stat':{'agility':16}})

    def test_quickchat_categories_and_responses_keep_typed_links_and_shortcut_codes(self):
        data = self.make_quickchat_data()
        rows = data.rows('quickchatcategories',data.records['quickchatcategories'][0])
        self.assertEqual(rows[0]['type'],'string')
        self.assertEqual(rows[1]['type'],'chatcat, int')
        self.assertEqual(rows[1]['raw'],'chatcat_1,111')
        self.assertEqual(rows[1]['parsed'],[{'type':'quickchatcategories','id':1,'text':'Agility'},{'text':'o (111)'}])
        self.assertEqual([row['parsed'][0]['id'] for row in rows[2:]],[0,1])
        self.assertEqual(rows[2]['parsed'][1],{'text':'0'})
        phrase = data.rows('quickchatphrases',data.records['quickchatphrases'][0])
        self.assertEqual(phrase[1]['parsed'],[{'type':'quickchatphrases','id':1,'text':'Hello, adventurer!'}])
        self.assertEqual(phrase[2]['type'],'boolean')
        self.assertIn(('quickchatphrases',0),data.refs['quickchatphrases',1])
        self.assertIn(('quickchatcategories',0),data.refs['quickchatphrases',0])
        self.assertEqual(data.resolve('0','chatcat')['id'],0)
        self.assertEqual(data.rows('params',data.records['params'][9])[1]['parsed'][0]['id'],0)

    def test_quickchat_template_arguments_resolve_without_evaluating_unknown_markup(self):
        data = self.make_quickchat_data()
        text = '<img src=x onerror=alert(1)> <enum_string_varbit(options,progress)><stat_base(agility)> <unknown(progress)> <listdialog(options,extra)> <objdialog()>'
        row = data.rows('quickchatphrases',record(0,'chatphrase_0',phrase=text))[0]
        self.assertEqual(row['raw'],text)
        value = row['parsed'][0]
        self.assertEqual(value['kind'],'inline')
        links = [part for part in value['values'] if part.get('type')]
        self.assertEqual([(part['type'],part['id']) for part in links],[('enums',3),('varplayerbits',4)])
        self.assertIn(('quickchatphrases',0),data.refs['enums',3])
        self.assertIn(('quickchatphrases',0),data.refs['varplayerbits',4])
        rendered = ''.join(part.get('text','') for part in value['values'])
        self.assertIn('<enum_string_varbit(options,progress)><stat_base(16: agility)>',rendered)
        self.assertIn('<img src=x onerror=alert(1)>',rendered)
        self.assertTrue(rendered.endswith('<unknown(progress)> <listdialog(options,extra)> <objdialog()>'))

    def test_quickchat_build_includes_display_text_and_reverse_references(self):
        data = self.make_quickchat_data()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            output = Path(folder)
            counts = data.build(output)
            self.assertEqual(counts['quickchatcategories'],2)
            self.assertEqual(counts['quickchatphrases'],2)
            categories = json.loads((output/'data/quickchatcategories/index.json').read_text())
            self.assertEqual(categories[0]['display'],'Skills')
            phrases = json.loads((output/'data/quickchatphrases/0.json').read_text())
            self.assertEqual(phrases['1']['display'],'Hello, adventurer!')
            self.assertEqual({(ref['type'],ref['id']) for ref in phrases['1']['references']},{('quickchatcategories',0),('quickchatphrases',0)})
            enum = json.loads((output/'data/enums/0.json').read_text())['3']
            self.assertEqual(enum['references'],[{'type':'quickchatphrases','id':0,'text':'chatphrase_0'}])

    def test_string_values_do_not_become_links(self):
        data = self.make_data()
        self.assertEqual(data.resolve("bronze_sword", "string"), {"text": "bronze_sword"})
        self.assertEqual(data.resolve("null", "obj"), {"text": "null"})

    def test_cursor_graphics_hotspots_and_native_references(self):
        records = {p:{} for p in FILES}
        records['cursors'] = {0:record(0,'cursor_move',graphic='mob_move_cursor',hotspot='0,0'),45:record(45,'cursor_take',graphic='"cursors_generic,2"',hotspot='5,7')}
        records['items'] = {3:record(3,'notes',cursor3='cursor_take',icursor1='cursor_move')}
        records['npcs'] = {1:record(1,'man',cursorattack='cursor_take')}
        records['scenery'] = {1:record(1,'crate',cursor1='cursor_take')}
        records['params'] = {9:record(9,'action_cursor',type='cursor')}
        records['structs'] = {2:record(2,'action',param='action_cursor,cursor_take')}
        data = BrowserData(records,{'graphic':{'mob_move_cursor':898,'cursors_generic,2':999}})
        rows = data.rows('cursors',records['cursors'][45])
        self.assertTrue(rows[0]['parsed'][0]['src'].endswith('/999-0.png'))
        self.assertEqual(rows[1]['parsed'],[{'text':'X: 5'},{'text':'Y: 7'}])
        for page,id in [('items',3),('npcs',1),('scenery',1),('structs',2)]:
            data.rows(page,records[page][id])
            self.assertIn((page,id),data.refs['cursors',45])
        self.assertEqual(data.resolve('cursor_move','cursor')['id'],0)
        self.assertEqual(native_field_type('cursors','hotspot'),'int, int')
        legacy = data.rows('items',record(4,'old_item',cursor1='2,cursor_take'))[0]
        self.assertEqual(legacy['parsed'],[{'text':'2'},{'type':'cursors','id':45,'text':'cursor_take'}])

    def test_scenery_morphs_parameters_and_typed_references(self):
        records = {p: {} for p in FILES}
        records['scenery'] = {0:record(0,'door_morph',multiloc='1,door_open',multivar='door_state'),1:record(1,'door_open',name='Open door',model='10,door_model')}
        records['varplayerbits'] = {8:record(8,'door_state')}
        records['params'] = {7:record(7,'target_scenery',type='loc')}
        records['structs'] = {5:record(5,'door_settings',param='target_scenery,door_open')}
        records['enums'] = {6:record(6,'doors',inputtype='int',outputtype='loc',val='0,door_open')}
        data = BrowserData(records)
        morph = data.rows('scenery',records['scenery'][0])
        self.assertEqual(morph[0]['parsed'][1]['type'],'scenery')
        self.assertEqual(morph[0]['parsed'][1]['id'],1)
        self.assertEqual(morph[1]['parsed'][0]['id'],8)
        self.assertIn(('scenery',0),data.refs['varplayerbits',8])
        data.rows('structs',records['structs'][5])
        data.rows('enums',records['enums'][6])
        self.assertEqual(data.refs['scenery',1],{('scenery',0),('structs',5),('enums',6)})
        self.assertEqual(data.resolve('door_open','object')['id'],1)
        self.assertEqual(native_field_type('scenery','model'),'loc shape, model')
        self.assertEqual(native_field_type('scenery','blockwalk'),'boolean')

    def test_cs2_params_are_identified_even_without_a_definition(self):
        data = self.make_data()
        item = record(3, "nulodions_notes", name="Nulodion's notes")
        item["fields"].extend([["param", "message,Hello"], ["param", "unknown_param,1"]])
        rows = data.rows("items", item)
        self.assertNotIn("kind", rows[0])
        self.assertEqual(rows[1]["kind"], "param")
        self.assertEqual(rows[1]["param"], 10)
        self.assertEqual(rows[2]["kind"], "param")
        self.assertNotIn("param", rows[2])

    def test_native_names_and_types_do_not_depend_on_value_spelling(self):
        data = self.make_data()
        item = record(3, "nulodions_notes", name="123", model="inv_book", members="yes", **{"2dzoom": "844", "iop1": "Read", "stackable": "sometimes"})
        rows = {r["key"]: r for r in data.rows("items", item)}
        for key, expected in {"name": "string", "model": "model", "members": "boolean", "2dzoom": "int", "iop1": "string", "stackable": "stackability"}.items():
            self.assertEqual(rows[key]["key_name"], key)
            self.assertEqual(rows[key]["type"], expected)
        self.assertEqual(native_field_type("items", "future_field"), "unknown")

    def test_tuple_and_context_specific_types(self):
        self.assertEqual(native_field_type("items", "count1"), "obj, int")
        self.assertEqual(native_field_type("items", "manwearoff"), "int, int, int")
        self.assertEqual(native_field_type("items", "quest"), "int")
        self.assertEqual(native_field_type("npcs", "quest"), "quest[]")
        self.assertEqual(native_field_type("achievements", "questreq"), "int, quest")
        self.assertEqual(native_field_type("quests", "questreq"), "quest")
        self.assertEqual(native_field_type("varplayerbits", "basevar", record(0, "bit", domain="npc")), "varnpc")

    def test_achievement_requirement_labels_multiple_targets_and_reverse_refs(self):
        records = {p: {} for p in FILES}
        records['varplayerbits'] = {1: record(1, 'course_a'), 2: record(2, 'course_b')}
        data = BrowserData(records)
        achievement = record(2241, 'courses', varbitreq="0,1,Course, with a comma,course_a,course_b")
        row = data.rows('achievements', achievement)[0]
        self.assertEqual(row['group'], 'achievement-requirements')
        cells = row['parsed'][0]['rows'][0]
        self.assertEqual(cells[2]['text'], 'Course, with a comma')
        self.assertEqual([v['id'] for v in cells[3]['values']], [1, 2])
        for id in [1, 2]:
            self.assertIn(('achievements', 2241), data.refs['varplayerbits', id])

    def test_achievement_quest_group_is_not_a_quest_reference(self):
        records = {p: {} for p in FILES}
        records['quests'] = {0: record(0, 'wrong_quest'), 7: record(7, 'right_quest')}
        data = BrowserData(records)
        row = data.rows('achievements', record(4, 'achievement', questprereq='0,right_quest'))[0]
        self.assertEqual(row['parsed'][0]['rows'][0][1]['id'], 7)
        self.assertNotIn(('achievements', 4), data.refs['quests', 0])
        self.assertIn(('achievements', 4), data.refs['quests', 7])

    def test_achievement_description_bit_test_and_graphic_symbols(self):
        records = {p: {} for p in FILES}
        records['varplayerbits'] = {8: record(8, 'progress')}
        data = BrowserData(records, {'graphic': {'achievement_icon_default': 30108, 'quest_icons_large,1': 2379}, 'category': {'skills':4815}})
        rows = data.rows('achievements', record(9, 'example', desc='0,A description, with punctuation.', varbittestbitreq='0,progress,1,Course, with a comma,3', sprite='achievement_icon_default', category='skills'))
        self.assertEqual(rows[0]['parsed'], [{'text': 'A description, with punctuation.'}])
        cells = rows[1]['parsed'][0]['rows'][0]
        self.assertEqual(cells[2]['text'], 'Course, with a comma')
        self.assertEqual(cells[3]['id'], 8)
        self.assertEqual(cells[4]['text'], '3')
        self.assertEqual(rows[2]['parsed'][0]['kind'], 'image')
        self.assertTrue(rows[2]['parsed'][0]['src'].endswith('/30108-0.png'))
        self.assertTrue(data.resolve('"quest_icons_large,1"', 'graphic')['src'].endswith('/2379-0.png'))
        self.assertEqual(rows[3]['parsed'], [{'text':'4815: skills'}])

    def test_field_pages_are_distinct_from_shared_params(self):
        data = self.make_data()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            output = Path(folder)
            counts = data.build(output)
            index = json.loads((output / "data/item_params/index.json").read_text())
            self.assertEqual([r["id"] for r in index], ["name"])
            self.assertEqual(counts["item_params"], 1)
            field_page = json.loads((output / "data/item_params/field-name.json").read_text())["name"]
            self.assertEqual(field_page["rows"][0]["raw"], "Bronze sword")
            self.assertEqual(field_page["rows"][0]["key_name"], "name")
            self.assertEqual(field_page["rows"][0]["type"], "string")
            param = json.loads((output / "data/params/0.json").read_text())["10"]
            self.assertEqual(param["uses"][0]["raw"], "Hello, adventurer")
            self.assertEqual(param["uses"][0]["key_name"], "message")
            item = json.loads((output / "data/items/0.json").read_text())["42"]
            self.assertEqual(item["refs"], 3)

    def make_extra_data(self):
        records = {page:{} for page in FILES}
        records['varplayers'][0] = record(0,'state',type='int',scope='perm',clientcode='0')
        records['varplayerbits'][3] = record(3,'progress',domain='player',basevar='state',startbit='0',endbit='1')
        records['mapelements'] = {
            0:record(0,'map_start',sprite='icon',multivar='state',multimel='default,map_end',condition='progress,0,1'),
            1:record(1,'map_end',text='Destination',sprite='"atlas,2"'),
        }
        records['mapsceneicons'][0] = record(0,'msi_0',graphic='"atlas,2"',hideonminimap='yes')
        records['animationsets'][0] = record(0,'human',readyanim='idle,walk',randomreadyanim='walk,80',unknown53='no')
        records['sequences'] = {0:record(0,'idle',frame1='animframe_1_1',delay1='2',replaceheldleft='sword'),
                                1:record(1,'walk',frame1='animframe_2_1',delay1='3',replaceheldright='hide'),
                                129:record(129,'last_seq',keyframeset='keyframeset_1',keyframerange='0,20')}
        records['items'][42] = record(42,'sword')
        records['spoteffects'][0] = record(0,'spark',anim='idle',model='spark_model',allowloop='yes')
        records['hitsplats'] = {0:record(0,'hit',classgraphic='icon',multivar='progress',multimark='1,hit_alt'),
                               1:record(1,'hit_alt',leftgraphic='"atlas,2"')}
        records['healthbars'][0] = record(0,'health',full='icon',empty='"atlas,2"',fadeout='no',tilefill='yes')
        records['npcs'][278] = record(278,'cook',bas='human',mapelement='map_start',multivar='progress')
        records['scenery'][0] = record(0,'tree',anim='walk,3',msi='msi_0',mapelement='map_start',multivar='state')
        records['achievements'][1] = record(1,'task',varpreq='0,1,Label, with comma,state')
        records['quests'][0] = record(0,'quest',masterquestvarp='state,1,2')
        records['quickchatphrases'][0] = record(0,'chatphrase_0',phrase='Progress: <tostring_varp(state)>.')
        return BrowserData(records,{'graphic':{'icon':10,'atlas,2':20}})

    def test_added_configs_link_native_dependencies_and_preserve_frame_values(self):
        data = self.make_extra_data()
        def rows(page,id=0): return {row['key']:row for row in data.rows(page,data.records[page][id])}
        self.assertEqual(rows('varplayerbits',3)['basevar']['parsed'][0]['id'],0)
        self.assertEqual(rows('npcs',278)['bas']['parsed'][0]['type'],'animationsets')
        self.assertEqual(rows('scenery')['msi']['parsed'][0]['type'],'mapsceneicons')
        self.assertEqual(rows('scenery')['anim']['parsed'],[{'type':'sequences','id':1,'text':'walk'},{'text':'3'}])
        animations = rows('animationsets')
        self.assertEqual([value['id'] for value in animations['readyanim']['parsed']],[0,1])
        self.assertEqual(animations['randomreadyanim']['parsed'][1],{'text':'80'})
        sequence = rows('sequences')
        self.assertEqual(sequence['frame1']['type'],'animframe')
        self.assertEqual(sequence['frame1']['parsed'],[{'text':'animframe_1_1'}])
        self.assertEqual(sequence['replaceheldleft']['parsed'][0]['id'],42)
        self.assertEqual(rows('sequences',1)['replaceheldright']['parsed'],[{'text':'hide'}])
        self.assertEqual(rows('spoteffects')['anim']['parsed'][0]['type'],'sequences')
        self.assertEqual(rows('mapelements')['condition']['parsed'][0]['type'],'varplayerbits')
        self.assertEqual(rows('mapelements')['multivar']['parsed'][0]['type'],'varplayers')
        self.assertEqual(rows('hitsplats')['multimark']['parsed'][1]['id'],1)
        self.assertEqual(rows('healthbars')['full']['parsed'][0]['src'],'https://chisel.weirdgloop.org/static/img/rs3-graphic/10-0.png')
        self.assertEqual(data.resolve('map_end','mapelement')['text'],'Destination')
        for kind,page in [('varplayer','varplayers'),('spotanim','spoteffects'),('hitmark','hitsplats'),('headbar','healthbars')]:
            self.assertEqual(data.resolve('0',kind)['type'],page)
        # Colliding variable names are ambiguous in the text format, not a guessed domain.
        data.names['varplayerbits']['state'] = 3
        self.assertEqual(rows('scenery')['multivar']['parsed'],[{'text':'state'}])

    def test_added_configs_build_previews_reverse_refs_and_stream_sparse_chunks(self):
        data = self.make_extra_data()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            output = Path(folder)
            counts = data.build(output)
            self.assertEqual(counts['sequences'],3)
            sequence = json.loads((output/'data/sequences/1.json').read_text())['129']
            self.assertEqual(sequence['name'],'last_seq')
            first = json.loads((output/'data/sequences/0.json').read_text())['0']
            self.assertEqual({(r['type'],r['id']) for r in first['references']},{('animationsets',0),('spoteffects',0)})
            player = json.loads((output/'data/varplayers/0.json').read_text())['0']
            refs = {(r['type'],r['id']) for r in player['references']}
            self.assertTrue({('varplayerbits',3),('scenery',0),('achievements',1),('quests',0),('quickchatphrases',0)} <= refs)
            for page in ['mapsceneicons','healthbars','hitsplats','mapelements']:
                index = json.loads((output/f'data/{page}/index.json').read_text())
                self.assertEqual(index[0]['preview']['kind'],'image')
            scene = json.loads((output/'data/scenery/0.json').read_text())['0']
            icon = next(row for row in scene['rows'] if row['key']=='msi')['parsed'][0]
            self.assertTrue(icon['preview']['src'].endswith('/20-0.png'))
            self.assertFalse(any(page=='sequences' for page,key in data.field_uses))


if __name__ == "__main__":
    unittest.main()
