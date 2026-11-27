"""Native fields from the pinned Var/MapElement/MSI/BAS/Seq/Spot/Hitmark/Headbar unpackers."""
import re

PAGES = frozenset({'varplayers', 'mapelements', 'mapsceneicons', 'animationsets',
                   'sequences', 'spoteffects', 'hitsplats', 'healthbars'})
PREVIEW_KEYS = {
    'cursors': ('graphic',),
    'mapelements': ('sprite', 'mouseovergraphic', 'flashsprite'),
    'mapsceneicons': ('graphic',),
    'hitsplats': ('classgraphic', 'leftgraphic', 'middlegraphic', 'rightgraphic'),
    'healthbars': ('full', 'empty', 'leftcapsprite', 'rightcapsprite'),
}
TYPES = {
    'varplayers': {'type':'type', 'scope':'variable scope', 'clientcode':'int', 'transmitlevel':'transmit mode',
                   'legacydefaultvalue':'boolean', 'wikisync':'boolean', 'pluginapi':'boolean'},
    'mapelements': {'sprite':'graphic', 'mouseovergraphic':'graphic', 'flashsprite':'graphic', 'worldmaparrow':'graphic',
                    'text':'string', 'textsize':'int', 'textcolour':'colour', 'textmouseovercolour':'colour',
                    'textbackgroundoutline':'colour', 'textbackgroundfill':'colour', 'show':'map visibility',
                    'mapfunction':'boolean', 'listable':'boolean', 'opbase':'string', 'category':'category',
                    'condition':'varbit | varplayer, int, int', 'condition2':'varbit | varplayer, int, int',
                    'multivar':'varbit | varplayer', 'multimel':'int | default, mapelement',
                    'polygonfill':'colour', 'polygonoutline':'colour', 'polygonoutlinedash':'int, int, int',
                    'textoffset':'int, int', 'minimapiconscale':'int', 'halign':'horizontal alignment', 'valign':'vertical alignment'},
    'mapsceneicons': {'graphic':'graphic', 'tint':'colour', 'resize':'boolean', 'hideonminimap':'boolean'},
    'animationsets': {'readyanim':'seq, seq', 'randomreadyanim':'seq, int', 'hillrotate':'int, int',
                      'hillrotatelimit':'int, int', 'turnspeed':'int', 'turnacceleration':'int', 'walkspeed':'int',
                      'overlayheight':'int', 'unknown27':'int, int, int, int, int, int, int', 'unknown28':'int',
                      'unknown31':'int', 'unknown32':'int', 'unknown33':'int', 'unknown34':'int', 'unknown35':'int',
                      'unknown36':'int', 'unknown43':'int', 'unknown44':'int', 'unknown53':'boolean',
                      'unknown55':'int, int', 'unknown56':'int, int, int, int'},
    'sequences': {'loops':'int', 'maxloops':'int', 'priority':'int', 'stretches':'boolean',
                  'replaceheldleft':'obj', 'replaceheldright':'obj', 'duplicatebehaviour':'duplicate behaviour',
                  'preanim_move':'animation movement mode', 'postanim_move':'animation movement mode',
                  'group':'seqgroup', 'keyframeset':'keyframeset', 'keyframerange':'int, int',
                  'walkmerge':'int[]', 'soundvolume':'int, int', 'soundrandomrate':'int, int, int',
                  'tertiaryvolumefactor':'int', 'unknown4':'int', 'unknown14':'boolean', 'unknown15':'boolean',
                  'unknown16':'boolean', 'unknown17':'int', 'unknown23':'int', 'unknown27':'int'},
    'spoteffects': {'anim':'seq', 'model':'model', 'resizeh':'int', 'resizev':'int', 'rotation':'int',
                    'ambient':'int', 'contrast':'int', 'allowloop':'boolean', 'castsshadows':'boolean',
                    'hasalpha':'boolean', 'hillchange':'hill skew mode[, int]'},
    'hitsplats': {'damagefont':'fontmetrics', 'damagecolour':'colour', 'classgraphic':'graphic',
                  'leftgraphic':'graphic', 'middlegraphic':'graphic', 'rightgraphic':'graphic',
                  'scrolltooffsetx':'int', 'scrolltooffsety':'int', 'damageformat':'string', 'sticktime':'int',
                  'fadeout':'int | no', 'replacemode':'int', 'damageyof':'int', 'graphicof':'int, int',
                  'multivar':'varbit | varplayer', 'multimark':'int | default, hitmark',
                  'damagescaleto':'int', 'damagescalefrom':'int'},
    'healthbars': {'showpriority':'int', 'hidepriority':'int', 'sticktime':'int', 'fadeout':'int | no',
                   'full':'graphic', 'empty':'graphic', 'fullplayergroup':'graphic', 'emptyplayergroup':'graphic',
                   'fullplayergroupteam':'graphic', 'emptyplayergroupteam':'graphic', 'leftcapsprite':'graphic',
                   'rightcapsprite':'graphic', 'tilefill':'boolean', 'stackoffset':'int', 'unknown1':'int', 'unknown6':'int'},
}


def native_type(page, key):
    if page not in PAGES:
        return None
    if page == 'animationsets' and re.fullmatch(r'(?:readyanim|walkanim|runanim|crawlanim|walkturn|runturn|crawlturn)(?:_[blr])?', key) and key != 'readyanim':
        return 'seq'
    if page == 'sequences':
        if re.fullmatch(r'i?frame\d+', key): return 'animframe'
        if re.fullmatch(r'delay\d+', key): return 'int'
        if re.fullmatch(r'sound\d+', key): return 'sound, int, int, sound[]'
    if page == 'mapelements':
        if re.fullmatch(r'polygonpoint\d+', key): return 'int, int'
        if re.fullmatch(r'polygonoutline\d+', key): return 'colour'
        if re.fullmatch(r'op\d+', key): return 'string'
    if page == 'spoteffects':
        if re.fullmatch(r'recol(?:hsl)?\d+[sd]', key): return 'int'
        if re.fullmatch(r'retex\d+[sd]', key): return 'material'
    return TYPES[page].get(key, 'unknown')


def variable_type(browser, value):
    """The text format loses the domain; only link an unambiguous name."""
    value = browser.unquote(value)
    bit = value in browser.names.get('varplayerbits', {})
    player = value in browser.names.get('varplayers', {}) or value in browser.symbols.get('varplayer', {})
    return 'varbit' if bit and not player else 'varplayer' if player and not bit else ''


def native_values(browser, page, key, value, value_type, source, split_values):
    resolve = lambda part, kind: browser.resolve(part, kind, source)
    if value_type in {'model', 'category', 'stat'}:
        return [resolve(value, value_type)]
    if value_type == 'stat, int':
        return [resolve(part, 'stat' if i == 0 else 'int') for i, part in enumerate(split_values(value))]
    if value_type in {'loc shape, model', 'int, int, int, model'}:
        parts = split_values(value)
        return [resolve(part, 'model' if i == len(parts) - 1 else '') for i, part in enumerate(parts)]
    if key == 'multivar' and page in {'mapelements','hitsplats','npcs','scenery'}:
        return [resolve(value, variable_type(browser, value))]
    if page == 'mapelements' and key in {'condition', 'condition2'}:
        parts = split_values(value)
        return [resolve(part, variable_type(browser, part) if i == 0 else 'int') for i, part in enumerate(parts)]
    if (page, key) in {('mapelements','multimel'), ('hitsplats','multimark')}:
        kind = 'mapelement' if page == 'mapelements' else 'hitmark'
        return [resolve(part, kind if i == 1 else 'int') for i, part in enumerate(split_values(value))]
    if page == 'animationsets' and key in {'readyanim', 'randomreadyanim'}:
        return [resolve(part, 'seq' if i == 0 or key == 'readyanim' else 'int') for i, part in enumerate(split_values(value))]
    if page == 'scenery' and key == 'anim':
        return [resolve(part, 'seq' if i == 0 else 'int') for i, part in enumerate(split_values(value))]
    if page == 'quests' and key == 'masterquestvarp':
        return [resolve(part, 'varplayer' if i == 0 else 'int') for i, part in enumerate(split_values(value))]
    if page in PAGES:
        if value_type in {'seq','obj','graphic','category','model','seqgroup','keyframeset','animframe','fontmetrics','material'}:
            return [resolve(value, value_type)]
        return None
    if (page, key) in {('npcs','bas'), ('npcs','mapelement'), ('scenery','msi'), ('scenery','mapelement'), ('varplayerbits','basevar')}:
        return [resolve(value, value_type)]
    return None
