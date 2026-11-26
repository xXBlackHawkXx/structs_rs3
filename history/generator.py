"""Generate JSON revision comparisons from rs3-dumps. Python 3.11+."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .normalization import ReferenceIndex, normalized_changes, export_id
from .asset_names import decode_asset_names

HERE = Path(__file__).resolve().parents[1]
REPOSITORY = "Joshua-F/rs3-dumps"
API = f"https://api.github.com/repos/{REPOSITORY}"
CACHE_TITLE = re.compile(r"^(\d{4}-\d{2}-\d{2})[a-z]?-rev([\w.]+)$")
HEADER = re.compile(r"//\s*(\d+(?::\d+)?)\s*$")
SECTION = re.compile(r"\[([^\[\]]*)\]$")
NAME_FIELDS = ("name", "text", "phrase", "desc")
EXCLUDED_TYPES = frozenset({
    "varn", "varglobal", "varcon", "controller", "gamelogevent",
    "flo", "apievent", "particleemitter", "stylesheet", "varc", "worldarea", "area", "interface",
})
EMPTY_BASELINE = {
    "sha": "", "title": "Empty baseline (no preceding snapshot available)",
    "date": None, "revision": None, "parent": None, "archive": None,
}


class CachePagesError(RuntimeError):
    """An actionable error for the command line."""


@dataclass(frozen=True)
class Revision:
    sha: str
    title: str
    date: str
    revision: str
    parent: str | None = None
    archive: str | None = None

    @property
    def report_filename(self) -> str:
        suffix = self.title.split("-rev", 1)[0][10:]
        return f"{self.date}-rev{self.revision}{'-' + suffix if suffix else ''}.json"

    @classmethod
    def from_commit(cls, value: dict) -> Revision | None:
        message = value["commit"]["message"]
        title = message.splitlines()[0]
        match = CACHE_TITLE.fullmatch(title)
        if not match:
            return None
        archive = re.search(r"https://archive\.openrs2\.org/caches/runescape/\d+", message)
        parents = value.get("parents", [])
        return cls(value["sha"], title, match[1], match[2],
                   parents[0]["sha"] if parents else None,
                   archive[0] if archive else None)


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha: str
    size: int


@dataclass(frozen=True)
class Record:
    id: str
    symbol: str
    body: str
    source: str

    def fields(self) -> dict[str, tuple[str, ...]]:
        fields = defaultdict(list)
        for line in self.body.splitlines():
            key, value = line.split("=", 1)
            # Parameters and enum entries have their own identities. This avoids
            # reporting an entire enum/parameter list when only one entry changes.
            if key in {"param", "val"} and "," in value:
                subkey, value = value.split(",", 1)
                key = f"{key}[{subkey}]"
            fields[key].append(value)
        return {k: tuple(v) for k, v in fields.items()}

    def name(self) -> str:
        fields = self.fields()
        return next((fields[k][-1] for k in NAME_FIELDS if fields.get(k)), "")


def parse_dump(lines: Iterable[str], source: str) -> dict[str, Record]:
    """Read numeric IDs (or interface:component IDs), retaining repeated keys."""
    result = {}
    pending = None
    current = None
    symbol = ""
    body = []

    def finish():
        if current is not None:
            if current in result:
                raise CachePagesError(f"{source}: duplicate ID {current}")
            result[current] = Record(current, symbol, "\n".join(body), source)

    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        match = HEADER.fullmatch(line)
        if match:
            if pending is not None:
                raise CachePagesError(f"{source}:{number}: ID {pending} has no section")
            finish()
            current, pending, body = None, match[1], []
        elif line.startswith("//"):
            continue
        elif SECTION.fullmatch(line):
            if pending is None:
                raise CachePagesError(f"{source}:{number}: section has no numeric ID")
            current, pending, symbol = pending, None, line[1:-1]
        elif current is not None and "=" in line and line.split("=", 1)[0]:
            body.append(line)
        else:
            raise CachePagesError(f"{source}:{number}: invalid dump line: {line[:100]}")
    if pending is not None:
        raise CachePagesError(f"{source}: ID {pending} has no section")
    finish()
    return result


def id_key(value: str) -> tuple[int, ...]:
    return tuple(int(n) for n in value.split(":"))


def record_data(record: Record) -> dict:
    """Export complete records with their original decoded field values."""
    fields = defaultdict(list)
    for line in record.body.splitlines():
        key, value = line.split("=", 1)
        fields[key].append(value)
    return {"id": export_id(record.id), "config_name": record.symbol,
            "name": record.name() or None, "source": record.source, "fields": dict(fields)}


def compare_records(kind: str, old: dict[str, Record], new: dict[str, Record],
                    old_index: ReferenceIndex, new_index: ReferenceIndex) -> tuple[dict, dict]:
    """Build deterministic JSON changes and counts for one config type."""
    data = {
        "added": [record_data(new[key]) for key in sorted(new.keys() - old.keys(), key=id_key)],
        "removed": [record_data(old[key]) for key in sorted(old.keys() - new.keys(), key=id_key)],
        "modified": [],
    }
    fields_changed = 0
    for key in sorted(old.keys() & new.keys(), key=id_key):
        fields = normalized_changes(old[key], new[key], kind, old_index, new_index)
        if fields:
            data["modified"].append({"id": export_id(key), "before": record_data(old[key]),
                                     "after": record_data(new[key]), "fields": fields})
            fields_changed += len(fields)
    summary = {"new": len(data["added"]), "removed": len(data["removed"]),
               "changed": len(data["modified"]), "fields_changed": fields_changed}
    return data, summary


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


class GitHubSource:
    def __init__(self, cache: Path, *, refresh_history: bool = False):
        self.cache = cache
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.blob_locks: dict[str, threading.Lock] = {}
        self.refresh_history = refresh_history
        self._history: list[Revision] | None = None

    def request(self, url: str, *, api: bool = False, allow_missing: bool = False) -> bytes | None:
        headers = {"User-Agent": "CachePages/2.0", "Accept": "application/vnd.github+json" if api else "*/*"}
        if api and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=headers), timeout=60) as response:
                    return response.read()
            except HTTPError as exc:
                if allow_missing and exc.code == 404:
                    return None
                if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                hint = " Set GITHUB_TOKEN to increase the API rate limit." if exc.code in {403, 429} else ""
                raise CachePagesError(f"Download failed (HTTP {exc.code}): {url}.{hint}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise CachePagesError(f"Download failed: {url}: {exc}") from exc
        raise AssertionError("unreachable")

    def api(self, suffix: str):
        # Commit/tree objects are immutable. Branches and history are refreshed.
        immutable = bool(re.fullmatch(r"/(?:commits|git/trees)/[0-9a-f]{40}", suffix))
        path = self.cache / "api" / (hashlib.sha256(suffix.encode()).hexdigest() + ".json")
        if immutable and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        result = json.loads(self.request(API + suffix, api=True))
        if immutable:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(result, handle)
            temporary.replace(path)
        return result

    def history(self):
        if self._history is not None:
            yield from self._history
            return
        path = self.cache / "history.json"
        cached = None
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if cached.get("version") != 2 or not cached.get("complete"):
                    cached = None
                else:
                    cached_revisions = [Revision(**entry) for entry in cached["revisions"]]
                    cached["saved_at"] = float(cached["saved_at"])
            except (ValueError, TypeError, KeyError, AttributeError):
                cached = None
        if cached is not None and not self.refresh_history and 0 <= time.time() - cached["saved_at"] < 3600:
            self._history = cached_revisions
            yield from self._history
            return
        revisions = []
        page = 1
        try:
            while True:
                commits = self.api(f"/commits?per_page=100&page={page}")
                for commit in commits:
                    revision = Revision.from_commit(commit)
                    if revision:
                        revisions.append(revision)
                if len(commits) < 100:
                    break
                page += 1
        except CachePagesError:
            if cached is None or self.refresh_history:
                raise
            print("Warning: GitHub history refresh failed; using cached history. "
                  "Newer updates may be missing.", file=sys.stderr)
            self._history = cached_revisions
            yield from self._history
            return
        # Save only complete snapshots; never mix cached pagination with a new
        # head, since added commits shift page boundaries.
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"version": 2, "complete": True, "saved_at": time.time(),
                       "revisions": [asdict(revision) for revision in revisions]}, handle)
        temporary.replace(path)
        self._history = revisions
        yield from self._history

    def resolve(self, selector: str) -> Revision:
        if selector == "latest":
            result = next(self.history(), None)
            if result:
                return result
            raise CachePagesError("No cache revisions found in repository history")
        is_date = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", selector))
        is_title = bool(CACHE_TITLE.fullmatch(selector))
        is_revision = bool(re.fullmatch(r"(?:rev)?\d+(?:\.\d+)?", selector))
        if is_date or is_title or is_revision:
            matches = []
            for revision in self.history():
                if ((is_date and revision.date == selector) or
                    (is_title and revision.title == selector) or
                    (is_revision and revision.revision == selector.removeprefix("rev"))):
                    matches.append(revision)
                    if len(matches) == 2:
                        break
            if len(matches) > 1:
                raise CachePagesError(f"Ambiguous revision '{selector}': {matches[0].title}, "
                                      f"{matches[1].title}. Use a commit SHA or a unique dated title.")
            if matches:
                return matches[0]
            raise CachePagesError(f"No cache revision matches '{selector}'")
        commit = self.api("/commits/" + quote(selector, safe=""))
        revision = Revision.from_commit(commit)
        if revision is None:
            raise CachePagesError(f"'{selector}' is not a dated cache commit; choose one with 'list'")
        return revision

    def predecessor(self, revision: Revision) -> Revision | None:
        parent = revision.parent
        while parent:
            commit = self.api("/commits/" + parent)
            result = Revision.from_commit(commit)
            if result:
                return result
            parents = commit.get("parents", [])
            parent = parents[0]["sha"] if parents else None
        return None

    def catalog(self, revision: Revision) -> dict[str, FileEntry]:
        commit = self.api("/commits/" + revision.sha)
        root = self.api("/git/trees/" + commit["commit"]["tree"]["sha"])
        result = {}
        for entry in root["tree"]:
            if entry["type"] != "tree" or entry["path"] != "config":
                continue
            tree = self.api("/git/trees/" + entry["sha"])
            if tree.get("truncated"):
                raise CachePagesError(f"Truncated Git tree for {entry['path']}")
            for file in tree["tree"]:
                if file["type"] != "blob":
                    continue
                name = file["path"]
                if name.startswith("dump."):
                    path = entry["path"] + "/" + name
                    result[path] = FileEntry(path, file["sha"], file["size"])
        if not any(p.startswith("config/") for p in result):
            raise CachePagesError(f"No config dumps found for {revision.title}")
        return result

    def symbol_catalog(self, revision: Revision) -> dict[str, FileEntry]:
        commit = self.api("/commits/" + revision.sha)
        root = self.api("/git/trees/" + commit["commit"]["tree"]["sha"])
        directory = next((entry for entry in root["tree"] if entry["path"] == "symbols" and entry["type"] == "tree"), None)
        if directory is None:
            return {}
        tree = self.api("/git/trees/" + directory["sha"])
        if tree.get("truncated"):
            raise CachePagesError("Truncated Git tree for symbols")
        return {"symbols/" + entry["path"]: FileEntry("symbols/" + entry["path"], entry["sha"], entry["size"])
                for entry in tree["tree"] if entry["type"] == "blob" and entry["path"].endswith(".sym")}

    def asset_names(self, revision: Revision, group: int) -> tuple[list[tuple[str, str]], dict | None]:
        if revision.archive is None:
            return [], None
        cache_id = revision.archive.rsplit("/", 1)[1]
        url = revision.archive + f"/archives/67/groups/{group}.dat"
        path = self.cache / "assetnames" / f"{cache_id}-67-{group}.dat"
        metadata_path = path.with_suffix(".json")
        data, metadata = None, None
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("missing"):
                return [], metadata
            if path.exists():
                cached = path.read_bytes()
                if hashlib.sha256(cached).hexdigest() == metadata.get("sha256"):
                    data = cached
        if data is None:
            data = self.request(url, allow_missing=True)
            metadata = {"url": url, "path": f"assetnames/{path.name}", "missing": data is None}
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is not None:
                metadata.update({"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                path.write_bytes(data)
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return (decode_asset_names(data) if data is not None else []), metadata

    def download(self, revision: Revision, entry: FileEntry) -> Path:
        lock = self.blob_locks.setdefault(entry.sha, threading.Lock())
        with lock:
            return self._download(revision, entry)

    def _download(self, revision: Revision, entry: FileEntry) -> Path:
        path = self.cache / "blobs" / entry.sha
        if path.exists():
            data = path.read_bytes()
            if len(data) == entry.size and blob_hash(data) == entry.sha:
                return path
        data = self.request(f"https://raw.githubusercontent.com/{REPOSITORY}/{revision.sha}/" + quote(entry.path, safe="/"))
        if len(data) != entry.size or blob_hash(data) != entry.sha:
            raise CachePagesError(f"Integrity check failed: {revision.title}/{entry.path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        return path


def local_catalog(directory: Path) -> tuple[Path, dict[str, FileEntry]]:
    root = directory.resolve()
    # Accept either a checkout root, or a directory of dump.* files.
    config = root / "config" if (root / "config").is_dir() else root
    paths = list(config.glob("dump.*"))
    if not paths:
        raise CachePagesError(f"No dump.* files in {config}")
    result = {}
    for path in paths:
        if path.is_file():
            data = path.read_bytes()
            key = "config/" + path.name
            result[key] = FileEntry(key, blob_hash(data), len(data))
    return root, result


def local_path(root: Path, entry: FileEntry) -> Path:
    direct = root / entry.path
    return direct if direct.exists() else root / Path(entry.path).name


def kind_of(path: str) -> str:
    return path.split("dump.", 1)[1]


def read_records(paths: list[tuple[str, Path]]) -> dict[str, Record]:
    records = {}
    for source, path in paths:
        with path.open(encoding="utf-8-sig") as handle:
            parsed = parse_dump(handle, source)
        duplicate = records.keys() & parsed.keys()
        if duplicate:
            key = min(duplicate, key=id_key)
            raise CachePagesError(f"Duplicate ID {key} in {records[key].source} and {source}")
        records.update(parsed)
    return records


def prepare_reference_index(source: GitHubSource, revision: Revision, catalog: dict[str, FileEntry],
                            local_root: Path | None = None) -> tuple[ReferenceIndex, list[dict]]:
    index, inputs = ReferenceIndex(), []
    if local_root is None:
        symbols = source.symbol_catalog(revision)
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [(entry, pool.submit(source.download, revision, entry)) for entry in symbols.values()]
            for entry, future in futures:
                index.load_symbols(future.result(), Path(entry.path).stem)
                inputs.append(asdict(entry))
        for group, kind in [(32, "material"), (90, "fontmetrics")]:
            names, asset_source = source.asset_names(revision, group)
            for identifier, name in names:
                index.add(kind, identifier, name)
            if asset_source:
                inputs.append(asset_source)
    else:
        directory = local_root / "symbols"
        if not directory.is_dir() and local_root.name == "config":
            directory = local_root.parent / "symbols"
        for path in sorted(directory.glob("*.sym")):
            data = path.read_bytes()
            index.load_symbols(path, path.stem)
            inputs.append(asdict(FileEntry("symbols/" + path.name, blob_hash(data), len(data))))
    # Types without .sym files still have stable numeric IDs in dump headers.
    # This also supports offline snapshots containing only config dumps.
    for entry in sorted(catalog.values(), key=lambda entry: entry.path):
        if not entry.path.startswith("config/"):
            continue
        kind = kind_of(entry.path)
        if index.names.get(index.kind(kind)):
            continue
        path = source.download(revision, entry) if local_root is None else local_path(local_root, entry)
        index.load_config(path, kind)
        inputs.append(asdict(entry))
    return index, inputs


def generate(args) -> Path:
    if args.output is not None and args.output.suffix.lower() != ".json":
        raise CachePagesError("--output must have a .json suffix")
    source = GitHubSource(args.cache_dir, refresh_history=args.refresh_history)
    local = args.old_dir is not None or args.new_dir is not None
    if local:
        if args.old_dir is None or args.new_dir is None or not args.date or not args.revision:
            raise CachePagesError("Local mode requires --old-dir, --new-dir, --date and --revision")
        if args.target != "latest" or args.base:
            raise CachePagesError("--target/--base cannot be combined with local directories")
        before = Revision("", "Local previous dump", "", "")
        after = Revision("", f"{args.date}-rev{args.revision}", args.date, args.revision)
        old_root, old_catalog = local_catalog(args.old_dir)
        new_root, new_catalog = local_catalog(args.new_dir)
    else:
        if args.date or args.revision:
            raise CachePagesError("--date and --revision are only for local directory mode")
        after = source.resolve(args.target)
        before = source.resolve(args.base) if args.base else source.predecessor(after)
        if before is not None and before.sha == after.sha:
            raise CachePagesError("Base and target are the same commit")
        print(f"Comparing {before.title if before else EMPTY_BASELINE['title']} -> {after.title}", flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            old_future = pool.submit(source.catalog, before) if before is not None else None
            new_future = pool.submit(source.catalog, after)
            old_catalog = old_future.result() if old_future is not None else {}
            new_catalog = new_future.result()
    all_paths = {p for p in old_catalog.keys() | new_catalog.keys() if kind_of(p) not in EXCLUDED_TYPES}
    available = {kind_of(p) for p in all_paths}
    if args.types:
        excluded = set(args.types) & EXCLUDED_TYPES
        if excluded:
            raise CachePagesError("Types excluded from output: " + ", ".join(sorted(excluded)))
        unknown = set(args.types) - available
        if unknown:
            raise CachePagesError("Types unavailable in either input: " + ", ".join(sorted(unknown)))
        all_paths = {p for p in all_paths if kind_of(p) in args.types}
    print("Loading revision-specific reference identities", flush=True)
    old_index, old_reference_inputs = (
        prepare_reference_index(source, before, old_catalog, old_root if local else None)
        if before is not None else (ReferenceIndex(), [])
    )
    new_index, new_reference_inputs = prepare_reference_index(source, after, new_catalog, new_root if local else None)
    remapped = any(identifier != new_index.names.get(kind, {}).get(name, identifier)
                   for kind, names in old_index.names.items() for name, identifier in names.items()
                   if name in new_index.names.get(kind, {}))
    grouped = defaultdict(list)
    for path in sorted(all_paths):
        grouped[kind_of(path)].append(path)
    summaries, files, change_data = {}, [], {}
    for kind in sorted(grouped):
        changed_paths = [p for p in grouped[kind] if remapped or old_catalog.get(p) != new_catalog.get(p)]
        # File entries include path, blob hash and size. Identical blobs need no parsing.
        old_inputs, new_inputs = [], []
        downloads = []
        print(f"{kind}: {len(changed_paths)} changed dump file(s)", flush=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for path in changed_paths:
                for catalog, rev, inputs, root in [
                    (old_catalog, before, old_inputs, old_root if local else None),
                    (new_catalog, after, new_inputs, new_root if local else None),
                ]:
                    if path not in catalog:
                        continue
                    entry = catalog[path]
                    files.append({"side": "before" if rev is before else "after", **asdict(entry)})
                    if local:
                        inputs.append((path, local_path(root, entry)))
                    else:
                        downloads.append((path, inputs, pool.submit(source.download, rev, entry)))
            for path, inputs, future in downloads:
                inputs.append((path, future.result()))
        old = read_records(old_inputs)
        new = read_records(new_inputs)
        type_changes, summary = compare_records(kind, old, new, old_index, new_index)
        summaries[kind] = summary
        if any(summary.values()):
            change_data[kind] = type_changes
        print(f"{kind}: {summary['new']:,} new, {summary['removed']:,} removed, "
              f"{summary['changed']:,} changed records ({summary['fields_changed']:,} changed fields)", flush=True)
        del old, new
    output = args.output or HERE / ".cache" / "reports" / after.report_filename
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps({
        "schema_version": 2,
        "tool": "CachePages/2.0", "before": asdict(before) if before is not None else EMPTY_BASELINE,
        "after": asdict(after),
        **({"comparison_kind": "initial_snapshot"} if before is None else {}),
        "coverage": {"types": list(summaries), "interfaces": False,
                     "excluded_types": sorted(EXCLUDED_TYPES)},
        "summary": summaries, "changes": change_data, "compared_files": files,
        "normalization": {"policy": "typed-reference-ids-v1", "ignored_record_name_changes": new_index.stats["ignored_record_names"],
                          "ignored_reference_field_changes": new_index.stats["ignored_reference_fields"],
                          "symbol_reassignments": remapped, "before_inputs": old_reference_inputs, "after_inputs": new_reference_inputs},
        "unchanged_files": sorted(p for p in all_paths if old_catalog.get(p) == new_catalog.get(p)),
        "unchanged_blobs": {p: asdict(old_catalog[p]) for p in sorted(all_paths)
                            if old_catalog.get(p) == new_catalog.get(p)},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(output)
    print(f"Wrote {output} ({output.stat().st_size:,} bytes)")
    return output


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return result


def valid_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def valid_revision(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.]+", value) or value in {".", ".."}:
        raise argparse.ArgumentTypeError("expected a revision number such as 951 or 951.1")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List dated dump commits, newest first")
    listing.add_argument("--limit", type=positive_int, default=20)
    listing.add_argument("--cache-dir", type=Path, default=HERE / ".cache" / "comparisons")
    listing.add_argument("--refresh-history", action="store_true", help="Refresh the cached revision list from GitHub")
    build = commands.add_parser("generate", help="Write a JSON cache comparison")
    build.add_argument("--target", default="latest", help="Date, dated title, commit, branch or unique revision")
    build.add_argument("--base", help="Comparison commit/date; defaults to preceding dump on first-parent history")
    build.add_argument("--cache-dir", type=Path, default=HERE / ".cache" / "comparisons")
    build.add_argument("--refresh-history", action="store_true", help="Refresh the cached revision list from GitHub")
    build.add_argument("--output", type=Path, help="Output JSON file (default: .cache/reports/DATE-revREV.json)")
    build.add_argument("--types", nargs="+", help="Dump suffixes to include, e.g. obj npc loc struct")
    build.add_argument("--old-dir", type=Path, help="Local previous checkout root or config directory")
    build.add_argument("--new-dir", type=Path, help="Local current checkout root or config directory")
    build.add_argument("--date", type=valid_date, help="Cache date for local mode, YYYY-MM-DD")
    build.add_argument("--revision", type=valid_revision, help="Cache revision for local mode")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            print("Date        Revision  Commit                                    Dump")
            for index, rev in enumerate(GitHubSource(args.cache_dir, refresh_history=args.refresh_history).history(), 1):
                print(f"{rev.date}  {rev.revision:<8}  {rev.sha}  {rev.title}")
                if index >= args.limit:
                    break
        else:
            generate(args)
        return 0
    except (CachePagesError, OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
