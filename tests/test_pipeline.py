import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from builder.build import FILES
from builder.history import history_digest, import_report_files, load_manifest
from history.generator import EMPTY_BASELINE, Revision
from pipeline.refresh import missing_comparisons, needs_build, refresh, resolve_target


REVISIONS = [Revision(char * 40,f'2026-11-{index:02d}-rev951',f'2026-11-{index:02d}','951',
                      chr(ord(char)-1) * 40 if index > 1 else None)
             for index,char in enumerate('abc',1)]


def metadata(revision):
    return vars(revision) if revision else EMPTY_BASELINE


class Source:
    def __init__(self, head=REVISIONS[-1], maintenance=False):
        self.head = head
        self.maintenance = maintenance
        self.visited = []

    def api(self, path):
        identifier = path.removeprefix('/commits/')
        revision = self.head if identifier == 'master' else next(r for r in REVISIONS if r.sha == identifier)
        if identifier == 'master' and self.maintenance:
            return {'sha':'d'*40,'commit':{'message':'Update symbols'},'parents':[{'sha':revision.sha}]}
        return {'sha':revision.sha,'commit':{'message':revision.title},
                'parents':[{'sha':revision.parent}] if revision.parent else []}

    def predecessor(self, revision):
        self.visited.append(revision.sha)
        return next((r for r in REVISIONS if r.sha == revision.parent),None)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history = self.root / 'history'
        self.cache = self.root / 'cache' / 'comparisons'
        self.generated = []

    def report(self, previous, current, path):
        path.parent.mkdir(parents=True,exist_ok=True)
        data = {'schema_version':2,'before':metadata(previous),'after':metadata(current),
                'coverage':{'types':['obj']},'changes':{}}
        if previous is None:
            data['comparison_kind'] = 'initial_snapshot'
        path.write_text(json.dumps(data),encoding='utf-8')
        return path

    def seed(self, previous=None, current=REVISIONS[0]):
        path = self.report(previous,current,self.root / 'seed.json')
        import_report_files([path],self.history,FILES)

    def generator(self, args):
        current = next(r for r in REVISIONS if r.sha == args.target)
        previous = next((r for r in REVISIONS if r.sha == args.base),None)
        self.generated.append((args.base,args.target))
        return self.report(previous,current,args.output)

    def test_backlog_generates_each_adjacent_pair_in_order_and_retains_history(self):
        self.seed()
        with redirect_stdout(io.StringIO()):
            state = refresh(history_dir=self.history,cache_dir=self.cache,source=Source(maintenance=True),
                            generator=self.generator,code_digest='code')
        self.assertEqual(self.generated,[(REVISIONS[0].sha,REVISIONS[1].sha),(REVISIONS[1].sha,REVISIONS[2].sha)])
        self.assertEqual(len(load_manifest(self.history)['reports']),3)
        self.assertEqual(state['revision'],REVISIONS[2].sha)
        self.assertEqual(state['history_digest'],history_digest(self.history))
        self.assertTrue(state['history_changed'])
        self.assertTrue(state['build'])

    def test_current_deployment_skips_but_failed_deployment_retries_without_new_history(self):
        self.seed(REVISIONS[1],REVISIONS[2])
        deployed = {'revision':REVISIONS[2].sha,'pipeline':{'source_digest':'code','history_digest':history_digest(self.history)}}
        with patch('pipeline.refresh.deployed_manifest',return_value=deployed),redirect_stdout(io.StringIO()):
            state = refresh(history_dir=self.history,cache_dir=self.cache,source=Source(),generator=self.generator,code_digest='code')
        self.assertFalse(state['build'])
        self.assertFalse(state['history_changed'])
        self.assertEqual(self.generated,[])
        self.assertTrue(needs_build(state,None))
        self.assertTrue(needs_build(state,{**deployed,'revision':REVISIONS[1].sha}))
        self.assertTrue(needs_build(state,{**deployed,'pipeline':{'source_digest':'old'}}))
        self.assertTrue(needs_build(state,deployed,force=True))

    def test_generation_failure_does_not_replace_retained_manifest(self):
        self.seed()
        original = (self.history / 'manifest.json').read_bytes()
        def fail_second(args):
            if args.target == REVISIONS[2].sha:
                raise RuntimeError('failed download')
            return self.generator(args)
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'failed download'):
            refresh(history_dir=self.history,cache_dir=self.cache,source=Source(),generator=fail_second,code_digest='code')
        self.assertEqual((self.history / 'manifest.json').read_bytes(),original)

    def test_wrong_comparison_commit_is_rejected(self):
        self.seed()
        def wrong(args):
            return self.report(None,REVISIONS[0],args.output)
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,'planned commits'):
            refresh(history_dir=self.history,cache_dir=self.cache,source=Source(),generator=wrong,code_digest='code')
        self.assertEqual(len(load_manifest(self.history)['reports']),1)

    def test_initial_baseline_and_maintenance_selection(self):
        self.seed()
        source = Source(head=REVISIONS[0],maintenance=True)
        self.assertEqual(resolve_target(source,'latest'),REVISIONS[0])
        self.assertEqual(missing_comparisons(source,REVISIONS[0],load_manifest(self.history)['reports']),[])

    def test_source_digest_tracks_code_without_changing_for_history(self):
        from pipeline.refresh import source_digest
        (self.root / 'frontend').mkdir()
        (self.root / 'frontend/app.js').write_text('one')
        self.history.mkdir()
        (self.history / 'manifest.json').write_text('old')
        (self.history / 'generator.py').write_text('generator one')
        (self.history / 'reports').mkdir()
        (self.history / 'reports/report.json.gz').write_bytes(b'old report')
        with patch('pipeline.refresh.subprocess.check_output',return_value=b'frontend/app.js\0history/generator.py\0history/manifest.json\0history/reports/report.json.gz\0'):
            before = source_digest(self.root)
            (self.history / 'manifest.json').write_text('new')
            (self.history / 'reports/report.json.gz').write_bytes(b'new report')
            self.assertEqual(source_digest(self.root),before)
            (self.history / 'generator.py').write_text('generator two')
            self.assertNotEqual(source_digest(self.root),before,'History engine changes must trigger a deployment')
            (self.history / 'generator.py').write_text('generator one')
            (self.root / 'frontend/app.js').write_text('two')
            self.assertNotEqual(source_digest(self.root),before)
