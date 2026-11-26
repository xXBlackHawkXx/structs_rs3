"""Build a static cache browser from Joshua-F/rs3-dumps (Python 3.11+)."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import urllib.request

from .field_types import native_field_type
from .achievement_values import achievement_value
from .quickchat_values import phrase_value
from .extra_configs import PREVIEW_KEYS, native_values
from .history import history_digest, prepare_history

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
REPO = "Joshua-F/rs3-dumps"
FILES = {
    "params": "param", "achievements": "achievement", "dbtables": "dbtable",
    "dbrows": "dbrow", "idkits": "idk", "invs": "inv", "items": "obj",
    "npcs": "npc", "structs": "struct", "enums": "enum", "quests": "quest",
    "varplayerbits": "varbit", "scenery": "loc", "cursors": "cursor",
    "quickchatcategories": "quickchatcat", "quickchatphrases": "quickchatphrase",
    "varplayers": "varp", "mapelements": "mel", "mapsceneicons": "msi", "animationsets": "bas",
    "sequences": "seq", "spoteffects": "spot", "hitsplats": "hitmark", "healthbars": "headbar",
}
PARAM_PAGES = {
    "achievement_params": "achievements", "idkit_params": "idkits",
    "inv_params": "invs", "item_params": "items", "npc_params": "npcs",
    "quest_params": "quests", "varplayerbit_params": "varplayerbits", "scenery_params": "scenery", "cursor_params": "cursors",
}
FIELD_PAGES = frozenset(PARAM_PAGES.values())
TYPE_PAGES = {v: k for k, v in FILES.items()} | {
    "namedobj": "items", "varplayerbit": "varplayerbits", "idkit": "idkits", "object": "scenery",
    "chatcat": "quickchatcategories", "chatphrase": "quickchatphrases",
    "varplayer": "varplayers", "mapelement": "mapelements", "mapsceneicon": "mapsceneicons", "spotanim": "spoteffects",
}
DISPLAY_FIELDS = {"quickchatcategories": "desc", "quickchatphrases": "phrase", "mapelements": "text"}
CHUNK_SIZE = 128
SYMBOL_FILES = {"graphic": "graphic", "category": "category", "stat": "stat", "varplayer": "varp"}


def request(url):
    headers = {
        "User-Agent": "rs3-structs-viewer/1.0", "Accept": "application/vnd.github+json",
    }
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token and url.startswith('https://api.github.com/'):
        headers['Authorization'] = f'Bearer {token}'
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120)


def parse_dump(lines):
    """Numeric // comments identify records; preserve repeated fields and commas."""
    record = None
    pending_id = None
    for raw in lines:
        line = raw.strip()
        match = re.fullmatch(r"//\s*(\d+)", line)
        if match:
            if record is not None:
                yield record
                record = None
            pending_id = int(match[1])
        elif line.startswith("[") and line.endswith("]"):
            if pending_id is None:
                raise ValueError(f"Missing numeric ID before {line}")
            record = {"id": pending_id, "name": line[1:-1], "fields": []}
            pending_id = None
        elif line and not line.startswith("//"):
            if record is None or "=" not in line:
                raise ValueError(f"Invalid dump line: {line[:120]}")
            record["fields"].append(line.split("=", 1))
    if record is not None:
        yield record


def split_values(value):
    """Split config tuples, respecting both quote styles and backslash escapes."""
    parts, start, quote, escaped = [], 0, None, False
    for i, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'" and i == start:
            quote = char
        elif char == ",":
            parts.append(value[start:i])
            start = i + 1
    parts.append(value[start:])
    return parts


def unquote(value):
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1].replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    return value


def field(record, key, default=""):
    return next((v for k, v in record["fields"] if k == key), default)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def compress_json_files(output):
    """Pack generated data for static hosts; the bootstrap manifest stays readable."""
    data = output.resolve() / "data"
    for path in data.rglob("*.json"):
        if path == data / "manifest.json":
            continue
        target = path.with_suffix(".json.gz")
        temporary = target.with_suffix(".gz.part")
        try:
            with path.open("rb") as source, temporary.open("wb") as destination:
                with gzip.GzipFile(filename="", mode="wb", fileobj=destination, compresslevel=6, mtime=0) as compressed:
                    shutil.copyfileobj(source, compressed)
            temporary.replace(target)
            path.unlink()
        finally:
            temporary.unlink(missing_ok=True)


def download_file(relative_path, revision, cache):
    path = cache / (relative_path.removeprefix("config/"))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        print(f"Downloading {relative_path}", flush=True)
        try:
            with request(f"https://raw.githubusercontent.com/{REPO}/{revision}/{relative_path}") as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def load_symbols(directory):
    result = {}
    for value_type, filename in SYMBOL_FILES.items():
        path = directory / f"{filename}.sym"
        result[value_type] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].isdigit():
                    result[value_type][parts[1]] = int(parts[0])
    return result


class BrowserData:
    unquote = staticmethod(unquote)

    def __init__(self, records, symbols=None):
        self.records = records
        self.symbols = symbols or {}
        self.names = {page: {r["name"]: r["id"] for r in rows.values()} for page, rows in records.items()}
        self.refs = defaultdict(set)
        self.uses = defaultdict(list)
        self.field_uses = defaultdict(list)
        self.params = {r["name"]: r for r in records["params"].values()}
        self.previews = {}
        for page, keys in PREVIEW_KEYS.items():
            for record in records.get(page, {}).values():
                for key in keys:
                    value = field(record, key)
                    if value:
                        preview = self.resolve(value, "graphic")
                        if preview.get("kind") == "image":
                            self.previews[page, record["id"]] = preview
                            break

    def resolve(self, value, value_type, source=None):
        value = unquote(value)
        page = TYPE_PAGES.get(value_type)
        if page and value not in ("null", "-1", ""):
            target = self.names[page].get(value)
            if target is None and re.fullmatch(r"-?\d+", value) and int(value) in self.records[page]:
                target = int(value)
            if target is not None:
                if source is not None:
                    self.refs[page, target].add(source)
                label = unquote(field(self.records[page][target], DISPLAY_FIELDS[page])) if page in DISPLAY_FIELDS else value
                result = {"type": page, "id": target, "text": label or value}
                preview = self.previews.get((page, target))
                if preview and page != "cursors":
                    result["preview"] = preview
                return result
        if value_type == "coord":
            match = re.fullmatch(r"(\d+)_(\d+)_(\d+)_(\d+)_(\d+)", value)
            if match:
                plane, mx, my, lx, ly = map(int, match.groups())
                return {"text": f"{plane}, {mx * 64 + lx}, {my * 64 + ly}"}
        symbol_id = self.symbols.get(value_type, {}).get(value)
        if value_type == "graphic":
            if symbol_id is None and re.fullmatch(r"\d+", value):
                symbol_id = int(value)
            if symbol_id is not None:
                return {"kind": "image", "src": f"https://chisel.weirdgloop.org/static/img/rs3-graphic/{symbol_id}-0.png", "text": f"{symbol_id}: {value}"}
        elif symbol_id is not None:
            return {"text": f"{symbol_id}: {value}"}
        return {"text": value}

    def rows(self, page, record, collect=True):
        rows = []
        source = (page, record["id"]) if collect else None
        for key, value in record["fields"]:
            row = {"key": key, "key_name": key, "raw": value, "type": "", "parsed": []}
            if key == "param":
                row["kind"] = "param"
                pname, _, pvalue = value.partition(",")
                param = self.params.get(pname)
                row.update(key=pname, key_name=pname, raw=pvalue, type=field(param, "type", "int") if param else "unknown")
                if param:
                    row["param"] = param["id"]
                    if collect:
                        self.refs["params", param["id"]].add(source)
                        self.uses[page, param["id"]].append((record["id"], pvalue))
                row["parsed"] = [self.resolve(pvalue, row["type"], source)]
            elif page == "enums" and key in ("val", "default"):
                row["type"] = field(record, "outputtype", "int")
                if key == "val":
                    parts = split_values(value)
                    kval = parts[0]
                    vval = value[len(kval) + 1:]
                    row.update(key=kval, raw=vval, keyType=field(record, "inputtype", "int"), parsedKey=self.resolve(kval, field(record, "inputtype", "int"), source))
                else:
                    vval = value
                row["parsed"] = [self.resolve(vval, row["type"], source)]
            elif page == "dbrows" and key == "data":
                column, _, content = value.partition(",")
                table_id = self.names["dbtables"].get(field(record, "table"))
                table = self.records["dbtables"].get(table_id, {"fields": []})
                definition = next((v for k, v in table["fields"] if k == "column" and v.partition(",")[0] == column), "")
                types = definition.split(",")[1:]
                parts = split_values(content)
                row.update(key=column, key_name=column, raw=content, type=", ".join(types) or "unknown")
                row["parsed"] = [self.resolve(part, types[i % len(types)] if types else "", source) for i, part in enumerate(parts)]
            elif page == "quickchatcategories" and key in {"subcat", "phrase"}:
                target, _, shortcut = value.partition(",")
                value_type = "chatcat" if key == "subcat" else "chatphrase"
                row["type"] = native_field_type(page, key, record)
                row["parsed"] = [self.resolve(target, value_type, source)]
                if shortcut:
                    label = f"{chr(int(shortcut))} ({shortcut})" if shortcut.isdigit() and 32 <= int(shortcut) <= 126 else shortcut
                    row["parsed"].append({"text": label})
            elif page == "quickchatphrases" and key == "phrase":
                row["type"] = "string"
                row["parsed"] = [phrase_value(self, value, source)]
            elif page == "quickchatphrases" and key == "autoresponse":
                row["type"] = "chatphrase"
                row["parsed"] = [self.resolve(value, "chatphrase", source)]
            else:
                achievement_parsed = achievement_value(self, key, value, source) if page == "achievements" else None
                native_type = native_field_type(page, key, record)
                native_parsed = native_values(self, page, key, value, native_type, source, split_values)
                value_type = {"table": "dbtable", "certlink": "obj", "lentlink": "obj", "boughtlink": "obj", "achievementreq": "achievement", "questreq": "quest", "masterquestvarbit": "varbit", "morphvarbit": "varbit"}.get(key, "")
                if page == "params" and key == "default":
                    value_type = field(record, "type", "int")
                if achievement_parsed is not None:
                    row["parsed"] = achievement_parsed
                    if achievement_parsed[0].get("kind") == "table":
                        row["group"] = "achievement-requirements"
                elif native_parsed is not None:
                    row["parsed"] = native_parsed
                elif page == "cursors" and key == "graphic":
                    row["parsed"] = [self.resolve(value,"graphic",source)]
                elif page == "cursors" and key == "hotspot":
                    parts = split_values(value)
                    row["parsed"] = [{"text":f"{axis}: {part}"} for axis,part in zip(("X","Y"),parts)]
                elif page in {"items","npcs","scenery"} and re.fullmatch(r"(?:i?cursor\d+|cursorattack)",key):
                    parts = split_values(value)
                    row["parsed"] = [self.resolve(part,"cursor" if i == len(parts)-1 else "",source) for i,part in enumerate(parts)]
                elif page == "scenery" and key == "multiloc":
                    group, _, target = value.partition(",")
                    row["parsed"] = [{"text":group}, self.resolve(target,"loc",source)]
                elif page == "scenery" and key == "multivar":
                    # The text dumper uses this key for either a varbit or a varplayer.
                    # Only link when the name identifies a varbit unambiguously.
                    target_type = "varbit" if value in self.names["varplayerbits"] and value not in self.symbols.get("varplayer",{}) else "varplayer"
                    row["parsed"] = [self.resolve(value,target_type,source)]
                elif page in {"npcs", "scenery"} and key == "quest":
                    row["parsed"] = [self.resolve(target,"quest",source) for target in split_values(value)]
                elif (page == "invs" and re.fullmatch(r"stock\d+", key)) or (page == "items" and re.fullmatch(r"count\d+", key)):
                    parts = split_values(value)
                    row["parsed"] = [self.resolve(parts[0], "obj", source)] + [{"text": p} for p in parts[1:]]
                    value_type = "obj, int"
                elif value_type:
                    parts = split_values(value)
                    # achievementreq is group,achievement; others start with the reference.
                    ref_index = 1 if key == "achievementreq" else 0
                    row["parsed"] = [self.resolve(p, value_type if i == ref_index else "", source) for i, p in enumerate(parts)]
                else:
                    row["parsed"] = [{"text": unquote(value)}]
                row["type"] = native_type
                if page == "achievements" and achievement_parsed is None and row["type"] in {"graphic", "category", "dbrow"}:
                    row["parsed"] = [self.resolve(value, row["type"], source)]
                if page == "params" and key == "default":
                    row["type"] = value_type
                elif page == "dbtables" and key == "default":
                    column = value.partition(",")[0]
                    row["type"] = next((v.partition(",")[2] for k, v in record["fields"] if k == "column" and v.partition(",")[0] == column), "unknown")
            rows.append(row)
            if collect and key != "param" and page in FIELD_PAGES:
                self.field_uses[page, key].append((record["id"], value, row["type"], row["parsed"]))
        return rows

    def build(self, output):
        # Collect references before emitting any summaries or details.
        for page, records in self.records.items():
            print(f"Indexing {page}: {len(records):,}", flush=True)
            for record in records.values():
                self.rows(page, record)
        counts = {}
        for page, records in self.records.items():
            index, chunk = [], {}
            chunk_number = None
            for id, record in sorted(records.items()):
                number = id // CHUNK_SIZE
                if chunk_number is not None and number != chunk_number:
                    write_json(output / "data" / page / f"{chunk_number}.json", chunk)
                    chunk = {}
                chunk_number = number
                refs = sorted(self.refs[page, id])
                name = record["name"]
                display = unquote(field(record, DISPLAY_FIELDS[page])) if page in DISPLAY_FIELDS else field(record, "name")
                rows = self.rows(page, record, collect=False)
                size = len([r for r in rows if r["key"] not in ("inputtype", "outputtype", "default")]) if page == "enums" else len(rows)
                entry = {"id": id, "name": name, "display": display, "size": size, "refs": len(refs)}
                if page == "enums":
                    entry.update(keyType=field(record, "inputtype"), valType=field(record, "outputtype"))
                if page in PREVIEW_KEYS:
                    entry["preview"] = self.previews.get((page, id))
                if page == "params":
                    entry["type"] = field(record, "type", "int")
                    entry["size"] = sum(len(self.uses.get((p, id), [])) for p in self.records)
                index.append(entry)
                payload = entry | {"rows": rows, "references": [{"type": p, "id": n, "text": self.records[p][n]["name"]} for p, n in refs], "source": f"// {id}\n[{name}]\n" + "\n".join(f"{k}={v}" for k, v in record["fields"])}
                if page == "dbtables":
                    payload["dbrows"] = [r for r in payload["references"] if r["type"] == "dbrows"]
                if page == "params":
                    payload["uses"] = [{"key": n, "key_name": name, "raw": v, "type": entry["type"], "parsedKey": {"type": p, "id": n, "text": self.records[p][n]["name"]}, "parsed": [self.resolve(v, entry["type"])]} for p in self.records for n, v in self.uses.get((p, id), [])]
                chunk[str(id)] = payload
            self.emit(output, page, index, {chunk_number:chunk} if chunk_number is not None else {})
            counts[page] = len(index)
        for page, entity_page in PARAM_PAGES.items():
            index = []
            for (source_page, key), uses in sorted(self.field_uses.items()):
                if source_page != entity_page:
                    continue
                if not re.fullmatch(r"[a-zA-Z0-9_]+", key):
                    raise ValueError(f"Unexpected config field name: {key}")
                value_types = sorted({t for _, _, t, _ in uses if t})
                entry = {"id": key, "name": key, "size": len(uses), "refs": len({n for n, _, _, _ in uses}), "type": " / ".join(value_types), "example": uses[0][1]}
                index.append(entry)
                payload = entry | {"rows": [{"key": n, "key_name": key, "raw": v, "type": t, "parsedKey": {"type": entity_page, "id": n, "text": self.records[entity_page][n]["name"]}, "parsed": parsed} for n, v, t, parsed in uses], "references": []}
                write_json(output / "data" / page / f"field-{key}.json", {key: payload})
            write_json(output / "data" / page / "index.json", index)
            counts[page] = len(index)
        return counts

    @staticmethod
    def emit(output, page, index, chunks):
        write_json(output / "data" / page / "index.json", index)
        for number, chunk in chunks.items():
            write_json(output / "data" / page / f"{number}.json", chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="master", help="Git ref or full commit SHA (default: master)")
    parser.add_argument("--dump-dir", type=Path, help="Use a local directory containing all required dump.* files")
    parser.add_argument("--symbols-dir", type=Path, help="Optional symbols directory for local dumps (graphic/category/stat/varp .sym files)")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--compress-json", action="store_true", help="Store data as .json.gz for size-limited static hosts such as GitHub Pages")
    parser.add_argument("--history-dir", type=Path, default=ROOT / "history", help="Imported CachePages history directory (default: history)")
    parser.add_argument("--no-history", action="store_true", help="Build without imported config history")
    parser.add_argument("--pipeline-state", type=Path, help="State written by pipeline.refresh, for deployment freshness checks")
    args = parser.parse_args()
    revision = args.ref
    if not args.dump_dir:
        with request(f"https://api.github.com/repos/{REPO}/commits/{args.ref}") as response:
            commit = json.load(response)
        revision = commit["sha"]
        cache = ROOT / ".cache" / revision
        with ThreadPoolExecutor(max_workers=4) as executor:
            paths = [f"config/dump.{kind}" for kind in FILES.values()] + [f"symbols/{name}.sym" for name in SYMBOL_FILES.values()]
            list(executor.map(lambda path: download_file(path, revision, cache), paths))
    else:
        cache = args.dump_dir.resolve()
    pipeline = None
    if args.pipeline_state:
        state = json.loads(args.pipeline_state.read_text(encoding='utf-8'))
        if args.no_history or state['revision'] != revision or state['history_digest'] != history_digest(args.history_dir):
            raise ValueError('Pipeline state does not match the selected dump and retained history; refresh it before building')
        pipeline = {key:state[key] for key in ('source_digest','history_digest')}
    records, hashes = {}, {}
    for page, kind in FILES.items():
        path = cache / f"dump.{kind}"
        with path.open("rb") as source:
            hashes[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
        with path.open(encoding="utf-8-sig") as source:
            rows = list(parse_dump(source))
        records[page] = {r["id"]: r for r in rows}
        if not rows or len(records[page]) != len(rows):
            raise ValueError(f"Empty dump or duplicate numeric IDs: {path}")
    symbols_dir = args.symbols_dir or (cache / "symbols" if (cache / "symbols").is_dir() else cache.parent / "symbols")
    symbols = load_symbols(symbols_dir)
    for filename in SYMBOL_FILES.values():
        path = symbols_dir / f"{filename}.sym"
        if path.exists():
            with path.open("rb") as source:
                hashes[f"symbols/{path.name}"] = hashlib.file_digest(source, "sha256").hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    counts = BrowserData(records, symbols).build(args.output)
    # Full revision history is large; release the current dump before expanding it.
    del records, symbols
    for name in ("index.html", "structs.js", "style.css", "key_labels.json"):
        shutil.copyfile(FRONTEND / name, args.output / name)
    shutil.copytree(FRONTEND / 'images',args.output / 'images',dirs_exist_ok=True)
    history = None if args.no_history else prepare_history(args.history_dir, args.output, FILES, TYPE_PAGES, revision)
    if args.compress_json:
        print("Compressing generated JSON for static hosting", flush=True)
        compress_json_files(args.output)
    manifest = {"repository": REPO, "revision": revision, "local": bool(args.dump_dir), "built": datetime.now(timezone.utc).isoformat(), "chunkSize": CHUNK_SIZE, "counts": counts, "sha256": hashes}
    if args.compress_json:
        manifest["compression"] = "gzip"
    if history:
        manifest["history"] = history
    if pipeline:
        manifest['pipeline'] = pipeline
    write_json(args.output / "data" / "manifest.json", manifest)
    print(f"Built {sum(counts.values()):,} entries in {args.output}")
    print("Run: python tools/serve.py")


if __name__ == "__main__":
    main()
