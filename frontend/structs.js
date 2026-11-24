"use strict";
(() => {
  const types = ['params', 'achievement_params', 'achievements', 'cursor_params', 'cursors', 'dbtables', 'dbrows', 'idkit_params', 'idkits', 'inv_params', 'invs', 'item_params', 'items', 'npc_params', 'npcs', 'scenery_params', 'scenery', 'structs', 'enums', 'quest_params', 'quests', 'quickchatcategories', 'quickchatphrases', 'varplayerbit_params', 'varplayerbits', 'varplayers', 'mapelements', 'mapsceneicons', 'animationsets', 'sequences', 'spoteffects', 'hitsplats', 'healthbars'];
  const extraConfigTypes = {varplayers:'varp',mapelements:'mel',mapsceneicons:'msi',animationsets:'bas',sequences:'seq',spoteffects:'spot',hitsplats:'hitmark',healthbars:'headbar'};
  const previewPages = ['cursors','mapelements','mapsceneicons','hitsplats','healthbars'];
  const fieldPages = {achievements:'achievement_params',idkits:'idkit_params',invs:'inv_params',items:'item_params',npcs:'npc_params',quests:'quest_params',varplayerbits:'varplayerbit_params',scenery:'scenery_params',cursors:'cursor_params'};
  const configTypes = {params:'param',achievements:'achievement',dbtables:'dbtable',dbrows:'dbrow',idkits:'idkit',invs:'inv',items:'item',npcs:'npc',structs:'struct',enums:'enum',quests:'quest',varplayerbits:'varbit',scenery:'object',cursors:'cursor',quickchatcategories:'quickchatcat',quickchatphrases:'quickchatphrase'};
  const typeLabels = {params:'CS2 parameters',achievement_params:'Achievement fields',achievements:'Achievements',dbtables:'Database tables',dbrows:'Database rows',idkit_params:'Identity kit fields',idkits:'Identity kits',inv_params:'Inventory fields',invs:'Inventories',item_params:'Item fields',items:'Items',npc_params:'NPC fields',npcs:'NPCs',structs:'Structs',enums:'Enums',quest_params:'Quest fields',quests:'Quests',varplayerbit_params:'Varbit fields',varplayerbits:'Varbits',scenery:'Scenery',scenery_params:'Scenery fields',cursors:'Cursors',cursor_params:'Cursor fields',quickchatcategories:'Quick Chat categories',quickchatphrases:'Quick Chat phrases'};
  Object.assign(configTypes, extraConfigTypes);
  Object.assign(typeLabels, {varplayers:'Player variables',mapelements:'Map elements',mapsceneicons:'Map scene icons',animationsets:'Animation sets',sequences:'Animation sequences',spoteffects:'Spot effects',hitsplats:'Hitsplats',healthbars:'Health bars'});
  const isCs2Param = row => row.kind === 'param' || row.param !== undefined;
  const main = document.getElementById('main');
  const query = new URLSearchParams(location.search);
  const page = query.get('type');
  const id = query.get('id');
  const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
  const number = n => Number(n).toLocaleString();
  let manifest;
  let keyLabels;
  let cursorPreviews;
  function readableWords(value) {
    const words = String(value).replace(/([a-z])([A-Z])/g, '$1 $2').split(/[_\s]+/).filter(Boolean).map(word => {
      if (keyLabels.words[word.toLowerCase()]) return keyLabels.words[word.toLowerCase()];
      const numbered = word.match(/^([a-z]+)(\d+)$/i);
      return numbered ? (keyLabels.words[numbered[1].toLowerCase()] || numbered[1]) + ' ' + numbered[2] : word;
    }).join(' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  function readableKey(row) {
    const key = String(row.key_name ?? row.key);
    const owner = page.endsWith('_params') ? Object.keys(fieldPages).find(type => fieldPages[type] === page) : page;
    const shared = isCs2Param(row) || page === 'params';
    const exact = (!shared && keyLabels.pages[owner]?.[key]) || keyLabels.common[key];
    if (exact) return exact;
    if (/^param_\d+$/.test(key) && keyLabels.parameters[key]) return readableWords(keyLabels.parameters[key]);
    let match;
    if (owner === 'sequences' && (match = key.match(/^(frame|iframe|delay|sound)(\d+)$/))) return `${{frame:'Animation frame',iframe:'Secondary animation frame',delay:'Frame delay',sound:'Frame sound'}[match[1]]} ${match[2]}`;
    if (owner === 'mapelements' && (match = key.match(/^(polygonpoint|polygonoutline)(\d+)$/))) return `${match[1] === 'polygonpoint' ? 'Polygon point' : 'Polygon outline'} ${match[2]}`;
    if (owner === 'animationsets' && (match = key.match(/^(readyanim|walkanim|runanim|crawlanim|walkturn|runturn|crawlturn)(?:_([blr]))?$/))) return `${{readyanim:'Idle animation',walkanim:'Walk animation',runanim:'Run animation',crawlanim:'Crawl animation',walkturn:'Walk turn animation',runturn:'Run turn animation',crawlturn:'Crawl turn animation'}[match[1]]}${match[2] ? ' (' + {b:'backwards',l:'left',r:'right'}[match[2]] + ')' : ''}`;
    if ((match = key.match(/^recol(hsl)?(\d+)([sd])$/))) return `${match[3] === 's' ? 'Original' : 'Replacement'} ${match[1] ? 'HSL ' : ''}colour ${match[2]}`;
    if ((match = key.match(/^retex(\d+)([sd])$/))) return `${match[2] === 's' ? 'Original' : 'Replacement'} texture ${match[1]}`;
    if ((match = key.match(/^(man|woman)(wear|head)(\d*)$/))) return `${match[1] === 'man' ? 'Male' : 'Female'} ${match[2] === 'wear' ? 'worn' : 'head'} model ID${match[3] ? ' ' + match[3] : ''}`;
    if ((match = key.match(/^(model|head|modeloffset|headicon)(\d+)$/))) return `${{model:'Model ID',head:'Head model ID',modeloffset:'Model offset',headicon:'Head icon'}[match[1]]} ${match[2]}`;
    if ((match = key.match(/^(op|iop|membersop|cursor|icursor|stock|count|wearpos|col|objvar)(\d+)$/))) {
      const labels = {op:owner === 'items' ? 'Ground action' : 'Action',iop:'Inventory action',membersop:'Members action',cursor:'Ground action cursor',icursor:'Inventory action cursor',stock:'Base stock',count:'Stack variant',wearpos:'Equipment slot',col:'Column',objvar:'Item variable'};
      return `${labels[match[1]]} ${match[2]}`;
    }
    if (key === 'wearpos') return 'Equipment slot 1';
    if ((match = key.match(/^stat(attack|strength|defence|constitution|ranged|magic|prayer|summoning|herblore|slayer|necromancy)$/))) return `${readableWords(match[1])} skill`;
    return readableWords(key);
  }
  function el(tag, text, attrs = {}) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  }
  function url(type, id) {
    const q = new URLSearchParams({type});
    if (id !== undefined) q.set('id', id);
    return `index.html?${q}`;
  }
  function link(type, id, text) {
    const target = el('a', text ?? id, {href: url(type, id)});
    const iconType = {structs:'struct', dbrows:'dbrow', achievements:'achievement', enums:'enum', quests:'quest', npcs:'npc'}[type];
    if (iconType && id !== undefined) {
      const icon = el('img', null, {class:'struct-icon', src:`https://chisel.weirdgloop.org/structs_rs3/images/${iconType}-icon.png`, alt:'', width:'11', height:'11', loading:'lazy'});
      icon.onerror = () => { icon.hidden = true; };
      target.prepend(icon);
    }
    return target;
  }
  function navigation() {
    const select = el('select', null, {id:'config-type', 'aria-label':'Browse config type'});
    select.append(el('option', 'Choose a config type', {value:''}));
    for (const [label, isField] of [['Game configs',false],['Parameters and fields',true]]) {
      const group = el('optgroup', null, {label});
      for (const type of types.filter(type => (type === 'params' || type.endsWith('_params')) === isField)) group.append(el('option', typeLabels[type], {value:type}));
      select.append(group);
    }
    select.value = types.includes(page) ? page : '';
    select.onchange = () => { location.href = select.value ? url(select.value) : 'index.html'; };
    const controls = document.getElementById('nav');
    controls.append(el('label', 'Browse', {for:'config-type'}), select);
    if (types.includes(page) && id !== null) {
      const browse = link(page, undefined, 'Browse all');
      browse.className = 'browse-all';
      browse.setAttribute('aria-label', `Browse all ${typeLabels[page].toLowerCase()}`);
      controls.append(browse);
    }
    if (!types.includes(page)) return;
    const breadcrumbs = document.getElementById('breadcrumbs');
    const trail = el('ol');
    const home = el('li'); home.append(el('a', 'Config index', {href:'index.html'})); trail.append(home);
    const collection = el('li');
    if (id === null) collection.append(el('span', typeLabels[page], {'aria-current':'page'}));
    else collection.append(link(page, undefined, typeLabels[page]));
    trail.append(collection);
    if (id !== null) {
      const current = el('li');
      current.append(el('span', page.endsWith('_params') ? readableKey({key_name:id}) : `#${id}`, {'aria-current':'page', title:id}));
      trail.append(current);
    }
    breadcrumbs.replaceChildren(trail); breadcrumbs.hidden = false;
  }
  function configShortcuts(data) {
    const fieldPage = page.endsWith('_params');
    const owner = fieldPage ? Object.keys(fieldPages).find(type => fieldPages[type] === page) : page;
    const configType = configTypes[owner];
    const typeLabel = fieldPage ? `${configType} field` : configType;
    const name = data.display || data.rows.find(row => !row.parsedKey && row.key === 'name')?.raw || data.name || `${typeLabel} ${id}`;
    const showLinks = ['items','achievements','scenery','quests','structs'].includes(page);
    const shortcuts = el('div', null, {class: showLinks ? 'config-shortcuts' : 'config-graphic', role: 'group', 'aria-label': `${typeLabel} ${showLinks ? 'links' : 'preview'}`});
    if (page === 'items') {
      const icon = el('img', null, {src: `https://chisel.weirdgloop.org/gazproj/icons/png/${id}.png`, alt: `${name} icon`});
      icon.onerror = () => { icon.hidden = true; };
      shortcuts.append(icon);
    } else {
      const sprite = data.preview?.kind === 'image' ? data.preview : data.rows.find(row => ['sprite','icon','graphic'].includes(row.key))?.parsed.find(value => value.kind === 'image');
      if (sprite) {
        const icon = el('img', null, {src: sprite.src, alt: `${name} icon`});
        icon.onerror = () => { icon.hidden = true; };
        shortcuts.append(icon);
      }
    }
    if (!showLinks) return shortcuts.childNodes.length ? shortcuts : document.createDocumentFragment();
    const wiki = 'https://runescape.wiki/w/';
    const search = text => wiki + 'Special:Search?' + new URLSearchParams({search:text});
    const wikiName = page === 'varplayerbits' ? `RuneScape:Varbit/${id}` : fieldPage ? `${configType} ${name} field` : name;
    const tool = {items:'mrid',npcs:'mrnd',scenery:'mrod'}[page];
    const cursorGraphic = data.preview?.kind === 'image' ? data.preview : data.rows.find(row => row.key === 'graphic')?.parsed.find(value => value.kind === 'image');
    const cursorTarget = cursorGraphic?.src || `https://github.com/${manifest.repository}/blob/${manifest.revision}/config/dump.cursor`;
    const quickchat = ['quickchatcategories','quickchatphrases'].includes(owner);
    const sourceDump = quickchat || Object.hasOwn(extraConfigTypes, owner);
    const chisel = sourceDump ? `https://github.com/${manifest.repository}/blob/${manifest.revision}/config/dump.${configType}` : tool ? `https://chisel.weirdgloop.org/gazproj/${tool}?${id}#${Number(id) - 15}-${Number(id) + 15}` : owner === 'cursors' ? cursorTarget : owner === 'scenery' ? 'https://chisel.weirdgloop.org/gazproj/mrod' : `https://chisel.weirdgloop.org/structs_rs3/${fieldPage ? 'index.html?' + new URLSearchParams({type:page}) : url(page,id)}`;
    const property = {items:'All Item ID',npcs:'All NPC ID'}[page];
    const idSearch = property ? wiki + 'Special:SearchByProperty?' + new URLSearchParams({limit:'20',property,value:id}) : search(`${typeLabel} "${id}"`);
    const targets = [
      ['m', chisel, sourceDump ? 'Open source config dump' : tool ? `Lookup this ID in ${tool.toUpperCase()}` : owner === 'cursors' ? cursorGraphic ? 'Open cursor graphic' : 'Open cursor config dump' : owner === 'scenery' ? 'Browse scenery in MROD' : fieldPage ? 'Browse this field type in Chisel' : 'Open this config in Chisel'],
      ['p', fieldPage ? search(wikiName) : wiki + encodeURIComponent(wikiName.replaceAll(' ', '_')), fieldPage ? 'Find wiki documentation for this field' : 'Go to this wiki page'],
      ['s', search(fieldPage ? wikiName : name), 'Search the wiki for this name'],
      ['l', fieldPage ? search(wikiName) : wiki + 'Special:Lookup?' + new URLSearchParams({type:configType,id,name:wikiName}), fieldPage ? 'Find wiki documentation for this field' : 'Wiki lookup by ID (falls back to name)'],
      ['i', idSearch, `Search the wiki for this ${typeLabel} ${fieldPage ? 'name' : 'ID'}`],
    ];
    for (const [label, href, title] of targets) shortcuts.append(el('a', label, {href, title, 'aria-label': title, target: '_blank', rel: 'noopener noreferrer'}));
    return shortcuts;
  }
  async function json(path) {
    const compressed = manifest?.compression === 'gzip' && path.startsWith('data/') && path !== 'data/manifest.json';
    const target = compressed ? path + '.gz' : path;
    const response = await fetch(target);
    if (!response.ok) throw new Error(`Could not load ${target} (HTTP ${response.status}).`);
    if (compressed) {
      if (typeof DecompressionStream !== 'function') throw new Error('Please use a current browser to read this compressed cache data.');
      return new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).json();
    }
    return response.json();
  }
  function parsed(value) {
    if (!value) return el('span', '');
    if (value.kind === 'inline') {
      const span = el('span');
      value.values.forEach(part => span.append(parsed(part)));
      return span;
    }
    if (value.kind === 'list') {
      const list = el('span');
      value.values.forEach((item, i) => { if (i) list.append(el('br')); list.append(parsed(item)); });
      return list;
    }
    if (value.kind === 'table') {
      const view = table(value.headers);
      view.table.classList.add('parsed-table');
      for (const cells of value.rows) {
        const row = view.body.insertRow();
        cells.forEach(cell => row.insertCell().append(parsed(cell)));
      }
      return view.wrapper;
    }
    if (value.kind === 'image') {
      const span = el('span', null, {class:'graphic-value'});
      const image = el('img', null, {src:value.src, alt:value.text, loading:'lazy'});
      image.onerror = () => { image.hidden = true; };
      span.append(image, el('span', value.text, {class:'muted'}));
      return span;
    }
    if (value.type) {
      const target = link(value.type, value.id, `${value.id}: ${value.text}`);
      const preview = value.type === 'items' ? `https://chisel.weirdgloop.org/gazproj/icons/png/${value.id}.png` : value.type === 'cursors' ? cursorPreviews.get(Number(value.id)) : value.preview?.kind === 'image' ? value.preview.src : null;
      if (preview) {
        const span = el('span',null,{class:value.type === 'items' ? 'stock-parsed-item' : value.type === 'cursors' ? 'cursor-reference' : 'config-reference'});
        const image = el('img',null,{src:preview,alt:'',width:'32',height:'32',loading:'lazy'});
        image.onerror = () => { image.hidden = true; };
        span.append(image,target);
        return span;
      }
      return target;
    }
    return el('span', value.text);
  }
  function achievementRows(rows) {
    const out = [], groups = new Map();
    for (const row of rows) {
      if (row.group !== 'achievement-requirements') { out.push(row); continue; }
      if (!groups.has(row.key)) {
        const grouped = {...row, raw:'', parsed:[{...row.parsed[0], rows:[]}]};
        groups.set(row.key, grouped); out.push(grouped);
      }
      const grouped = groups.get(row.key);
      grouped.raw += (grouped.raw ? '\n' : '') + row.raw;
      grouped.parsed[0].rows.push(...row.parsed[0].rows);
    }
    return out;
  }
  async function databaseRows(data) {
    const refs = data.dbrows || [];
    main.append(el('h2', `Database rows (${number(refs.length)})`));
    if (!refs.length) { main.append(el('p', 'This table has no database rows.', {class:'muted'})); return; }
    const columns = data.rows.filter(row => row.key === 'column').map(row => {
      const [key, ...types] = row.raw.split(',').map(part => part.trim());
      return {key, types, split:['obj,int','dbrow,int'].includes(types.join(','))};
    });
    const view = table(['Row', ...columns.map(column => readableKey(column))]);
    view.table.classList.add('database-rows');
    columns.forEach((column, i) => {
      const cell = view.head.cells[i + 1];
      cell.dataset.column = column.key;
      cell.title = column.key;
      cell.append(el('span', column.types.join(', '), {class:'db-column-type'}));
      if (column.split) { cell.colSpan = 2; cell.scope = 'colgroup'; }
    });
    if (columns.length) main.append(el('p', 'null = no explicit value; see the table defaults above.', {class:'muted'}));
    const controls = el('div', null, {class:'pagination'});
    const previous = el('button', 'Previous', {type:'button'});
    const next = el('button', 'Next', {type:'button'});
    const status = el('span', '', {role:'status'});
    const retry = el('button', 'Retry loading rows', {type:'button', hidden:''});
    controls.append(previous, status, next, retry);
    if (refs.length <= 100) { previous.hidden = true; next.hidden = true; }
    main.append(controls, view.wrapper);
    const chunks = new Map();
    let offset = 0;
    async function render() {
      previous.disabled = true; next.disabled = true; retry.hidden = true;
      status.classList.remove('error');
      status.textContent = 'Loading database rows…';
      view.body.replaceChildren();
      try {
        const batch = refs.slice(offset, offset + 100);
        const chunkIds = [...new Set(batch.map(ref => Math.floor(ref.id / manifest.chunkSize)))];
        await Promise.all(chunkIds.map(async chunkId => {
          if (!chunks.has(chunkId)) {
            const pending = json(`data/dbrows/${chunkId}.json`).catch(error => { chunks.delete(chunkId); throw error; });
            chunks.set(chunkId, pending);
          }
          await chunks.get(chunkId);
        }));
        const loaded = new Map(await Promise.all(chunkIds.map(async chunkId => [chunkId, await chunks.get(chunkId)])));
        for (const ref of batch) {
          const record = loaded.get(Math.floor(ref.id / manifest.chunkSize))[ref.id];
          if (!record) throw new Error(`Could not find database row #${ref.id}.`);
          const columnValues = columns.map(column => record.rows.filter(row => row.key === column.key));
          const height = Math.max(1, ...columnValues.map(values => values.length));
          const recordRows = Array.from({length:height}, () => {
            const row = view.body.insertRow(); row.dataset.dbrow = ref.id; return row;
          });
          const rowLink = recordRows[0].insertCell(); rowLink.rowSpan = height; rowLink.append(parsed(ref));
          columns.forEach((column, columnIndex) => {
            const values = columnValues[columnIndex];
            if (!values.length) {
              const cell = recordRows[0].insertCell(); cell.dataset.column = column.key; cell.rowSpan = height;
              if (column.split) cell.colSpan = 2;
              cell.className = 'db-null';
              cell.append(el('span', 'null', {title:'No explicit value'}));
              return;
            }
            values.forEach((value, index) => {
              const span = index === values.length - 1 ? height - index : 1;
              const cell = recordRows[index].insertCell(); cell.dataset.column = column.key; cell.rowSpan = span;
              const entry = el('div', null, {class:column.split ? 'db-value db-item-value' : 'db-value', title:value.raw});
              cell.append(entry);
              if (column.split) {
                entry.append(parsed(value.parsed?.[0]));
                const quantity = recordRows[index].insertCell();
                quantity.dataset.column = `${column.key}-quantity`; quantity.className = 'stock-parsed-quantity'; quantity.rowSpan = span;
                const amount = el('div', null, {class:'db-value db-item-value'});
                amount.append(parsed(value.parsed?.[1])); quantity.append(amount);
              } else {
                (value.parsed || []).forEach((part, i) => { if (i) entry.append(document.createTextNode(', ')); entry.append(parsed(part)); });
              }
            });
          });
        }
        status.textContent = `${number(offset + 1)}–${number(Math.min(offset + 100, refs.length))} of ${number(refs.length)} rows`;
      } catch (error) {
        view.body.replaceChildren();
        status.textContent = error.message; status.classList.add('error'); retry.hidden = false;
      }
      previous.disabled = offset === 0; next.disabled = offset + 100 >= refs.length;
    }
    previous.onclick = () => { offset -= 100; render(); };
    next.onclick = () => { offset += 100; render(); };
    retry.onclick = render;
    await render();
  }
  function table(headers) {
    const wrapper = el('div', null, {class: 'table-wrap'});
    const table = el('table');
    const head = table.createTHead().insertRow();
    headers.forEach(title => head.append(el('th', title, {scope: 'col'})));
    const body = table.createTBody();
    wrapper.append(table);
    return {wrapper, table, head, body};
  }
  function heading(text) { main.append(el('h1', text)); document.title = `${text} · RS3 cache configs`; }
  function indexPage() {
    heading('RuneScape 3 cache configs');
    main.append(el('p', 'Browse config definitions, typed values, and references.'));
    const list = el('ul', null, {class: 'categories'});
    for (const type of types) {
      const item = el('li');
      item.append(link(type, undefined, type), el('span', number(manifest.counts[type] ?? 0)));
      list.append(item);
    }
    main.append(list);
  }
  async function listing() {
    heading(typeLabels[page]);
    const rows = await json(`data/${page}/index.json`);
    const toolbar = el('form', null, {class: 'toolbar', role: 'search'});
    const search = el('input', null, {type: 'search', placeholder: 'Search ID, name or value', 'aria-label': 'Search configs', value: query.get('q') || ''});
    const filter = el('select', null, {'aria-label': 'Filter records'});
    for (const [value, text] of [['all', 'All records'], ['named', 'Named records'], ['empty', 'Empty records'], ['referenced', 'Referenced records']]) filter.append(el('option', text, {value}));
    filter.value = query.get('filter') || 'all';
    const jump = el('input', null, {type: page.endsWith('_params') ? 'text' : 'number', min: '0', placeholder: page.endsWith('_params') ? 'Field name' : 'ID', 'aria-label': 'Go to ID', style: 'width:140px'});
    const go = el('button', 'Go to ID', {type: 'submit'});
    toolbar.append(search, filter, jump, go);
    toolbar.addEventListener('submit', e => { e.preventDefault(); if (jump.value !== '') location.href = url(page, jump.value); });
    main.append(toolbar);
    const legend = el('p', null, {class: 'legend muted'});
    legend.append(el('span', 'Named', {class: 'named'}), el('span', 'Empty', {class: 'empty'}));
    main.append(legend);
    const headers = ['id', 'name', 'size', 'refs'];
    const quickchat = ['quickchatcategories','quickchatphrases'].includes(page);
    if (quickchat) headers.splice(2, 0, 'display');
    if (previewPages.includes(page)) headers.splice(1,0,'preview');
    if (page === 'enums') headers.splice(3, 0, 'keyType', 'valType');
    if (page === 'params' || page.endsWith('_params')) headers.splice(1, 0, 'type');
    if (page.endsWith('_params')) headers.push('example');
    const view = table(headers);
    const pagination = el('div', null, {class: 'pagination'});
    const previous = el('button', 'Previous', {type: 'button'});
    const next = el('button', 'Next', {type: 'button'});
    const status = el('span', '', {role: 'status'});
    const count = el('select', null, {'aria-label': 'Rows per page'});
    for (const n of [100, 250, 500]) count.append(el('option', `${n} rows`, {value: n}));
    pagination.append(previous, status, next, count);
    main.append(pagination, view.wrapper);
    let offset = Math.max(0, Number(query.get('page') || 1) - 1) * 100;
    let sort = 'id', direction = 1;
    const isNamed = r => !/^(param|struct|enum|obj|npc|loc|cursor|inv|quest|idk|idkit|dbrow|dbtable|varbit|achievement|chatcat|chatphrase|varplayer|mel|msi|bas|seq|spotanim|hitmark|headbar)_\d+$/.test(r.name);
    function render() {
      const needle = search.value.trim().toLowerCase();
      const filtered = rows.filter(r => (!needle || [r.id, r.name, r.display, r.type, r.example].some(v => String(v ?? '').toLowerCase().includes(needle))) && (filter.value === 'all' || filter.value === 'named' && isNamed(r) || filter.value === 'empty' && r.size === 0 || filter.value === 'referenced' && r.refs > 0));
      filtered.sort((a, b) => direction * (typeof a[sort] === 'number' ? a[sort] - b[sort] : collator.compare(String(a[sort] ?? ''), String(b[sort] ?? ''))));
      const limit = Number(count.value);
      offset = Math.min(offset, Math.max(0, Math.ceil(filtered.length / limit) - 1) * limit);
      const fragment = document.createDocumentFragment();
      for (const record of filtered.slice(offset, offset + limit)) {
        const row = el('tr', null, {class: isNamed(record) ? 'struct-named' : record.size === 0 ? 'struct-empty' : ''});
        for (const key of headers) {
          const cell = el('td', null, {class: ['id','size','refs'].includes(key) ? 'numeric' : ''});
          if (key === 'id') cell.append(link(page, record.id));
          else if (key === 'preview') {
            if (record.preview?.kind === 'image') {
              const previewLink = link(page,record.id,'');
              previewLink.setAttribute('aria-label',`Open ${page === 'cursors' ? 'cursor' : typeLabels[page]} ${record.id}`);
              const icon = el('img',null,{class:page === 'cursors' ? 'cursor-preview' : 'config-preview',src:record.preview.src,alt:record.name,width:'32',height:'32',loading:'lazy'});
              icon.onerror = () => { previewLink.hidden = true; };
              previewLink.append(icon); cell.append(previewLink);
            } else cell.textContent = record.preview?.text || '';
          }
          else cell.textContent = record[key] ?? '';
          if (key === 'name' && !quickchat && record.display && record.display !== record.name) cell.append(el('br'), el('span', record.display, {class: 'muted'}));
          row.append(cell);
        }
        fragment.append(row);
      }
      view.body.replaceChildren(fragment);
      if (!filtered.length) { const row = view.body.insertRow(); const cell = row.insertCell(); cell.colSpan = headers.length; cell.textContent = 'No matching records.'; }
      status.textContent = filtered.length ? `${number(offset + 1)}–${number(Math.min(offset + limit, filtered.length))} of ${number(filtered.length)}` : '0 records';
      previous.disabled = offset === 0; next.disabled = offset + limit >= filtered.length;
      for (const [i, key] of headers.entries()) view.head.cells[i].setAttribute('aria-sort', key === sort ? direction === 1 ? 'ascending' : 'descending' : 'none');
      const q = new URLSearchParams({type: page});
      if (search.value) q.set('q', search.value);
      if (filter.value !== 'all') q.set('filter', filter.value);
      if (offset) q.set('page', Math.floor(offset / limit) + 1);
      history.replaceState(null, '', `?${q}`);
    }
    for (const [i, key] of headers.entries()) {
      if (key === 'preview') continue;
      const title = key === 'display' && quickchat ? page === 'quickchatphrases' ? 'Phrase' : 'Description' : key;
      const button = el('button', title, {type: 'button', 'aria-label': `Sort by ${title}`});
      button.onclick = () => { direction = sort === key ? -direction : 1; sort = key; render(); };
      view.head.cells[i].replaceChildren(button);
    }
    search.oninput = filter.onchange = count.onchange = () => { offset = 0; render(); };
    previous.onclick = () => { offset -= Number(count.value); render(); };
    next.onclick = () => { offset += Number(count.value); render(); };
    render();
  }
  async function detail() {
    const nativeField = page.endsWith('_params');
    if (!(nativeField ? /^[a-zA-Z0-9_]+$/ : /^\d+$/).test(id)) throw new Error(nativeField ? 'Enter a valid config field name.' : 'The config ID must be a non-negative integer.');
    const chunk = await json(`data/${page}/${nativeField ? 'field-' + encodeURIComponent(id) : Math.floor(Number(id) / manifest.chunkSize)}.json`);
    const data = chunk[nativeField ? id : Number(id)];
    if (!data) throw new Error(`Could not find ${page} #${id}.`);
    heading(`${page.toUpperCase()} #${id}${data.name ? ': ' + data.name : ''}`);
    const pageMetadata = el('dl', null, {class:'table-metadata', hidden:''});
    const isEnumDefinition = row => !row.parsedKey && ['inputtype','outputtype','default'].includes(row.key);
    const definitions = page === 'enums' ? data.rows.filter(isEnumDefinition) : page === 'params' ? data.rows : [];
    for (const row of definitions) {
      const pair = el('div', null, {'data-column':row.key});
      const value = el('dd', null, {title:`Raw value: ${row.raw}`});
      (row.parsed || []).forEach((part, i) => { if (i) value.append(document.createTextNode(', ')); value.append(parsed(part)); });
      pair.append(el('dt', readableKey(row)), value);
      pageMetadata.append(pair); pageMetadata.hidden = false;
    }
    if (data.param !== undefined) main.append(link('params', data.param, 'Parameter definition'));
    if (data.display && data.display !== data.name) main.append(el('p', data.display));
    main.append(configShortcuts(data), pageMetadata);
    function appendRows(rows, label) {
      const shared = [];
      if (rows.length && !rows.every(isCs2Param)) {
        const firstName = String(rows[0].key_name ?? rows[0].key);
        const firstType = rows[0].type || 'unknown';
        if (rows.every(row => String(row.key_name ?? row.key) === firstName)) shared.push({key:'key_name', label:'Key name', value:readableKey(rows[0]), title:`Dump key: ${firstName}`});
        if (rows.every(row => (row.type || 'unknown') === firstType)) shared.push({key:'type', label:'Type', value:firstType});
      }
      const headers = ['raw_key', 'key_name', 'raw_val', 'type', 'parsed_val'].filter(key => !shared.some(entry => entry.key === key));
      const view = table(headers);
      headers.forEach((key, i) => { view.head.cells[i].dataset.column = key; });
      const isQuantityRow = row => !isCs2Param(row) && (
        (['invs','inv_params'].includes(page) && /^stock\d+$/.test(String(row.key_name ?? row.key))) ||
        (['items','item_params'].includes(page) && /^count\d+$/.test(String(row.key_name ?? row.key))) ||
        (page === 'dbrows' && ['obj,int','dbrow,int'].includes(row.type?.replace(/\s/g, '')) && row.parsed?.length === 2)
      );
      const splitQuantity = rows.some(isQuantityRow);
      if (splitQuantity) {
        view.table.classList.add('stock-value-table');
        for (const cell of view.head.cells) {
          if (cell.dataset.column === 'parsed_val') { cell.colSpan = 2; cell.scope = 'colgroup'; }
        }
      }
      if (shared.length) {
        const summary = nativeField || page === 'enums' || (page === 'params' && label === 'uses') ? pageMetadata : el('dl', null, {class:'table-metadata'});
        summary.hidden = false;
        for (const entry of shared) {
          if (entry.key === 'type' && definitions.some(row => row.key === (page === 'enums' ? 'outputtype' : 'type') && row.raw === entry.value)) continue;
          const pair = el('div', null, {'data-column':entry.key});
          pair.append(el('dt', entry.label), el('dd', entry.value, entry.title ? {title:entry.title} : {}));
          if (entry.key === 'key_name') summary.prepend(pair);
          else summary.append(pair);
        }
        if (summary !== pageMetadata) main.append(summary);
      }
      let offset = 0;
      const controls = el('div', null, {class: 'pagination'});
      const previous = el('button', 'Previous', {type: 'button'});
      const next = el('button', 'Next', {type: 'button'});
      const status = el('span', '', {role: 'status'});
      function render() {
        view.body.replaceChildren();
        for (const row of rows.slice(offset, offset + 250)) {
          const tr = view.body.insertRow();
          const keyCell = tr.insertCell();
          keyCell.dataset.column = 'raw_key';
          if (row.param !== undefined) keyCell.append(link('params', row.param));
          else if (row.parsedKey) keyCell.append(parsed(row.parsedKey));
          else {
            const nativePage = fieldPages[page];
            if (nativePage && !isCs2Param(row)) keyCell.append(link(nativePage, row.key, row.key));
            else keyCell.textContent = row.key;
          }
          if (headers.includes('key_name')) {
            const nameCell = tr.insertCell(); nameCell.dataset.column = 'key_name';
            nameCell.textContent = readableKey(row);
            nameCell.title = `Dump key: ${row.key_name ?? row.key}`;
          }
          const rawCell = tr.insertCell(); rawCell.dataset.column = 'raw_val'; rawCell.className = 'raw-value'; rawCell.textContent = row.raw;
          if (headers.includes('type')) {
            const typeCell = tr.insertCell(); typeCell.dataset.column = 'type'; typeCell.textContent = row.type || 'unknown';
          }
          const valueCell = tr.insertCell();
          valueCell.dataset.column = 'parsed_val';
          if (splitQuantity && isQuantityRow(row)) {
            valueCell.dataset.column = 'parsed_item';
            valueCell.append(parsed(row.parsed?.[0]));
            const quantityCell = tr.insertCell();
            quantityCell.dataset.column = 'parsed_quantity'; quantityCell.className = 'stock-parsed-quantity';
            quantityCell.append(parsed(row.parsed?.[1]));
          } else {
            if (splitQuantity) valueCell.colSpan = 2;
            (row.parsed || []).forEach((value, i) => { if (i) valueCell.append(document.createTextNode(', ')); valueCell.append(parsed(value)); });
          }
        }
        status.textContent = `${number(offset + 1)}–${number(Math.min(offset + 250, rows.length))} of ${number(rows.length)} ${label}`;
        previous.disabled = offset === 0; next.disabled = offset + 250 >= rows.length;
      }
      previous.onclick = () => { offset -= 250; render(); }; next.onclick = () => { offset += 250; render(); };
      controls.append(previous, status, next);
      if (rows.length > 250) main.append(controls);
      else main.append(el('p', `${number(rows.length)} ${label}`, {class:'muted'}));
      main.append(view.wrapper); render();
    }
    if (fieldPages[page] || ['mapelements','sequences'].includes(page)) {
      let fields = data.rows.filter(row => !isCs2Param(row));
      if (page === 'achievements') fields = achievementRows(fields);
      const params = data.rows.filter(isCs2Param);
      main.append(el('h2', 'Native fields'));
      if (fields.length) appendRows(fields, 'fields');
      else main.append(el('p', 'This config has no explicit native fields.'));
      if (params.length || ['items','npcs','quests','scenery'].includes(page)) {
        main.append(el('h2', 'cs2 params'));
        if (params.length) appendRows(params, 'parameters');
        else main.append(el('p', 'This file does not have cs2 params.'));
      }
    } else if (page === 'params') {
      if (!definitions.length) main.append(el('p', 'This parameter has no explicit definition fields.', {class:'muted'}));
    } else if (page === 'enums') {
      const entries = data.rows.filter(row => !isEnumDefinition(row));
      if (entries.length) appendRows(entries, 'entries');
      else main.append(el('p', 'This enum has no explicit entries.', {class:'muted'}));
    } else if (data.rows.length) appendRows(data.rows, nativeField ? 'uses' : 'fields');
    else main.append(el('p', 'This config has no explicit fields.'));
    if (data.uses?.length) { main.append(el('h2', `Parameter uses (${number(data.uses.length)})`)); appendRows(data.uses, 'uses'); }
    if (page === 'dbtables') await databaseRows(data);
    main.append(el('h2', `References (${number(data.references.length)})`));
    if (data.references.length) {
      const groups = new Map();
      for (const ref of data.references) { if (!groups.has(ref.type)) groups.set(ref.type, []); groups.get(ref.type).push(ref); }
      for (const [type, refs] of groups) {
        const disclosure = el('details'); disclosure.open = groups.size === 1;
        disclosure.append(el('summary', `${type} (${number(refs.length)})`));
        const list = el('ul', null, {class: 'reference-list'});
        const more = el('button','Show more references',{type:'button'});
        let shown = 0;
        function showMoreReferences() {
          const fragment = document.createDocumentFragment();
          for (const ref of refs.slice(shown,shown+250)) { const li = el('li'); li.append(parsed(ref)); fragment.append(li); }
          shown = Math.min(shown+250,refs.length); list.append(fragment);
          more.hidden = shown === refs.length;
          more.textContent = `Show more (${number(refs.length-shown)} remaining)`;
          more.setAttribute('aria-label',`Show more ${type} references, ${number(refs.length-shown)} remaining`);
        }
        more.onclick = showMoreReferences;
        showMoreReferences();
        disclosure.append(list);
        if (refs.length > 250) disclosure.append(more);
        main.append(disclosure);
      }
    } else main.append(el('p', 'No references found in the imported config types.', {class: 'muted'}));
    if (data.source) {
      const source = el('details'); source.append(el('summary', 'Source config'), el('pre', data.source)); main.append(source);
    }
  }
  async function start() {
    try {
      let cursors;
      manifest = await json('data/manifest.json');
      [keyLabels, cursors] = await Promise.all([json('key_labels.json'), json('data/cursors/index.json')]);
      cursorPreviews = new Map(cursors.filter(cursor => cursor.preview?.kind === 'image').map(cursor => [Number(cursor.id),cursor.preview.src]));
      main.replaceChildren();
      navigation();
      const footer = document.getElementById('provenance');
      footer.append(document.createTextNode('Cache dumps: '), el('a', manifest.repository, {href: `https://github.com/${manifest.repository}/tree/${manifest.revision}/config`}), document.createTextNode(` · ${manifest.local ? 'Local input' : 'Commit ' + manifest.revision.slice(0, 12)} · Built ${new Date(manifest.built).toLocaleDateString('en-GB')}`));
      if (!page) indexPage();
      else if (!types.includes(page)) throw new Error(`Unknown config type: ${page}`);
      else if (id === null) await listing();
      else await detail();
    } catch (error) {
      main.replaceChildren(el('h1', 'Could not load cache data'), el('p', error.message, {class: 'error'}));
      main.append(el('p', location.protocol === 'file:' ? 'Open the viewer over HTTP: run python tools/serve.py after python -m builder.build.' : 'Build or refresh the data with python -m builder.build, then run python tools/serve.py.'), el('a', 'Back to config index', {href: 'index.html'}));
    }
  }
  return start();
})();
