"""Native text field types, independent of Google Sheets and runtime downloads.

Definitions checked against zwyz/rs3-cache's config unpackers at commit
59b566a22a9ea537c26e99701837c2c5cce4871e, src/main/java/rs3/unpack/config/.
These describe individual text dump fields, not the old viewer's grouped opcodes.
"""
import re
from .extra_configs import native_type as extra_native_type

SOURCE = "https://github.com/zwyz/rs3-cache/tree/59b566a22a9ea537c26e99701837c2c5cce4871e/src/main/java/rs3/unpack/config"

FLAGS = set("""active alwaysonbottom alwaysontop antimacro castsshadows certtradeable
checklist disable familiar fastpicking locked members minimap placeholder pluginapi
randomposition reprioritiseattackop spotshadow stockmarket tradeable walksmoothing
wikisync autodisable transmogfakenpc""".split())

INTEGERS = set("""2dxan 2dxof 2dyan 2dyof 2dzan 2dzoom ambient contrast cost
dummyitem picksizeshift resizex resizey resizez shardcount stockmarketlimit team
bodypart size maxrange vislevel wanderrange respawndir turnspeed resizeh resizev
multidefault bgsoundvolume overlayheight highlightoverride roughbounding priorityoffset
unknown119 runescore graceday hide numprereqgroupstocomplete numreqgroupstocomplete
prereqitemstocomplete reqgroupitemstocomplete questpoints qpreq startbit endbit""".split())


def native_field_type(page, key, record=None):
    """Return a declared semantic type; keep unrecognised future fields explicit."""
    extra = extra_native_type(page, key)
    if extra is not None:
        return extra
    if page == "quickchatcategories":
        return {"desc":"string", "subcat":"chatcat, int", "phrase":"chatphrase, int", "searchable":"boolean"}.get(key, "unknown")
    if page == "quickchatphrases":
        return {"phrase":"string", "autoresponse":"chatphrase", "searchable":"boolean"}.get(key, "unknown")
    if page == "cursors":
        return {"graphic":"graphic","hotspot":"int, int"}.get(key,"unknown")
    if page == "scenery":
        if key in {'blockwalk','blockrange','hillskew','sharelight','occlude','mirror','shadow','forcedecor','breakroutefinding','raiseobject','istexture','hardshadow','randomanimframe','msirotate','msimirror','hasparticles','findable','runetek5only','highdetailonly','unknown90','unknown96','unknown108','unknown109','unknown110','unknown111','unknown177','unknown179','bgsounddistancefiltered','randomsounddistancefiltered'}:
            return 'boolean'
        if key in {'width','length','wallwidth','offsetx','offsety','offsetz','postoffsetx','postoffsety','postoffsetz','raiseobjectgrounddecor','raiseentities','indoorsoverride','msiangle','unknown170','unknown171','bgsounddropoffrange','bgsoundshape','randomsoundshape','mapfunction','mapscene'}:
            return 'int'
        types = {'model':'loc shape, model', 'modelhd':'loc shape, model', 'modelsd':'loc shape, model',
                 'anim':'seq[, int]', 'forceapproach':'direction[]', 'multiloc':'int | default, loc',
                 'multivar':'varbit | varplayer', 'multidefault':'int', 'bgsound':'sound, int',
                 'randomsound':'int, int, int, sound[]', 'hillchange':'hill skew mode[, int]',
                 'msi':'mapsceneicon', 'mapelement':'mapelement', 'quest':'quest[]',
                 'bgsoundrate':'int, int', 'tint':'int, int, int, int', 'custombounding':'int, int, int, int, int, int',
                 'minimumlodleveloverride':'level of detail', 'multimodel':'int, int, int, model',
                 'multiheadmodel':'int, int, int, model', 'multiretex':'int, int, int, material, material',
                 'multirecol':'int, int, int, int, int', 'multitint':'int, int, int, int, int, int',
                 'vfx':'vfx, int, float, float, float, float, float, float',
                 'pointlight':'boolean, boolean, boolean, float, float, float, int, float, colour, light, int, float, float, float',
                 'bgsounddistancefilterparams':'int, int, int','randomsounddistancefilterparams':'int, int, int'}
        if key in types:
            return types[key]
    if key in FLAGS:
        return "boolean"
    if key in INTEGERS or re.fullmatch(r"recol(?:hsl)?\d+[sd]", key):
        return "int"
    if key in {"name", "sortname", "reward", "shardname"} or re.fullmatch(r"(?:iop|op|membersop)\d+", key):
        return "string"
    if key == "desc":
        return "int, string" if page == "achievements" else "string"
    if re.fullmatch(r"(?:model\d*|head\d+|(?:man|woman)(?:head|wear)\d*)", key):
        return "model"
    if re.fullmatch(r"(?:i?cursor\d+|cursorattack)", key):
        return "cursor"
    if re.fullmatch(r"retex\d+[sd]", key):
        return "material"
    if key in {"category", "subcat"}:
        return "category"
    if key in {"certlink", "certtemplate", "lentlink", "lenttemplate", "boughtlink", "boughttemplate", "shardlink", "shardtemplate", "plantemplate"}:
        return "obj"
    if re.fullmatch(r"(?:count|stock)\d+", key):
        return "obj, int"
    if re.fullmatch(r"wearpos\d*", key):
        return "wearpos"
    if key == "stackable":
        return "stackability"
    if key in {"manwearoff", "womanwearoff"} or re.fullmatch(r"modeloffset\d+", key):
        return "int, int, int"
    if key in {"sprite", "icon"}:
        return "graphic"
    if re.fullmatch(r"headicon\d+", key):
        return "graphic, int"
    if key in {"mainstartcoord", "startcoord", "viacoord"}:
        return "coord"
    if key == "table":
        return "dbtable"
    if key == "dbrow":
        return "dbrow"
    if page == "achievements":
        if key in {"achievementreq", "achievementprereq"}:
            return "int, achievement"
        if key in {"questreq", "questprereq"}:
            return "int, quest"
        if key in {"statreq", "statprereq", "varpreq", "varpprereq", "varbitreq", "varbitprereq"}:
            target = "stat" if key.startswith("stat") else "varbit" if key.startswith("varbit") else "varplayer"
            return f"int, int, string, {target}[]"
        if key in {"varbittestbitreq", "varbittestbitprereq", "varptestbitreq", "varptestbitprereq"}:
            target = "varbit" if key.startswith("varbit") else "varplayer"
            return f"int, {target}, int, string, int"
        if key == "tally":
            return "int, int, int"
    if page == "quests":
        return {"type": "quest type", "difficulty": "quest difficulty", "parent": "quest",
                "questreq": "quest", "statreq": "stat, int", "masterquestvarbit": "varbit, int, int",
                "masterquestvarp": "varplayer, int, int"}.get(key, "unknown")
    if page == "items" and key == "quest":
        # ObjUnpacker writes an unformatted g2 here, not a named quest config.
        return "int"
    if page == "npcs":
        return {"bas": "bas", "mapelement": "mapelement", "quest": "quest[]",
                "defaultmovemode": "movement mode", "multivar": "varbit | varplayer",
                "multinpc": "int | default, npc", "multimodel": "int, int, int, model",
                "multiheadmodel": "int, int, int, model", "multirecol": "int, int, int, int, int",
                "multiretex": "int, int, int, material, material", "bgsound": "sound, sound, sound, sound, int",
                "bgsoundrate": "int, int", "spotshadowcolour": "int, int", "spotshadowtrans": "int, int",
                "tint": "int, int, int, int", "custombounding": "int, int, int, int, int, int"}.get(key, "unknown")
    if page == "varplayerbits":
        if key == "domain":
            return "var domain"
        if key == "basevar":
            domain = next((v for k, v in record["fields"] if k == "domain"), "unknown") if record else "unknown"
            return {"player": "varplayer", "npc": "varnpc", "client": "varclient", "object": "varobj", "clan": "varclan", "clansetting": "varclansetting", "shared": "varshared"}.get(domain, f"var ({domain})")
    if (page == "params" and key == "type") or (page == "enums" and key in {"inputtype", "outputtype"}):
        return "type"
    if page == "dbtables" and key == "column":
        return "dbcolumn, type[]"
    return "unknown"
