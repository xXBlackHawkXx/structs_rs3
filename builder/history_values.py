"""Use viewer parsers with snapshot context and explicitly recorded historical IDs."""
from .build import BrowserData, FILES, TYPE_PAGES, split_values, unquote
from .field_types import native_field_type


class HistoricalBrowser(BrowserData):
    def __init__(self, page, key, value, references):
        self.records = {page:{} for page in FILES}
        self.names = {page:{} for page in FILES}
        self.symbols = {}
        self.params = {}
        self.previews = {}
        self.bindings = []
        self.data_index = 0 if page == 'dbrows' and key == 'data' else None
        parts = split_values(value)
        requirements = page == 'achievements' and key in {
            'statreq','statprereq','varpreq','varpprereq','varbitreq','varbitprereq'}
        for offset, ref in enumerate(references):
            path = ref.get('path', [])
            name = None
            if not path:
                name = value
            elif requirements:
                # Requirement labels may contain unquoted commas; references form a suffix.
                if len(parts) >= 3 + len(references):
                    name = parts[len(parts) - len(references) + offset]
            elif page == 'dbrows' and key == 'data' and len(path) == 2 and path[0] == 1:
                index = 1 + path[1]
                if 0 <= index < len(parts):
                    name = parts[index]
            elif len(path) == 1 and 0 <= path[0] < len(parts):
                name = parts[path[0]]
            if name is None:
                continue
            name = unquote(name)
            self.bindings.append((name, ref))
            target = TYPE_PAGES.get(ref['type'])
            if target:
                self.names.setdefault(target, {})[name] = ref['id']
            else:
                self.symbols.setdefault(ref['type'], {})[name] = ref['id']

    def resolve(self, value, value_type, source=None):
        text = unquote(value)
        target = TYPE_PAGES.get(value_type)
        position = None
        if self.data_index is not None and not value_type:
            position = self.data_index
            self.data_index += 1
        for index, (name, ref) in enumerate(self.bindings):
            if name != text:
                continue
            if position is not None and ref.get('path') != [1,position]:
                continue
            if value_type and not (ref['type'] == value_type or target and TYPE_PAGES.get(ref['type']) == target):
                continue
            self.bindings.pop(index)
            page = TYPE_PAGES.get(ref['type'])
            if page:
                return {'type':page, 'id':ref['id'], 'text':text}
            if ref['type'] == 'graphic':
                return {'kind':'image', 'src':f'https://chisel.weirdgloop.org/static/img/rs3-graphic/{ref["id"]}-0.png', 'text':text}
            return {'text':text}
        # Coordinates and explicitly numeric graphics can be decoded without looking up names.
        if value_type in {'coord','graphic'}:
            return super().resolve(value,value_type)
        return {'text':text}


def parsed_values(page, key, values, references, snapshot, field_label=None):
    if values is None:
        return None
    result = []
    context = [(key,value) for key,values in snapshot.get('fields',{}).items()
               if key in {'type','inputtype','outputtype','domain','column','table'} for value in values]
    for index, value in enumerate(values):
        refs = [ref for ref in references if ref.get('value_index',0) == index]
        browser = HistoricalBrowser(page,key,value,refs)
        raw = value
        # Semantic param/enum changes omit their entry key; restore it for the normal parser.
        if key in {'param','val'} and field_label and field_label.startswith(key + '[') and field_label.endswith(']'):
            entry = field_label[len(key) + 1:-1]
            raw = f'{entry},{value}'
            if key == 'param':
                scalar = [ref for ref in refs if not ref.get('path')]
                value_type = scalar[0]['type'] if len(scalar) == 1 else 'unknown'
                browser.params[entry] = {'id':0,'fields':[['type',value_type]]}
        record = {'id':snapshot.get('id',0),'name':snapshot.get('config_name',''),
                  'fields':[(k,v) for k,v in context if k != key] + [(key,raw)]}
        parts = browser.rows(page,record,collect=False)[-1]['parsed']
        # A historical scalar reference is authoritative even when its declared type isn't present.
        if len(refs) == 1 and not refs[0].get('path'):
            parts = [browser.resolve(value,refs[0]['type'])] if browser.bindings else parts
        elif native_field_type(page,key,record) == 'coord':
            parts = [browser.resolve(value,'coord')]
        if len(parts) == 1:
            result.append(parts[0])
        else:
            joined = []
            for part in parts:
                if joined:
                    joined.append({'text':', '})
                joined.append(part)
            result.append({'kind':'inline','values':joined})
    return result
