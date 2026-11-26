"""Additional historical field types from the pinned config unpackers."""
import re

PAGES = frozenset({'varplayers', 'mapelements', 'mapsceneicons', 'animationsets',
                   'sequences', 'spoteffects', 'hitsplats', 'healthbars'})
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

