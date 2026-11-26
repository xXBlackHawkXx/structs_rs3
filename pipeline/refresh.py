"""Generate missing adjacent comparisons and select one immutable build revision."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import quote
from urllib.request import urlopen

from builder.build import FILES
from builder.history import comparison_key, history_digest, import_report_files, load_manifest, write_json
from history.generator import CACHE_TITLE, CachePagesError, GitHubSource, Revision, generate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / '.cache' / 'pipeline' / 'state.json'


def resolve_target(source, ref):
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',ref or '') or CACHE_TITLE.fullmatch(ref or ''):
        return source.resolve(ref)
    if not ref or ref == 'latest':
        ref = 'master'
    commit = source.api('/commits/' + quote(ref,safe=''))
    # A symbol-only maintenance commit is not a new cache snapshot.
    while True:
        revision = Revision.from_commit(commit)
        if revision:
            return revision
        parents = commit.get('parents',[])
        if not parents:
            raise CachePagesError(f'No dated cache snapshot found at {ref}')
        commit = source.api('/commits/' + parents[0]['sha'])


def missing_comparisons(source, target, reports):
    known = {comparison_key(report) for report in reports}
    initial = {report['after'].get('sha') for report in reports if not report['before'].get('sha') and not report['before'].get('date')}
    pending, seen = [], set()
    current = target
    while current:
        if current.sha in seen:
            raise CachePagesError('Cycle in dump first-parent history')
        seen.add(current.sha)
        previous = source.predecessor(current)
        # Initial baselines have no commit SHA; their descriptive title is not an identity.
        pair = (previous.sha if previous else None,current.sha)
        if pair in known or previous is None and current.sha in initial:
            break
        pending.append((previous,current))
        current = previous
    return list(reversed(pending))


def source_digest(root=ROOT):
    paths = subprocess.check_output(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard','--','.']).split(b'\0')
    digest = hashlib.sha256()
    for name in sorted(set(paths)):
        if not name:
            continue
        relative = name.decode('utf-8')
        if relative == 'history/manifest.json' or relative.startswith('history/reports/'):
            continue
        path = root / relative
        digest.update(name + b'\0')
        digest.update(path.read_bytes() if path.is_file() else b'<deleted>')
        digest.update(b'\0')
    return digest.hexdigest()


def deployed_manifest(pages_url):
    if not pages_url:
        return None
    if not pages_url.startswith('https://'):
        raise ValueError('Pages URL must use HTTPS')
    try:
        # Revalidate so an intermediary cache cannot hide a newer deployment.
        from urllib.request import Request
        request = Request(pages_url.rstrip('/') + '/data/manifest.json',headers={'Cache-Control':'no-cache','User-Agent':'rs3-viewer-pipeline/1.0'})
        with urlopen(request,timeout=30) as response:
            value = json.load(response)
        return value if isinstance(value,dict) else None
    except (OSError,ValueError) as exc:
        print(f'Could not read the deployed manifest; a build will be required: {exc}')
        return None


def needs_build(state, deployed, force=False):
    return bool(force or not deployed or deployed.get('revision') != state['revision']
                or deployed.get('pipeline') != {key:state[key] for key in ('source_digest','history_digest')})


def refresh(ref='master', history_dir=ROOT / 'history', cache_dir=ROOT / '.cache' / 'comparisons',
            pages_url=None, force=False, source=None, generator=generate, code_digest=None):
    history_dir, cache_dir = Path(history_dir), Path(cache_dir)
    source = source or GitHubSource(cache_dir)
    target = resolve_target(source,ref)
    reports = load_manifest(history_dir)['reports']
    pending = missing_comparisons(source,target,reports)
    before_digest = history_digest(history_dir)
    print(f'Target: {target.title} ({target.sha}); {len(pending)} missing comparison(s)',flush=True)
    scratch = cache_dir.resolve().parent / 'reports'
    scratch.mkdir(parents=True,exist_ok=True)
    if pending:
        # All raw reports are temporary; only compact, validated inputs are retained.
        with tempfile.TemporaryDirectory(prefix='refresh-',dir=scratch) as directory:
            paths = []
            for previous, current in pending:
                path = Path(directory) / f'{current.date}-rev{current.revision}-{current.sha}.json'
                args = argparse.Namespace(target=current.sha,base=previous.sha if previous else None,
                    cache_dir=cache_dir,refresh_history=False,output=path,types=None,
                    old_dir=None,new_dir=None,date=None,revision=None)
                generated = Path(generator(args))
                report = json.loads(generated.read_text(encoding='utf-8'))
                if report['after']['sha'] != current.sha or (report['before'].get('sha') or None) != (previous.sha if previous else None):
                    raise ValueError('Generated comparison does not match the planned commits')
                paths.append(generated)
            import_report_files(paths,history_dir,FILES)
    state = {'revision':target.sha,'title':target.title,
             'source_digest':code_digest if code_digest is not None else source_digest(),
             'history_digest':history_digest(history_dir)}
    state['history_changed'] = before_digest != state['history_digest']
    state['build'] = needs_build(state,deployed_manifest(pages_url),force)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='master',help='Dated dump, branch, tag or commit (default: master)')
    parser.add_argument('--history-dir',type=Path,default=ROOT / 'history')
    parser.add_argument('--cache-dir',type=Path,default=ROOT / '.cache' / 'comparisons')
    parser.add_argument('--pages-url',help='Live Pages URL used to skip builds that are already deployed')
    parser.add_argument('--force',action='store_true',help='Build even when the deployed manifest is current')
    parser.add_argument('--state',type=Path,default=DEFAULT_STATE)
    parser.add_argument('--github-output',type=Path)
    args = parser.parse_args()
    state = refresh(args.ref,args.history_dir,args.cache_dir,args.pages_url,args.force)
    if not re.fullmatch(r'[a-f0-9]{40}',state['revision']):
        raise ValueError('Expected an immutable dump commit SHA')
    write_json(args.state,state)
    if args.github_output:
        with args.github_output.open('a',encoding='utf-8') as output:
            for key in ('revision','build','history_changed'):
                value = str(state[key]).lower() if isinstance(state[key],bool) else state[key]
                output.write(f'{key}={value}\n')
    print(f'History changed: {state["history_changed"]}; build required: {state["build"]}; state: {args.state}')


if __name__ == '__main__':
    main()
