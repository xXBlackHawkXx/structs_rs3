import gzip
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from builder.history import history_digest, import_report_files, import_reports, prepare_history
from builder.history_values import parsed_values


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'input'
        self.inputs.mkdir()
        self.source = self.root / 'history'
        self.output = self.root / 'dist'
        self.pages = {'items':'obj', 'enums':'enum'}
        self.types = {'obj':'items', 'enum':'enums'}

    def report(self, day, before_sha, after_sha, changes):
        value = {'schema_version':2,
                 'before':{'sha':before_sha,'date':f'2026-11-{day-1:02d}','revision':'951'},
                 'after':{'sha':after_sha,'date':f'2026-11-{day:02d}','revision':'951'},
                 'coverage':{'types':['obj','enum','unsupported']}, 'changes':changes}
        (self.inputs / f'2026-11-{day:02d}-rev951.json').write_text(json.dumps(value), encoding='utf-8')

    def load(self, page, identifier):
        return json.loads((self.output / 'data' / 'history' / page / f'{identifier//64}.json').read_text())[str(identifier)]

    def test_semantic_changes_preserve_missing_empty_null_and_historical_ids(self):
        fields = [{'field':'val[1]', 'identity':{'field':'val','entry':{'value':'1'}},
                   'before':['same_name','','null'], 'after':None,
                   'before_references':[{'value_index':0,'path':[],'type':'obj','id':123}]}]
        self.report(2, 'a'*40, 'b'*40, {'enum':{'modified':[
            {'id':65,'before':{'config_name':'old','fields':{'unrelated':['ignore']}},
             'after':{'config_name':'new','fields':{'unrelated':['renamed']}},'fields':fields}]},
            'unsupported':{'added':[{'id':'composite:key'}]}})
        reports = import_reports(self.inputs,self.source,self.pages)
        compact = json.loads(gzip.decompress((self.source / 'reports' / reports[0]['file']).read_bytes()))
        self.assertNotIn('before',compact['changes']['enums']['modified'][0])
        info = prepare_history(self.source,self.output,self.pages,self.types,'b'*40)
        entry = self.load('enums',65)
        self.assertEqual(entry['name'],'new')
        exported = entry['events'][0]['fields'][0]
        self.assertEqual({key:exported[key] for key in fields[0]},fields[0])
        self.assertEqual(exported['before_parsed'],[{'type':'items','id':123,'text':'same_name'},{'text':''},{'text':'null'}])
        self.assertIsNone(exported['after_parsed'])
        self.assertEqual(info['chunks'],{'enums':[1]})
        self.assertEqual(info['types'],['enums','items'])
        self.assertEqual(info['from'],'2026-11-01')

    def test_added_removed_and_known_revision_cutoff(self):
        item = {'id':3,'config_name':'example','fields':{'name':['Example'],'empty':['']}}
        self.report(2,'a'*40,'b'*40,{'obj':{'added':[item]}})
        self.report(3,'b'*40,'c'*40,{'obj':{'removed':[item]}})
        import_reports(self.inputs,self.source,self.pages)
        earlier = prepare_history(self.source,self.output,self.pages,self.types,'b'*40)
        self.assertEqual(len(earlier['reports']),1)
        self.assertEqual(self.load('items',3)['events'][0]['fields'][0]['before'],None)
        later = prepare_history(self.source,self.output,self.pages,self.types,'c'*40)
        events = self.load('items',3)['events']
        self.assertEqual(len(later['reports']),2)
        self.assertEqual([event['kind'] for event in events],['added','removed'])
        self.assertEqual(events[1]['fields'][0]['before'],['Example'])
        self.assertIsNone(events[1]['fields'][0]['after'])

    def test_checksum_failure_and_optional_absence(self):
        self.assertIsNone(prepare_history(self.source,self.output,self.pages,self.types))
        self.report(2,'a'*40,'b'*40,{})
        reports = import_reports(self.inputs,self.source,self.pages)
        (self.source / 'reports' / reports[0]['file']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):
            prepare_history(self.source,self.output,self.pages,self.types)

    def test_duplicate_ids_rejected(self):
        item = {'id':3,'config_name':'example','fields':{}}
        self.report(2,'a'*40,'b'*40,{'obj':{'added':[item],'removed':[item]}})
        with self.assertRaisesRegex(ValueError,'Duplicate obj ID'):
            import_reports(self.inputs,self.source,self.pages)

    def test_duplicate_comparisons_rejected(self):
        self.report(2,'a'*40,'b'*40,{})
        import_reports(self.inputs,self.source,self.pages)
        path = self.source / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['reports'] *= 2
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'Duplicate history comparison'):
            prepare_history(self.source,self.output,self.pages,self.types)

    def test_incremental_import_merges_and_is_idempotent(self):
        self.report(2,'a'*40,'b'*40,{})
        import_reports(self.inputs,self.source,self.pages)
        self.report(3,'b'*40,'c'*40,{})
        path = self.inputs / '2026-11-03-rev951.json'
        reports = import_report_files([path],self.source,self.pages)
        self.assertEqual(len(reports),2)
        before = (self.source / 'manifest.json').read_bytes()
        import_report_files([path],self.source,self.pages)
        self.assertEqual((self.source / 'manifest.json').read_bytes(),before)

    def test_failed_partial_import_keeps_previous_manifest_and_reports(self):
        self.report(2,'a'*40,'b'*40,{})
        original = import_reports(self.inputs,self.source,self.pages)[0]
        before = (self.source / 'manifest.json').read_bytes()
        payload = (self.source / 'reports' / original['file']).read_bytes()
        self.report(3,'b'*40,'c'*40,{})
        invalid = self.inputs / 'invalid.json'
        invalid.write_text('{')
        with self.assertRaises(ValueError):
            import_report_files([self.inputs / '2026-11-03-rev951.json',invalid],self.source,self.pages)
        self.assertEqual((self.source / 'manifest.json').read_bytes(),before)
        self.assertEqual((self.source / 'reports' / original['file']).read_bytes(),payload)

    def test_same_day_snapshots_are_cut_off_by_exact_commit(self):
        self.report(2,'a'*40,'b'*40,{})
        path = self.inputs / '2026-11-02-rev951.json'
        first = json.loads(path.read_text())
        first['after']['title'] = '2026-11-02a-rev951'
        path.write_text(json.dumps(first))
        second = {**first,'before':first['after'],'after':{**first['after'],'sha':'c'*40,'title':'2026-11-02b-rev951'}}
        (self.inputs / '2026-11-02-rev951-b.json').write_text(json.dumps(second))
        import_reports(self.inputs,self.source,self.pages)
        info = prepare_history(self.source,self.output,self.pages,self.types,'b'*40)
        self.assertEqual(len(info['reports']),1)

    def test_build_includes_history_in_compressed_output(self):
        from builder.build import FILES, main
        self.report(2,'a'*40,'b'*40,{'obj':{'removed':[{'id':3,'config_name':'removed','fields':{'name':['Old name']}}]}})
        import_reports(self.inputs,self.source,self.pages)
        dumps = self.root / 'dumps'
        dumps.mkdir()
        for kind in FILES.values():
            (dumps / f'dump.{kind}').write_text(f'// 0\n[{kind}_0]\n',encoding='utf-8')
        state = {'revision':'b'*40,'source_digest':'code','history_digest':history_digest(self.source)}
        state_path = self.root / 'state.json'
        state_path.write_text(json.dumps(state))
        with patch('sys.argv',['builder.build','--dump-dir',str(dumps),'--output',str(self.output),
                               '--history-dir',str(self.source),'--compress-json','--ref','b'*40,'--pipeline-state',str(state_path)]), contextlib.redirect_stdout(io.StringIO()):
            main()
        manifest = json.loads((self.output / 'data/manifest.json').read_text())
        self.assertEqual(manifest['history']['counts']['items'],1)
        self.assertEqual(manifest['compression'],'gzip')
        self.assertEqual(manifest['pipeline'],{key:state[key] for key in ('source_digest','history_digest')})
        with gzip.open(self.output / 'data/history/items/0.json.gz','rt',encoding='utf-8') as stream:
            self.assertEqual(json.load(stream)['3']['events'][0]['kind'],'removed')
        self.assertFalse((self.output / 'data/history/items/0.json').exists())

    def test_build_rejects_mismatched_pipeline_state_before_loading_dumps(self):
        from builder.build import main
        state = self.root / 'state.json'
        state.write_text(json.dumps({'revision':'wrong','source_digest':'code','history_digest':'wrong'}))
        with patch('sys.argv',['builder.build','--dump-dir',str(self.root),'--pipeline-state',str(state)]),self.assertRaisesRegex(ValueError,'Pipeline state does not match'):
            main()

    def test_parsed_values_use_recorded_ids_and_preserve_snapshot_context(self):
        snapshot = {'id':3,'fields':{'inputtype':['int'],'outputtype':['obj']}}
        for identifier in (42,99):
            refs = [{'value_index':0,'path':[],'type':'obj','id':identifier}]
            value = parsed_values('enums','val',['same_name'],refs,snapshot,'val[1]')[0]
            self.assertEqual(value,{'type':'items','id':identifier,'text':'same_name'})
        # Coordinate parsing uses that side's enum type, without a current-dump lookup.
        snapshot['fields']['outputtype'] = ['coord']
        self.assertEqual(parsed_values('enums','val',['1_2_3_4_5'],[],snapshot,'val[1]'),[{'text':'1, 132, 197'}])

    def test_parsed_achievement_requirement_and_nested_dbrow_reference(self):
        snapshot = {'fields':{}}
        refs = [{'value_index':0,'path':[3],'type':'stat','id':18}]
        value = parsed_values('achievements','statprereq',['0,115,Skill: 115 Slayer, with comma,slayer'],refs,snapshot)[0]
        self.assertEqual(value['headers'],['group','value','name','stats'])
        row = value['rows'][0]
        self.assertEqual(row[2],{'text':'Skill: 115 Slayer, with comma'})
        self.assertEqual(row[3]['values'],[{'text':'slayer'}])
        refs = [{'value_index':0,'path':[1,0],'type':'obj','id':42}]
        value = parsed_values('dbrows','data',['col0,old_sword,10'],refs,snapshot)[0]
        self.assertEqual(value['values'][0],{'type':'items','id':42,'text':'old_sword'})
        self.assertEqual(value['values'][-1],{'text':'10'})
        # Identical text in an earlier string column must not steal a later reference.
        refs[0]['path'] = [1,1]
        value = parsed_values('dbrows','data',['col0,old_sword,old_sword'],refs,snapshot)[0]
        self.assertEqual(value['values'][0],{'text':'old_sword'})
        self.assertEqual(value['values'][-1],{'type':'items','id':42,'text':'old_sword'})

    def test_parsed_values_do_not_invent_links_without_reference_metadata(self):
        value = parsed_values('invs','stock1',['old_sword,10'],[],{'fields':{}})[0]
        self.assertEqual(value['values'][0],{'text':'old_sword'})
        self.assertIsNone(parsed_values('items','name',None,[],{}))
        self.assertEqual(parsed_values('items','name',['','null','"Quoted, name"'],[],{}),
                         [{'text':''},{'text':'null'},{'text':'Quoted, name'}])
