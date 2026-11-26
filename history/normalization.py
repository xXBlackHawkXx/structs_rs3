"""Compare historical cache references by identity, retaining literal strings.

Symbol tables are scoped to the exact dump revision. Unknown fields and
ambiguous names remain literal; no guesses are made from display text.
"""
from collections import defaultdict
from functools import lru_cache
import re

from .normalization_fields import native_field_type

ALIASES = {
    "namedobj": "obj", "item": "obj", "object": "loc", "varplayer": "varp",
    "varplayerbit": "varbit", "varclient": "varc", "varclientstring": "varc",
    "varnpc": "varn", "varobject": "varobj", "varshared": "varworld",
    "chatcat": "quickchatcat", "chatphrase": "quickchatphrase", "mapelement": "mel",
    "mapsceneicon": "msi", "spotanim": "spot", "idkit": "idk", "categorytype": "category",
    "sound": "vorbis", "synth": "vorbis", "pef": "particleeffector", "pem": "particleemitter",
    "toplevelinterface": "interface", "overlayinterface": "interface", "clientinterface": "interface",
}
PAGES = {
    "obj": "items", "npc": "npcs", "loc": "scenery", "param": "params", "enum": "enums",
    "struct": "structs", "quest": "quests", "achievement": "achievements", "varbit": "varplayerbits",
    "varp": "varplayers", "mel": "mapelements", "msi": "mapsceneicons", "bas": "animationsets",
    "seq": "sequences", "spot": "spoteffects", "hitmark": "hitsplats", "headbar": "healthbars",
    "idk": "idkits", "inv": "invs", "dbtable": "dbtables", "dbrow": "dbrows",
    "cursor": "cursors", "quickchatcat": "quickchatcategories", "quickchatphrase": "quickchatphrases",
}
TEXT_KEYS = {"name", "text", "desc", "sortname", "reward", "shardname", "opbase", "targetverb",
             "damageformat", "tooltip", "optext", "unknown9"}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?::[A-Za-z_0-9]+)*")
NUMERIC_ID = re.compile(r"\d+(?::\d+)*$")


@lru_cache(maxsize=8192)
def declared_type(kind, field):
    return native_field_type(PAGES.get(kind, kind), field)


def split_values(value):
    """Split comma tuples without splitting quoted string/graphic values."""
    parts, start, quote, escaped = [], 0, None, False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'" and not value[start:index].strip():
            quote = char
        elif char == ",":
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def unquote(value):
    return value[1:-1] if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0] else value


class ReferenceIndex:
    def __init__(self):
        self.names = defaultdict(dict)
        self.param_types = {}
        self.column_types = {}
        self.components = defaultdict(dict)
        self.columns = defaultdict(dict)
        self.stats = defaultdict(int)
        self._any = None
        self._resolved = {}

    @staticmethod
    def kind(kind):
        return ALIASES.get(kind, kind)

    def add(self, kind, identifier, symbol):
        kind = self.kind(kind)
        if not symbol:
            return
        mapping = self.names[kind]
        if symbol in mapping and mapping[symbol] != identifier:
            mapping[symbol] = None  # Ambiguous symbol: never choose one ID.
        else:
            mapping[symbol] = identifier
        if kind in {"component", "dbcolumn"} and ":" in identifier and ":" in symbol:
            scope = identifier.split(":", 1)[0]
            short = symbol.split(":", 1)[1]
            scoped = self.components if kind == "component" else self.columns
            if short in scoped[scope] and scoped[scope][short] != identifier:
                scoped[scope][short] = None
            else:
                scoped[scope][short] = identifier
        if kind == "clientscript":
            match = re.fullmatch(r"\[clientscript,([^\]]+)\]", symbol)
            if match:
                self.add("script_handler", identifier, match[1])
        self._any = None
        self._resolved.clear()

    def load_symbols(self, path, kind):
        kind = self.kind(kind)
        with path.open(encoding="utf-8-sig") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) < 2 or not NUMERIC_ID.fullmatch(parts[0]):
                    raise ValueError(f"{path}:{number}: invalid symbol entry")
                identifier, symbol = parts[:2]
                self.add(kind, identifier, symbol)
                if kind == "param" and len(parts) > 2:
                    self.param_types[identifier] = parts[2]
                if kind == "dbcolumn" and len(parts) > 2:
                    self.column_types[identifier] = tuple(split_values(",".join(parts[2:])))

    def load_config(self, path, kind):
        """Index headers and the small type declarations missing from .sym files."""
        pending, identifier = None, None
        with path.open(encoding="utf-8-sig") as handle:
            for raw in handle:
                line = raw.strip()
                match = re.fullmatch(r"//\s*(\d+(?::\d+)?)", line)
                if match:
                    pending = match[1]
                elif line.startswith("[") and line.endswith("]") and pending is not None:
                    identifier, pending = pending, None
                    self.add(kind, identifier, line[1:-1])
                elif identifier is not None and kind == "param" and line.startswith("type="):
                    self.param_types[identifier] = line[5:]
                elif identifier is not None and kind == "dbtable" and line.startswith("column="):
                    parts = split_values(line[7:])
                    column = self.column(parts[0], identifier)
                    if column is not None:
                        self.column_types[column] = tuple(parts[1:])

    def resolve(self, kind, value, scope=None):
        kind = self.kind(kind)
        scope = scope if kind == "component" else None
        key = (kind, value, scope)
        if key not in self._resolved:
            result = self._resolve(kind, value, scope)
            if len(self._resolved) >= 65536:
                self._resolved.clear()
            self._resolved[key] = result
        return self._resolved[key]

    def _resolve(self, kind, value, scope=None):
        kind, value = self.kind(kind), unquote(value.strip())
        identifier = self.names.get(kind, {}).get(value)
        if identifier is not None:
            return ("ref", kind, identifier)
        if value in self.names.get(kind, {}):
            return None
        if NUMERIC_ID.fullmatch(value):
            return ("ref", kind, value)
        # Generic names emitted when a revision has no human-readable symbol.
        prefixes = [kind] + [alias for alias, target in ALIASES.items() if target == kind]
        for prefix in prefixes:
            match = re.fullmatch(re.escape(prefix) + r"_(\d+)", value)
            if match:
                return ("ref", kind, match[1])
        if kind == "clientscript":
            handler = self.names.get("script_handler", {}).get(value)
            if handler is not None:
                return ("ref", kind, handler)
            match = re.fullmatch(r"(?:\[clientscript,)?script(\d+)\]?", value)
            if match:
                return ("ref", kind, match[1])
        if kind == "component":
            match = re.fullmatch(r"(.+):com_(\d+)", value)
            if match:
                interface = self.resolve("interface", match[1])
                if interface:
                    return ("ref", kind, interface[2] + ":" + match[2])
            if scope is not None:
                identifier = self.components.get(scope, {}).get(value)
                if identifier is not None:
                    return ("ref", kind, identifier)
                match = re.fullmatch(r"com_(\d+)", value)
                if match:
                    return ("ref", kind, scope + ":" + match[1])
        return None

    def column(self, value, table):
        result = self.resolve("dbcolumn", value)
        if result:
            return result[2]
        identifier = self.columns.get(table, {}).get(unquote(value))
        if identifier is not None:
            return identifier
        match = re.fullmatch(r"(?:.*:)?col(\d+)(?::(\d+))?", unquote(value))
        if match and table is not None:
            return table + ":" + match[1] + ((":" + match[2]) if match[2] else "")
        return None

    def atom(self, value, kind, scope=None):
        if kind in {"unknown", "string", "int", "boolean", "type", "colour", "coord", "char", "long", "float"}:
            return ("literal", value)
        result = self.resolve(kind, value, scope)
        return result if result is not None else ("literal", value)

    def typed(self, value, declaration, scope=None):
        declaration = declaration.strip()
        if "[," in declaration:
            declaration = declaration.replace("[,", ",").replace("]", "")
        # Strings may contain commas and look exactly like symbols. Keep them.
        if declaration == "string" or declaration == "unknown":
            return ("literal", value)
        if declaration != "var_int" and "," not in declaration and "[" not in declaration and "|" not in declaration:
            return self.atom(value, declaration, scope)
        if declaration == "varbit | varplayer":
            candidates = {result for k in ("varbit", "varp")
                          if (result := self.resolve(k, value, scope)) is not None}
            return next(iter(candidates)) if len(candidates) == 1 else ("literal", value)
        if declaration == "var_int":
            candidates = {result for kind in self.names if kind.startswith("var")
                          if (result := self.resolve(kind, value, scope)) is not None}
            # A generic fallback can name a domain absent from exported tables.
            match = re.fullmatch(r"([a-z]+)_(\d+)", unquote(value))
            if match and self.kind(match[1]).startswith("var"):
                candidates.add(("ref", self.kind(match[1]), match[2]))
            return next(iter(candidates)) if len(candidates) == 1 else ("literal", value)
        declarations = [part.strip() for part in declaration.split(",")]
        parts = split_values(value)
        result = []
        for index, part in enumerate(parts):
            subtype = declarations[min(index, len(declarations) - 1)]
            subtype = subtype.replace("[, int]", "").removesuffix("[]")
            if ("|" in subtype and subtype != "varbit | varplayer") or "[" in subtype:
                subtype = "unknown"
            result.append(self.typed(part, subtype, scope) if subtype == "varbit | varplayer" else self.atom(part, subtype, scope))
        return tuple(result)

    def phrase(self, value):
        commands = {"listdialog": ("enum",), "stat_base": ("stat",),
                    "enum_string": ("enum", "varp"), "enum_string_clan": ("enum",),
                    "tostring_varp": ("varp",), "tostring_varbit": ("varbit",),
                    "enum_string_statbase": ("enum", "stat"), "tostring_shared": ("varworld",),
                    "enum_string_varbit": ("enum", "varbit")}
        result, offset = [], 0
        for match in re.finditer(r"<([a-z_]+)\(([^<>()]*)\)>", value):
            types = commands.get(match[1])
            arguments = split_values(match[2])
            if types is None or len(types) != len(arguments):
                continue
            result.extend([value[offset:match.start()], (match[1], tuple(self.atom(arg, kind) for arg, kind in zip(arguments, types)))])
            offset = match.end()
        result.append(value[offset:])
        return tuple(result)

    def any_reference(self, token):
        if self._any is None:
            self._any = {}
            for kind, names in self.names.items():
                if kind in {"script_handler", "clientscript"}:
                    continue
                for name, identifier in names.items():
                    identity = ("ref", kind, identifier) if identifier is not None else None
                    if name in self._any and self._any[name] != identity:
                        self._any[name] = None
                    else:
                        self._any[name] = identity
        if token in self._any:
            return self._any[token]
        match = re.fullmatch(r"([A-Za-z]+)_(\d+)", token)
        if match and self.kind(match[1]) in self.names:
            return ("ref", self.kind(match[1]), match[2])
        return None

    def handler(self, value, record, field):
        """Resolve handler/script/reference tokens; preserve quoted arguments."""
        scope = record.id.split(":", 1)[0]
        trigger_type = {"onvartransmit": "varp", "onvarctransmit": "varc", "onvarcstrtransmit": "varc",
                        "oninvtransmit": "inv", "onstattransmit": "stat"}.get(field)
        result, offset, first = [], 0, True
        for match in re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_][A-Za-z_0-9]*(?::[A-Za-z_0-9]+)*', value):
            result.append(value[offset:match.start()])
            token = match[0]
            resolved = None
            if token[0] not in "\"'" and token not in {"true", "false", "null", "default", "none"} and not token.startswith("event_"):
                if first:
                    resolved = self.resolve("clientscript", token)
                elif trigger_type and "{" in value[:match.start()] and "}" not in value[value.rfind("{", 0, match.start()):match.start()]:
                    resolved = self.resolve(trigger_type, token)
                else:
                    candidates = {identity for identity in (self.resolve("component", token, scope), self.any_reference(token))
                                  if identity is not None}
                    resolved = next(iter(candidates)) if len(candidates) == 1 else None
            result.append(resolved if resolved is not None else token)
            offset, first = match.end(), False
        result.append(value[offset:])
        return tuple(result)

    def canonical_fields(self, record, kind):
        raw = record.fields()
        result = {}
        scope = record.id.split(":", 1)[0] if kind == "interface" else None
        for field, values in raw.items():
            key = field
            param = re.fullmatch(r"param\[(.*)\]", field)
            enum_value = re.fullmatch(r"val\[(.*)\]", field)
            if param:
                identity = self.resolve("param", param[1])
                key = ("param", identity if identity is not None else param[1])
                declaration = self.param_types.get(identity[2], "unknown") if identity else "unknown"
                normalized = tuple(self.typed(value, declaration, scope) for value in values)
            elif enum_value and kind == "enum":
                input_type = raw.get("inputtype", ("unknown",))[-1]
                output_type = raw.get("outputtype", ("unknown",))[-1]
                key = ("val", self.typed(enum_value[1], input_type))
                normalized = tuple(self.typed(value, output_type) for value in values)
            elif kind == "enum" and field == "default":
                normalized = tuple(self.typed(value, raw.get("outputtype", ("unknown",))[-1]) for value in values)
            elif kind == "param" and field == "default":
                normalized = tuple(self.typed(value, raw.get("type", ("unknown",))[-1]) for value in values)
            elif kind in {"dbrow", "dbtable"} and field in {"data", "column", "default"}:
                table = record.id if kind == "dbtable" else (self.resolve("dbtable", raw.get("table", ("",))[-1]) or (None, None, None))[2]
                entries = []
                for value in values:
                    parts = split_values(value)
                    column = self.column(parts[0], table)
                    if column is None:
                        entries.append(("literal", value))
                        continue
                    types = self.column_types.get(column, ())
                    entries.append((column, tuple(self.typed(part, types[i] if i < len(types) and field != "column" else "unknown")
                                                  for i, part in enumerate(parts[1:]))))
                normalized = tuple(entries)
            elif kind == "interface" and field.startswith("on"):
                normalized = tuple(self.handler(value, record, field) for value in values)
            elif kind == "quickchatphrase" and field == "phrase":
                normalized = tuple(self.phrase(value) for value in values)
            else:
                if field in TEXT_KEYS or re.fullmatch(r"(?:iop|op|membersop)\d+", field):
                    declaration = "string"
                elif (field == "material" and kind in {"billboard", "flo", "flu", "skybox"}) or (kind == "water" and field.startswith("normal_map_material")):
                    declaration = "material"
                elif field == "staticmodel" and kind == "skybox":
                    declaration = "model"
                elif kind == "stylesheet" and field == "parent":
                    declaration = "stylesheet"
                elif kind in {"interface", "stylesheet"} and (field == "textfont" or field.endswith(".textfont")):
                    declaration = "fontmetrics"
                elif kind == "varbit" and field == "basevar":
                    domain = raw.get("domain", ("",))[-1].replace("_", "")
                    declaration = {"player": "varp", "npc": "varn", "client": "varc", "object": "varobj",
                                   "clan": "varclan", "clansetting": "varclansetting", "shared": "varworld",
                                   "world": "varworld", "global": "varglobal", "region": "varregion",
                                   "playergroup": "varplayergroup"}.get(domain, "unknown")
                elif kind == "interface":
                    declaration = {"layer": "component", "model": "model", "modelanim": "seq",
                                   "graphic": "graphic", "stylesheet": "stylesheet"}.get(field, "unknown")
                    if re.fullmatch(r"opcursor\d+", field):
                        declaration = "cursor"
                else:
                    declaration = declared_type(kind, field)
                normalized = tuple(self.typed(value, declaration, scope) for value in values)
            if key in result:
                raise ValueError(f"{record.source}: duplicate normalized field {field} for ID {record.id}")
            result[key] = (field, values, normalized)
        return result


def is_reference(value):
    return isinstance(value, tuple) and len(value) == 3 and value[0] == "ref"


def same_known_identities(old, new):
    """For identical raw text, uncertainty alone is not evidence of a change."""
    if old == new:
        return True
    if is_reference(old) and is_reference(new):
        return False
    if is_reference(old) or is_reference(new):
        return True
    if isinstance(old, tuple) and isinstance(new, tuple) and len(old) == len(new):
        return all(same_known_identities(a, b) for a, b in zip(old, new))
    return False


def export_id(identifier):
    """Numeric config IDs are numbers; composite IDs retain their separators."""
    return int(identifier) if identifier.isdecimal() else identifier


def export_identity(value):
    if is_reference(value):
        return {"type": value[1], "id": export_id(value[2])}
    if isinstance(value, tuple):
        if len(value) == 2 and value[0] == "literal":
            return {"value": value[1]}
        return {"parts": [export_identity(part) for part in value]}
    return {"value": value}


def export_references(values):
    result = []

    def visit(value, index, path):
        if is_reference(value):
            result.append({"value_index": index, "path": path, **export_identity(value)})
        elif isinstance(value, tuple):
            for offset, part in enumerate(value):
                visit(part, index, path + [offset])

    for index, value in enumerate(values):
        visit(value, index, [])
    return result


def export_field_change(key, old_field, new_field, previous, current, old_value=(), new_value=()):
    identity = {"field": key} if isinstance(key, str) else {"field": key[0], "entry": export_identity(key[1])}
    return {"field": new_field or old_field, "identity": identity,
            "before_field": old_field or None, "after_field": new_field or None,
            "before": list(previous) if old_field else None,
            "after": list(current) if new_field else None,
            "before_references": export_references(old_value),
            "after_references": export_references(new_value)}


def normalized_changes(before, after, kind, old_index, new_index):
    """Export semantic field changes without altering the original source values."""
    old, new = old_index.canonical_fields(before, kind), new_index.canonical_fields(after, kind)
    if before.symbol != after.symbol:
        new_index.stats["ignored_record_names"] += 1
    result = []
    for key in sorted(old.keys() | new.keys(), key=str):
        old_field, previous, old_value = old.get(key, ("", (), ()))
        new_field, current, new_value = new.get(key, ("", (), ()))
        if old_value != new_value:
            if previous == current:
                if same_known_identities(old_value, new_value):
                    continue
            result.append(export_field_change(key, old_field, new_field, previous, current, old_value, new_value))
        elif old_field != new_field or previous != current:
            new_index.stats["ignored_reference_fields"] += 1
    return result
