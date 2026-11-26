"""Import CachePages schema-v2 comparisons and build per-config history chunks."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 64


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)


def comparison_key(report):
    return tuple(report[side].get('sha') or report[side].get('title') for side in ('before','after'))


def report_order(report):
    return (report['after'].get('date') or '',report['after'].get('title') or '',report['after'].get('sha') or '')


def load_manifest(history_dir):
    path = history_dir / 'manifest.json'
    if not path.exists():
        return {'schema_version':1,'reports':[]}
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported imported history manifest version')
    keys = [comparison_key(report) for report in manifest['reports']]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate history comparison in manifest')
    return manifest


def history_digest(history_dir):
    path = history_dir / 'manifest.json'
    return hashlib.sha256(path.read_bytes() if path.exists() else b'').hexdigest()


def snapshot_metadata(value):
    result = {key:value.get(key) for key in ('sha','title','date','revision','archive')}
    if result['date'] is not None:
        date.fromisoformat(result['date'])
    return result


def record_id(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f'History config ID must be a non-negative integer: {value!r}')
    return value


def compact_record(record, kind, page):
    from .history_values import parsed_values
    identifier = record_id(record['id'])
    if kind == 'modified':
        before, after = record['before'], record['after']
        fields = []
        for original in record['fields']:
            field = dict(original)
            key = field.get('identity',{}).get('field',field['field'])
            for side, snapshot in (('before',before),('after',after)):
                field[side + '_parsed'] = parsed_values(page,key,field[side],field.get(side + '_references',[]),snapshot,field.get(side + '_field') or field['field'])
            fields.append(field)
        return {'id':identifier, 'before_name':before.get('config_name'), 'after_name':after.get('config_name'),
                'fields':fields}
    fields = record['fields']
    return {'id':identifier, 'name':record.get('config_name'), 'fields':fields,
            'parsed_fields':{key:parsed_values(page,key,values,[],record) for key,values in fields.items()}}


def import_report_files(paths, output_dir, pages):
    """Merge comparisons atomically; a partial import must retain previous history."""
    by_kind = {kind:page for page,kind in pages.items()}
    retained = {comparison_key(report):report for report in load_manifest(output_dir)['reports']}
    imported = set()
    for path in paths:
        raw = path.read_bytes()
        report = json.loads(raw)
        if report.get('schema_version') != 2:
            raise ValueError(f'Expected CachePages schema_version 2: {path.name}')
        before, after = snapshot_metadata(report['before']), snapshot_metadata(report['after'])
        if not after['date']:
            raise ValueError(f'History report has no target date: {path.name}')
        changes = {}
        for kind, groups in report['changes'].items():
            if kind not in by_kind:
                continue
            selected, seen = {}, set()
            for status in ('added','removed','modified'):
                values = []
                for record in groups.get(status, []):
                    value = compact_record(record, status, by_kind[kind])
                    if value['id'] in seen:
                        raise ValueError(f'Duplicate {kind} ID {value["id"]} in {path.name}')
                    seen.add(value['id']); values.append(value)
                if values:
                    selected[status] = values
            if selected:
                changes[by_kind[kind]] = selected
        covered = sorted({by_kind[kind] for kind in report.get('coverage',{}).get('types',[]) if kind in by_kind} | set(changes))
        payload = {'schema_version':1, 'before':before, 'after':after, 'types':covered, 'changes':changes}
        if report.get('comparison_kind'):
            payload['comparison_kind'] = report['comparison_kind']
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        compressed = gzip.compress(encoded, compresslevel=6, mtime=0)
        key = comparison_key(payload)
        if key in imported:
            raise ValueError(f'Duplicate history comparison: {path.name}')
        imported.add(key)
        checksum = hashlib.sha256(compressed).hexdigest()
        previous = retained.get(key)
        # Changed content gets a new filename so the old manifest stays valid on failure.
        filename = previous['file'] if previous and previous['sha256'] == checksum else f'{after["date"]}-rev{after["revision"]}-{checksum}.json.gz'
        if Path(filename).name != filename:
            raise ValueError(f'Invalid history report path: {filename}')
        destination = output_dir / 'reports' / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != compressed:
            temporary = destination.with_name(destination.name + '.tmp')
            temporary.write_bytes(compressed)
            temporary.replace(destination)
        descriptor = {'file':filename, 'sha256':checksum,
                        'source_file':path.name, 'source_sha256':hashlib.sha256(raw).hexdigest(),
                        'before':before, 'after':after,
                        'events':sum(len(values) for groups in changes.values() for values in groups.values())}
        if report.get('comparison_kind'):
            descriptor['comparison_kind'] = report['comparison_kind']
        retained[key] = descriptor
    if not imported:
        raise ValueError('No dated CachePages JSON reports supplied')
    reports = sorted(retained.values(),key=report_order)
    write_json(output_dir / 'manifest.json', {'schema_version':1, 'reports':reports})
    return reports


def import_reports(input_dir, output_dir, pages):
    paths = [path for path in sorted(input_dir.glob('*.json'))
             if re.fullmatch(r'\d{4}-\d{2}-\d{2}-rev[^/\\]+\.json',path.name)]
    return import_report_files(paths,output_dir,pages)


def prepare_history(history_dir, output_dir, pages, type_pages, revision=None):
    """Expand the compact tracked inputs into the generated site's data format."""
    source_manifest = history_dir / 'manifest.json'
    if not source_manifest.exists():
        return None
    manifest = load_manifest(history_dir)
    selected = sorted(manifest['reports'],key=report_order)
    # A build pinned to a known older snapshot must not show later events.
    positions = [index for index,report in enumerate(selected) if revision and report['after'].get('sha') == revision]
    if positions:
        selected = selected[:max(positions) + 1]
    elif revision:
        positions = [index for index,report in enumerate(selected) if report['before'].get('sha') == revision]
        if positions:
            selected = selected[:min(positions)]
    if not selected:
        return None
    # An empty filename creates a temporary disk database, removed when closed.
    with closing(sqlite3.connect('')) as database:
        return expand_history(database,selected,history_dir,output_dir,pages,type_pages)


def expand_history(database, selected, history_dir, output_dir, pages, type_pages):
    database.execute('PRAGMA journal_mode=OFF')
    database.execute('PRAGMA synchronous=OFF')
    database.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, page TEXT, chunk INTEGER, id INTEGER, name TEXT, payload TEXT)')
    reports, covered = [], set()
    seen_comparisons = set()
    for descriptor in selected:
        filename = descriptor['file']
        if Path(filename).name != filename or not filename.endswith('.json.gz'):
            raise ValueError(f'Invalid history report path: {filename}')
        compressed = (history_dir / 'reports' / filename).read_bytes()
        if hashlib.sha256(compressed).hexdigest() != descriptor['sha256']:
            raise ValueError(f'History report checksum mismatch: {filename}')
        report = json.loads(gzip.decompress(compressed))
        if report.get('schema_version') != 1:
            raise ValueError(f'Unsupported history report version: {filename}')
        if report['before'] != descriptor['before'] or report['after'] != descriptor['after']:
            raise ValueError(f'History report metadata mismatch: {filename}')
        pair = (report['before'].get('sha') or report['before'].get('title'),report['after'].get('sha') or report['after'].get('title'))
        if pair in seen_comparisons:
            raise ValueError(f'Duplicate history comparison: {filename}')
        seen_comparisons.add(pair)
        report_number = len(reports)
        reports.append({key:descriptor[key] for key in ('source_file','source_sha256','before','after')})
        covered.update(page for page in report['types'] if page in pages)
        for page, groups in report['changes'].items():
            if page not in pages:
                continue
            for status, records in groups.items():
                if status not in ('added','removed','modified'):
                    raise ValueError(f'Unsupported history event: {status}')
                for record in records:
                    identifier = record_id(record['id'])
                    name = record.get('after_name') or record.get('before_name') or record.get('name') or ''
                    if status == 'modified':
                        fields = record['fields']
                    else:
                        fields = [{'field':key, 'identity':{'field':key},
                                   'before_field':key if status == 'removed' else None,
                                   'after_field':key if status == 'added' else None,
                                   'before':value if status == 'removed' else None,
                                   'after':value if status == 'added' else None,
                                   'before_parsed':record.get('parsed_fields',{}).get(key) if status == 'removed' else None,
                                   'after_parsed':record.get('parsed_fields',{}).get(key) if status == 'added' else None}
                                  for key,value in record['fields'].items()]
                    event = {'report':report_number,'kind':status,'fields':fields}
                    database.execute('INSERT INTO events (page,chunk,id,name,payload) VALUES (?,?,?,?,?)',
                                     (page,identifier // CHUNK_SIZE,identifier,name,json.dumps(event,ensure_ascii=False,separators=(',',':'))))
        database.commit()
    database.execute('CREATE INDEX event_chunks ON events (page,chunk,id,seq)')
    chunks, counts = {}, {}
    for page, number in database.execute('SELECT DISTINCT page,chunk FROM events ORDER BY page,chunk'):
        chunk = {}
        for identifier, name, payload in database.execute('SELECT id,name,payload FROM events WHERE page=? AND chunk=? ORDER BY id,seq',(page,number)):
            entry = chunk.setdefault(str(identifier),{'id':identifier,'name':'','events':[]})
            entry['name'] = name or entry['name']
            entry['events'].append(json.loads(payload))
        chunks.setdefault(page,[]).append(number)
        counts[page] = counts.get(page,0) + len(chunk)
        write_json(output_dir / 'data' / 'history' / page / f'{number}.json',chunk)
    dates = [side['date'] for report in reports for side in (report['before'],report['after']) if side.get('date')]
    return {'chunkSize':CHUNK_SIZE,'chunks':chunks,'counts':counts,'types':sorted(covered),
            'reports':reports,'from':min(dates) if dates else None,'through':max(dates) if dates else None,
            'typePages':type_pages}


def main():
    from .build import FILES
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='CachePages/output directory (read only)')
    parser.add_argument('--output', type=Path, default=ROOT / 'history', help='Compact history source directory')
    args = parser.parse_args()
    reports = import_reports(args.input, args.output, FILES)
    print(f'Imported {len(reports)} reports and {sum(report["events"] for report in reports):,} config events into {args.output}')


if __name__ == '__main__':
    main()
