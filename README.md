# RS3 cache config viewer

A local static recreation of the [Chisel struct viewer](https://chisel.weirdgloop.org/structs_rs3/index.html), built from [Joshua-F/rs3-dumps/config](https://github.com/Joshua-F/rs3-dumps/tree/master/config).

## Run

Python 3.11 or newer is required. No third-party packages, API keys, Node dependencies, or database are needed.

From this folder:

```powershell
python -m pipeline.build
python tools/serve.py
```

After the build completes, open **http://127.0.0.1:8000/**. Generated output and downloaded dumps are not included in source control, so a clean checkout must run `python -m pipeline.build` before `python tools/serve.py`. The combined command generates missing comparisons, retains compact history inputs, and builds the viewer at the same immutable dump commit.

The first build downloads approximately 190 MB of text dumps. Builds resolve `master` to one commit before downloading, cache files under `.cache/<commit>/`, and record the commit and SHA-256 hashes in `dist/data/manifest.json`. Running the build again checks for a newer commit and reuses downloads for the selected commit. Data is fetched during the build; browsing does not call GitHub. Detail chunks are written incrementally, and native field usage is collected only for types that have field browsers, keeping large animation dumps from retaining unused data.

Pin a revision for a reproducible build, use local dumps, or select another port:

```powershell
python -m builder.build --ref d215783ad35d9c7ff2e6d3562ebfd0a0abbde916
python -m builder.build --dump-dir C:/cache/config
python tools/serve.py --port 8080
```

Local input requires `dump.param`, `dump.struct`, `dump.enum`, `dump.obj`, `dump.npc`, `dump.loc`, `dump.cursor`, `dump.quest`, `dump.achievement`, `dump.inv`, `dump.idk`, `dump.dbtable`, `dump.dbrow`, `dump.varbit`, `dump.quickchatcat`, and `dump.quickchatphrase`.

It also requires `dump.varp`, `dump.mel`, `dump.msi`, `dump.bas`, `dump.seq`, `dump.spot`, `dump.hitmark`, and `dump.headbar` for the additional config types below.

## Repository layout

```text
builder/             Viewer importer, parsers, and generated site data
pipeline/            Incremental history refresh and coordinated builds
frontend/            HTML, JavaScript, CSS, and display labels
history/             Comparison engine, CLI, and reference normalization
  manifest.json      Retained comparison index
  reports/           Compact revision comparisons used by builds
tests/               Viewer, history, pipeline, and frontend checks
  comparisons/       Comparison engine regression tests
tools/               Local preview server
.github/workflows/   GitHub Pages build and deployment
```

Run the commands in this README from the repository root. Builds copy `frontend/` assets into the root of `dist/`, so published URLs keep the same format. Generated `dist/` output and the `.cache/` download/test cache stay at the repository root and are ignored by Git.

## GitHub Pages

The [deployment workflow](.github/workflows/deploy-pages.yml) runs only when started manually through **Actions → Build and deploy cache viewer → Run workflow**, with an optional dump branch/tag/commit (default: `master`). Only default-branch runs deploy or commit history.

Each run tests the Python packages, resolves the selected dump to an exact snapshot SHA, and walks its first-parent history back to the last retained adjacent comparison. It generates every intervening comparison, merges the compact reports into `history/`, then builds the viewer at that same SHA. Maintenance commits without dated cache titles are skipped. Every manual run forces a build, including when retrying a failed deployment whose history has already been retained.

Successful builds run frontend checks and the size check before committing updated `history/` inputs as `github-actions[bot]`, uploading `dist`, and deploying Pages. The build job requests `contents: write` for those history commits. Bot commits use `GITHUB_TOKEN`, so they do not recursively start another push workflow; deployment continues in the same run. Existing write restrictions on the default branch must permit that history commit. The deployment job keeps separate Pages/OIDC permissions. No personal access token is required. [GitHub token behaviour](https://docs.github.com/en/actions/concepts/security/github_token)

1. Commit this folder's source files and `.github/workflows/deploy-pages.yml` to your repository. The workflow must be at the repository root's `.github/workflows/` path. If the viewer is in a subdirectory, set the workflow's `PROJECT_DIR` to that path, such as `structs_rs3` or `Tools/structs_rs3`.
2. In **Settings → Pages → Build and deployment**, set **Source** to **GitHub Actions**.
3. After pushing the workflow to the default branch, use **Actions → Build and deploy cache viewer → Run workflow**. The deployment job reports the site URL.

The workflow builds with `python -m builder.build --compress-json`. This stores generated data as `.json.gz`, keeps the bootstrap manifest and frontend assets uncompressed, and lets the browser decompress fetched data. Relative asset links support both repository Pages sites and account/custom-domain sites. Normal local builds continue to use plain JSON. For a compressed local build, use the same flag and run `python tools/serve.py` as usual.

The full dataset requires compression for [GitHub Pages' 1 GB published-site limit](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits); the workflow rejects oversized output before uploading. Compressed builds require a browser with [DecompressionStream support](https://developer.mozilla.org/en-US/docs/Web/API/DecompressionStream). Generated `dist/`, raw reports, and download caches stay ignored. Compact `history/` inputs are committed so history survives clean runners and failed deployments.

## Viewer

- The original categories, Scenery, Cursors, Quick Chat, and the additional config types below have search, sorting, record filters, and pagination. Scenery comes from `dump.loc` and uses `index.html?type=scenery&id=ID`; its native fields use `type=scenery_params`. Cursors come from `dump.cursor`, with `type=cursors` and `type=cursor_params`.
- Quick Chat categories (`type=quickchatcategories`) and phrases (`type=quickchatphrases`) come from `dump.quickchatcat` and `dump.quickchatphrase`. Listings show searchable/sortable descriptions or phrase text alongside dump names. Category entries link to subcategories and phrases, with printable shortcut keys shown alongside their numeric codes. Phrases link to automatic responses, and all these relationships have incoming references.
- Quick Chat templates retain their commands as text. Supported command arguments resolve to enums, varbits, player variables, and skill symbol IDs, with reverse references to linked configs. Unknown commands remain literal text; player-specific values are not evaluated. Shared parameters and database/enum values typed as `chatcat` or `chatphrase` link to the new records.
- Player variables (`type=varplayers`, `dump.varp`), map elements (`mapelements`, `dump.mel`), map scene icons (`mapsceneicons`, `dump.msi`), animation sets (`animationsets`, `dump.bas`), animation sequences (`sequences`, `dump.seq`), spot effects (`spoteffects`, `dump.spot`), hitsplats (`hitsplats`, `dump.hitmark`), and health bars (`healthbars`, `dump.headbar`) have list/detail pages, search, sorting, pagination, source configs, and incoming references.
- Map elements, map scene icons, hitsplats, and health bars show available sprite previews in lists, details, and links. Sprite names resolve through the pinned graphic symbols, including quoted names with commas. All graphic component fields remain available in the config table. Morph targets and unambiguous variable conditions link to their configs.
- NPC animation sets and map elements, scenery animations and map icons, player-domain varbit base variables, achievement/quest variable requirements, and Quick Chat variable placeholders link to the new types. Animation sets link to idle/walk/run sequences, spot effects link to sequences, and sequence held-item overrides link to items. Frame IDs, delays, keyframe ranges, weights, and sound settings retain their raw values and declared types. These pages browse definitions; animation playback and model rendering require separate assets/rendering support.
- Cursor list/detail pages show graphic previews, with hotspot X/Y coordinates on detail pages. Item, NPC and scenery cursor fields link to cursor records; shared parameters, enum entries and database columns typed as cursors also resolve. Cursor pages show the incoming references.
- Large reference groups show 250 entries at a time, with `Show more` to reveal the next batch, so commonly used cursors remain responsive.
- Links to cursor records show the cursor graphic before the link, including parsed fields, parameter usage tables, enum entries, and references. Graphics are resolved from the small cursor index and load lazily.
- Links to individual structs, database rows, achievements, enums, quests, and NPCs include Chisel's matching `*-icon.png` markers before the text throughout the viewer, at their native 11×11 size.
- Parsed item references show a 32×32 item sprite before the link, including plain `obj` fields and item/quantity tuples.
- A grouped, labelled config selector and breadcrumbs for the current collection/entry. Detail pages have a single `Browse all` action in the header instead of separate quick links and a repeated list button.
- Original numeric config URLs, such as `index.html?type=structs&id=0`.
- Config detail pages include dated History entries with before/after field values, added/removed events, and links to compare the source commits. A Raw/Parsed toggle switches both value columns together. Removed configs remain accessible by their numeric detail URL when imported history exists. History is separate from current incoming references.
- Parameter types, defaults, usage values, and links to source configs.
- Parameter definition fields, including type, default, and automatic-disable flags, use the same metadata layout as enums above the usage table. Parsed defaults retain links and icons; usage records remain in their table.
- Shared `key_name` and `type` values appear once as metadata instead of repeated columns. Parameter/field pages show them beneath the title; other detail tables show them above the table. Columns are assessed independently across all rows, including later pagination pages. Inventory detail tables and attached CS2 params tables always retain both columns, including single-field inventories and single-parameter tables.
- Separate native fields and `cs2 params` sections on entity pages. These attached parameters are distinct from the incoming links listed under References.
- Enum keys and values resolved according to their declared types.
- Enum detail pages show input type, output type, and any explicit default above the entries table. Defaults retain parsed links and icons; raw values remain available in tooltips and source config. Entry counts and pagination exclude these definition fields.
- Database table pages show their records in a table with typed column headings and links to each row. Repeated values use separate, bordered table rows, with shared cells spanning the entries; `obj, int` and `dbrow, int` values show a linked item/row with its icon and an aligned quantity, on table and row detail pages. Missing explicit values show `null` in darker cells, matching Chisel; defaults remain in the definitions above. Records load in pages of 100, reusing downloaded chunks.
- Inventory `stockN` and item `countN` rows retain the config table layout, with `parsed_val` split into an item sprite/link and a separate quantity column. This also applies to their field usage pages. Unresolved item references remain text without an icon; unavailable icon images are hidden.
- Achievement requirement tables with linked varbits, quest/achievement requirements, prerequisite groups, bit tests, and reverse references. Repeated requirements are grouped into one parsed table while all raw tuples remain visible.
- Parsed achievement descriptions, category IDs, and sprite previews, resolved from the dump repository's symbol files.
- Repeated fields, quoted tuple values, and source config text preserved.
- Original dark table colours, including named and empty records.
- The `m p s l i` shortcuts appear only on item, achievement, scenery, quest, and struct detail pages. `m` opens MRID for items, MROD for scenery, or the matching Chisel config browser. `p` opens the wiki page, `s` searches its name, `l` uses wiki ID lookup with name fallback, and `i` searches the ID with type context. All links open in a new tab. Other config pages retain available sprite previews without shortcut links.

The `*_params` categories browse native config fields (`name`, `model`, etc.). The text dumps use symbolic field names rather than the numeric opcodes in the original viewer, so these URLs use names, e.g. `index.html?type=item_params&id=name`. Shared `param=…` entries belong to `params`, where their numeric IDs are retained.

`raw_val` means the literal value from the text dump, which can already be a symbolic name. Parsed values link to supported configs and decode coordinates and achievement requirements. References include shared parameters, enum keys/values/defaults, database data, achievement requirements, scenery morphs, and supported native relationship fields. Shared parameters, enums and database columns with type `loc` resolve to scenery. NPC and scenery `quest[]` fields link each quest in the list, including their field usage pages and incoming quest references; unambiguous scenery varbit references also link to their configs. Attached `cs2 params` are imported from `param=…` entries; references from CS2 script source code are not imported. Item icons and resolved sprite previews load from Chisel; model assets and remaining special derived interpretations from the original generator are not imported. RuneScape markup is displayed as text.

Normal builds download `symbols/graphic.sym`, `category.sym`, `stat.sym`, and `varp.sym` from the same pinned dump commit. These map readable names to numeric sprite/category/skill/variable IDs without Sheets. Local builds can supply them in a `symbols` folder inside or next to the dump directory, or with `--symbols-dir PATH`. Without symbols, names remain visible and varbits still link using `dump.varbit`; unavailable sprite previews and numeric symbol IDs remain text. Graphic image availability depends on Chisel's hosted cache version.

`key_name` displays human-readable labels on entity and usage tables, compared with Chisel's native field and parameter labels. Local overrides in `frontend/key_labels.json` expand abbreviations, model/action/colour slot names, and compound fields; remaining parameter names have underscores and camel case separated and common abbreviations expanded. The raw column, links, source config, and generated data retain canonical dump keys. Hover over a display label to see its original key. For 46 otherwise unnamed parameters, the local label file includes named aliases captured from Chisel; no label lookups or Sheets requests happen at runtime or during builds.

Native field types are defined locally in `field_types.py`, checked against the [dumper's config unpackers](https://github.com/zwyz/rs3-cache/tree/59b566a22a9ea537c26e99701837c2c5cce4871e/src/main/java/rs3/unpack/config). Shared parameter types come from `dump.param`, and database column types come from `dump.dbtable`. Types describe individual text fields, which can differ from the original viewer's grouped numeric opcodes. Unrecognised future fields show `unknown`; the importer does not infer a semantic type from the value or fetch definitions during a build.

Config names come directly from the `[config_name]` headings in the dump files. Numeric IDs come from their `// ID` comments, and shared parameter names and types come from `dump.param`. The importer uses these names to resolve links between configs; it makes no Google Sheets requests and uses no spreadsheet metadata.

## Revision history

The comparison engine is bundled in `history/`; builds and deployment do not depend on a sibling checkout. From the repository root, update history and build in one command:

```powershell
python -m pipeline.build
# GitHub Pages format:
python -m pipeline.build --compress-json
```

To refresh only history, run `python -m pipeline.refresh`. It records the selected snapshot and input digests in `.cache/pipeline/state.json`. The lower-level `python -m builder.build` still builds using retained comparisons without generating new ones.

Existing external CachePages JSON reports can also be merged without changing that input directory:

```powershell
python -m builder.history --input ../CachePages/output
python -m builder.build
```

Commit `history/manifest.json` and the compressed files it references under `history/reports/`. New reports are merged by their exact before/after commit pair, preserving earlier comparisons. Reimporting an unchanged report is idempotent. Updated reports receive content-addressed filenames and the manifest is replaced atomically; a failed import leaves the previous manifest and its reports readable. Raw generated reports live temporarily under `.cache/reports/`; comparison downloads use `.cache/comparisons/`.

The retained backfill begins with the earliest available dated dump in December 2003. The viewer displays its actual available coverage from the manifest. An empty History section means no changes were recorded in those comparisons, not that a config has never changed. Builds pinned to a known snapshot SHA exclude later comparisons, including later snapshots on the same day. The build uses a temporary disk database and writes one history chunk at a time to handle the full backfill without retaining every event in memory.

Modified records use only the report's semantic field changes. Removed words, numbers and punctuation are highlighted in red; additions are highlighted in green, with shared text left unchanged. Repeated values are aligned before comparing their text. Missing fields, empty strings, literal `null`, and repeated values remain distinct. The **Raw/Parsed** toggle defaults to Raw and switches both before/after columns together, preserving expanded events and fields. Parsed mode uses the existing config parsers for tables, linked values, icons, quoted strings and coordinates, with highlighting applied to their displayed text. Hover over a parsed value to see its raw text. No separate reference labels are displayed in either mode.

Parsed history is captured during import using each side's snapshot context and explicitly recorded reference IDs. It does not look up old names in the current dump. Unsupported values, older history imports without parsed data, and names without recorded references remain text. Added/removed records have no resolved-reference metadata, so their parsed values decode supported formats without guessing links. All history entries start collapsed and render when opened. Large events reveal 100 fields at a time. Native `*_params` usage pages have no separate history; their owning configs do.

Use `--history-dir PATH` to build from another imported history directory, or `--no-history` to omit history. A checkout without a `history/manifest.json` also builds without history.

## Files and verification

`pipeline/` coordinates refresh and build. `history/` contains the bundled comparison generator, documented in [history/README.md](history/README.md). `builder/build.py` downloads, parses, and builds `dist`. The other `builder/` modules define native field types, achievement requirements, Quick Chat templates, additional relationships, and sprite preview priorities. `frontend/` contains the static site source and display labels. `tools/serve.py` serves only `dist`, bound to localhost. Any ordinary static host can also serve the contents of `dist`; opening HTML through `file://` will not work because the viewer fetches JSON. Tests live in `tests/`.

```powershell
python -m unittest discover -s tests -v
node --check frontend/structs.js
```

Tests cover sparse numeric IDs, repeated fields, quoted commas, typed references, database tuples, Quick Chat categories/responses/templates, and separation of native fields from shared parameters. They use temporary fixtures and can run before building any data. Node is optional for the viewer; the workflow uses Node 24 for frontend checks.

Optional DOM checks require generated `dist` data and jsdom as a test-only dependency. After building the site, run:

```powershell
npm install --prefix .cache/frontend-check --no-save --ignore-scripts jsdom@29.1.1
node tests/test_frontend.cjs --smoke
```

The smoke checks work with any dump revision. For the full snapshot regression suite, build the pinned revision shown above and run `node tests/test_frontend.cjs` without `--smoke`.
