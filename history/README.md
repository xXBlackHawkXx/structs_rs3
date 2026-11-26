# RS3 revision history

Compare two [rs3-dumps](https://github.com/Joshua-F/rs3-dumps) snapshots and export added, removed and modified configuration records as JSON. Requires **Python 3.11 or newer**, with no third-party packages.

## Quick start

Run these commands from the repository root:

```powershell
python -m history list
python -m history generate
```

The combined command, `python -m pipeline.build`, generates missing comparisons, imports compact history and builds the static viewer. The generator alone writes raw schema-version-2 JSON to `.cache/reports/DATE-revREV.json`. Downloads default to `.cache/comparisons/`. Both are ignored temporary data; durable compact viewer inputs live in `history/`.

This package contains the comparison engine, reference normalization, native field definitions and material/font name decoding. Its offline tests live in `tests/comparisons/`. Python's standard library is sufficient.

Generation selects the latest dated cache commit and compares it with the preceding dump on its first-parent history, skipping maintenance commits. The earliest snapshot uses an empty baseline, marked `comparison_kind: "initial_snapshot"`; this is an initial inventory rather than evidence of when records were introduced into the game.

## Choosing snapshots and output

```powershell
# List dated commits and their full SHA values.
python -m history list --limit 50

# Compare an update with its preceding dump.
python -m history generate --target 2026-11-23

# Choose both ends of the comparison.
python -m history generate --base 2026-11-09 --target 2026-11-23

# Pin an exact commit for repeatable generation.
python -m history generate --target d215783ad35d9c7ff2e6d3562ebfd0a0abbde916

# Select types and an explicit JSON path.
python -m history generate --types obj npc loc struct --output .cache/reports/entities.json
```

Selectors accept a date, a full dump title such as `2026-11-23-rev951`, a commit SHA, a Git branch/tag, or a **unique** revision number. Dates and titles come from commit messages. Several updates can share a revision number or date; use a SHA when a selector is ambiguous. Use distinct `--output` paths to retain comparisons with the same target date/revision or different bases.

Same-day snapshots such as `2026-03-02a-rev946` and `2026-03-02b-rev946` can be selected by their full titles. Their default reports are `2026-03-02-rev946-a.json` and `2026-03-02-rev946-b.json`; the recorded date remains `2026-03-02`.

`--output` must have a `.json` suffix. Existing output is replaced only after a successful comparison and a complete temporary JSON write.

## JSON format

Reports retain `schema_version: 2` for compatibility with consumers such as `builder/history.py`. The tool identifier is `CachePages/2.0`. Wiki page metadata (`pages` and `output_sha256`) has been removed from generation.

| Field | Contents |
| --- | --- |
| `before`, `after` | Snapshot title, date, revision, exact commit SHA, first parent and OpenRS2 archive link where available. |
| `coverage` | Included dump suffixes and excluded types. `interfaces` remains `false` for schema compatibility. |
| `summary` | Counts by type: `new`, `removed`, `changed` records and `fields_changed`. Includes unchanged selected types with zero counts. |
| `changes` | Added, removed and modified records, keyed by dump suffix. Only types with changes appear. |
| `compared_files` | Input side, path, Git blob hash and byte size for compared files. |
| `normalization` | Reference policy, ignored naming-change counts, symbol reassignment flag and reference input metadata. |
| `unchanged_files`, `unchanged_blobs` | Identical input files and their hashes/sizes. |

Each type in `changes` contains three arrays:

- `added`: complete records present only in the target snapshot.
- `removed`: complete records present only in the base snapshot.
- `modified`: objects with `id`, complete `before` and `after` records, and a `fields` array of semantic changes.

Complete records have `id`, `config_name`, `name`, `source` and `fields`. Numeric IDs are JSON numbers; composite IDs remain strings. An unavailable display name is `null`. `fields` maps original dump keys to arrays of strings, preserving repeated values and their order. For example, `param=a,1` and `param=b,2` become `"param": ["a,1", "b,2"]`. Values retain decoded text, Unicode, commas, quotes and markup. Numbers and booleans in dump values remain strings.

A modified field looks like this:

```json
{
  "field": "param[pet]",
  "identity": {"field": "param", "entry": {"type": "param", "id": 2}},
  "before_field": "param[param_2]",
  "after_field": "param[pet]",
  "before": ["npc_3"],
  "after": ["dragon"],
  "before_references": [{"value_index": 0, "path": [], "type": "npc", "id": 3}],
  "after_references": [{"value_index": 0, "path": [], "type": "npc", "id": 4}]
}
```

`before` or `after` is `null` when a field or entry is absent. An explicit empty value is `[""]`; a literal cache string `null` is `["null"]`. Field labels are also `null` when absent. Parameter and enum entries are compared individually; their values exclude the entry key, which is represented by the labels and `identity`.

`identity.field` identifies the original dump field. Parameter and enum identities additionally contain `entry`, using a resolved `{type, id}` reference where possible or `{value: "..."}` for a literal/unresolved key. Composite keys use `{parts: [...]}`. Reference lists use `value_index` to locate a repeated value and `path` to locate a reference within its nested comparison value. Simple references have an empty path. Unresolved names retain their original text without an invented reference.

Two raw values can be identical while their references resolve to different IDs; the reference lists expose that change. Naming-only differences are omitted. Complete snapshots may still contain naming differences in otherwise unchanged fields; use the modified record's `fields` array to identify semantic changes.

Types, records and changed fields have deterministic ordering. Array lengths match summary counts, and the total modified field count matches `fields_changed`. An empty comparison has `"changes": {}`.

```python
import json
from pathlib import Path

report = json.loads(Path(".cache/reports/2026-11-23-rev951.json").read_text(encoding="utf-8"))
for record in report["changes"].get("obj", {}).get("modified", []):
    for field in record["fields"]:
        print(record["id"], field["field"], field["before"], field["after"])
```

## Coverage and comparison rules

Available `config/dump.*` types are discovered automatically. Excluded types are `varn`, `varglobal`, `varcon`, `controller`, `gamelogevent`, `flo`, `apievent`, `particleemitter`, `stylesheet`, `varc`, `worldarea`, `area` and `interface`. They cannot be selected with `--types`, although their definitions may resolve references from included types. Interface files are not compared; component symbols remain available for reference matching.

Records are matched by numeric ID, including sparse IDs and unnamed `[]` records. A cleared record still present at the same ID is modified rather than removed. Ordering between independent fields does not count as a change; repeated-field order does.

Each snapshot uses its own symbol tables and numeric dump headers. Parameter names and typed values, enum keys/values, database columns/cells and supported script/Quick Chat arguments are matched by identity. Display names and string values stay literal. Unknown fields and ambiguous names are retained conservatively. Identical raw text that is unresolved on one side is not treated as changed without evidence of different IDs.

These are decoded configuration comparisons. Defaults and transformations such as item note inheritance are not inferred. Only the selected endpoints are compared; reverted intermediate changes are not visible. Models, sprites, audio, scripts, world maps, terrain, spawns and other non-config assets are outside this tool's comparison.

## Local snapshots and offline use

Supply two checkout roots containing `config/` and optionally `symbols/`, or two directories containing `dump.*` files:

```powershell
python -m history generate `
  --old-dir 'J:/Caches/previous' `
  --new-dir 'J:/Caches/current' `
  --date 2026-11-23 --revision 951
```

Local mode makes no network requests and requires the target date and revision. It records local Git blob hashes without attributing a GitHub commit. A file missing from one endpoint is treated as absent, making all its records added or removed. Supply matching complete snapshots, or use `--types` for an intentional subset.

Include matching `symbols/` files for full reference matching. Material/font symbols can supply names absent from dump exports. With config directories alone, record headers and type declarations are used; unresolved references stay literal.

## Downloads and caching

Remote refs are resolved to immutable commits. Downloads are checked against their Git blob hashes and byte sizes, then cached under `.cache/comparisons/blobs/`. Identical blobs can skip comparison unless symbol bindings were reassigned. Reference definitions may require files outside selected output types. A first run can require several hundred megabytes of traffic and memory.

Remote mode also reads material/font names from JS5 archive 67, groups 32 and 90 in the exact OpenRS2 cache linked by the commit. These live under `.cache/comparisons/assetnames/`; source URLs, sizes and SHA-256 hashes are recorded. Local mode never fetches them.

`--cache-dir PATH` changes the cache location. If GitHub's unauthenticated API rate limit is reached, set `GITHUB_TOKEN` or `GH_TOKEN`. Tokens are sent only to the GitHub API.

The complete revision list is cached in `.cache/comparisons/history.json` for one hour. Use `list --refresh-history` or `generate --refresh-history` to refresh explicitly. If automatic refresh fails, an existing complete list is reused with a warning. Explicit refresh failures are reported without fallback; incomplete history is never cached. Full base/target SHAs bypass history lookup and reuse cached metadata and blobs.

The retained cache consists of `api/`, `assetnames/`, `blobs/` and `history.json`. It can be deleted to reclaim space; remote generation will download it again. `.cache/reports/` contains temporary raw JSON reports, separate from retained viewer history.

Malformed dumps, duplicate IDs, download failures and integrity mismatches stop generation without replacing existing reports.

## Tests

From the repository root:

```powershell
python -B -m unittest -v
```

From the parent `Tools` directory:

```powershell
python -B -m unittest discover -s CachePages -v
```

Tests run offline and cover parsing, sparse IDs, repeated fields, missing/empty values, semantic reference identities, source selection, history caching, download integrity, type exclusions, deterministic JSON, complete large records and safe output replacement.
