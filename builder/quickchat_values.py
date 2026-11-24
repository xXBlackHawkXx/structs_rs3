"""Resolve typed arguments in Quick Chat templates without executing them."""
import re

# QuickChatPhraseUnpacker.formatPhrase / unpackCommand in rs3-cache.
COMMAND_TYPES = {
    "listdialog": ("enum",),
    "stat_base": ("stat",),
    "enum_string": ("enum", "varplayer"),
    "enum_string_clan": ("enum",),
    "tostring_varp": ("varplayer",),
    "tostring_varbit": ("varbit",),
    "enum_string_statbase": ("enum", "stat"),
    "tostring_shared": ("varworld",),
    "enum_string_varbit": ("enum", "varbit"),
}


def phrase_value(browser, value, source=None):
    value = browser.unquote(value)
    parts = []
    offset = 0
    for match in re.finditer(r"<([a-z_]+)\(([^<>()]*)\)>", value):
        types = COMMAND_TYPES.get(match[1])
        arguments = match[2].split(",") if match[2] else []
        if types is None or len(arguments) != len(types):
            continue
        parts.append({"text": value[offset:match.start(2)]})
        for i, (argument, value_type) in enumerate(zip(arguments, types)):
            if i:
                parts.append({"text": ","})
            parts.append(browser.resolve(argument.strip(), value_type, source))
        parts.append({"text": ")>"})
        offset = match.end()
    parts.append({"text": value[offset:]})
    return {"kind": "inline", "values": parts}
