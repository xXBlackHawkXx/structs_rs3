"""Decode achievement tuples emitted by AchievementUnpacker, without Sheets."""
import re


def requirement_table(headers, cells):
    return [{"kind": "table", "headers": headers, "rows": [cells]}]


def achievement_value(browser, key, value, source):
    """Return a structured parsed value, or None for ordinary scalar fields."""
    text = lambda v: {"text": v}
    if key == "desc":
        _, separator, description = value.partition(",")
        return [text(description if separator else value)]
    if key in {"achievementreq", "achievementprereq", "questreq", "questprereq"}:
        group, separator, target = value.partition(",")
        if not separator:
            return None
        target_type = "achievement" if key.startswith("achievement") else "quest"
        return requirement_table(["group", target_type], [text(group), browser.resolve(target, target_type, source)])
    list_types = {"varbitreq": "varbit", "varbitprereq": "varbit", "varpreq": "varplayer",
                  "varpprereq": "varplayer", "statreq": "stat", "statprereq": "stat"}
    if key in list_types:
        parts = value.split(",", 2)
        if len(parts) != 3:
            return None
        group, required, remainder = parts
        target_type = list_types[key]
        target_page = {"varbit":"varplayerbits", "varplayer":"varplayers", "stat":"stats"}.get(target_type)
        names = browser.names.get(target_page, {}) or browser.symbols.get(target_type, {})
        targets = []
        # Labels can contain unquoted commas. Known reference names form a suffix.
        # Preserve the label verbatim rather than treating its words as references.
        while "," in remainder:
            label, _, candidate = remainder.rpartition(",")
            numeric = re.fullmatch(r"-?\d+", candidate)
            if candidate not in names and not (numeric and target_page and int(candidate) in browser.records.get(target_page, {})):
                break
            targets.insert(0, browser.resolve(candidate, target_type, source))
            remainder = label
        return requirement_table(["group", "value", "name", target_type + "s"],
                                 [text(group), text(required), text(browser.unquote(remainder)), {"kind": "list", "values": targets}])
    test_types = {"varbittestbitreq": "varbit", "varbittestbitprereq": "varbit",
                  "varptestbitreq": "varplayer", "varptestbitprereq": "varplayer"}
    if key in test_types:
        parts = value.split(",", 3)
        if len(parts) != 4 or "," not in parts[3]:
            return None
        group, target, required, tail = parts
        label, _, bit = tail.rpartition(",")
        target_type = test_types[key]
        return requirement_table(["group", "value", "name", target_type, "bit"],
                                 [text(group), text(required), text(browser.unquote(label)), browser.resolve(target, target_type, source), text(bit)])
    return None
