// Optional DOM regression tests: see README for the test-only jsdom install.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {gzipSync, gunzipSync} = require('node:zlib');
const root = path.resolve(__dirname, '..');
const {JSDOM} = require(path.join(root, '.cache/frontend-check/node_modules/jsdom'));

const frontendRoot = path.join(root, 'frontend');
const dataRoot = path.resolve(root, process.env.VIEWER_DIST || 'dist');
async function open(query, replacement, replacementPath = 'data/items/0.json') {
  const dom = new JSDOM(fs.readFileSync(path.join(frontendRoot, 'index.html'), 'utf8'), {
    url: `http://localhost/${query}`, runScripts: 'outside-only',
  });
  dom.window.Response = Response;
  dom.window.DecompressionStream = DecompressionStream;
  dom.window.fetch = async relative => {
    const plainPath = relative.replace(/\.gz$/, '');
    const isReplacement = replacement instanceof Map ? replacement.has(plainPath) : replacement && [replacementPath, replacementPath + '.gz'].includes(relative);
    const value = replacement instanceof Map ? replacement.get(plainPath) : replacement;
    if (isReplacement && value === null) return new Response('', {status:404});
    if (!isReplacement && !fs.existsSync(path.join(dataRoot, relative))) return new Response('', {status:404});
    let bytes = isReplacement ? Buffer.from(JSON.stringify(value)) : fs.readFileSync(path.join(dataRoot, relative));
    if (isReplacement && relative.endsWith('.gz')) bytes = gzipSync(bytes);
    return new Response(bytes);
  };
  await dom.window.eval(fs.readFileSync(path.join(frontendRoot, 'structs.js'), 'utf8'));
  return dom;
}

async function settle(dom) {
  const deadline = Date.now() + 10000;
  while ([...dom.window.document.querySelectorAll('[role=status]')].some(node=>node.textContent.startsWith('Loading'))) {
    assert.ok(Date.now() < deadline,'Timed out waiting for database rows');
    await new Promise(resolve=>setTimeout(resolve,5));
  }
}

function section(document, title) {
  const heading = [...document.querySelectorAll('h2')].find(h => typeof title === 'string' ? h.textContent === title : title.test(h.textContent));
  assert.ok(heading, `Missing ${title} section`);
  const nodes = [];
  for (let node = heading.nextElementSibling; node && node.tagName !== 'H2'; node = node.nextElementSibling) nodes.push(node);
  return nodes;
}

function column(row, name) {
  return [...row.cells].find(cell => cell.dataset.column === name);
}

function assertTableGrid(view) {
  const width = [...view.tHead.rows[0].cells].reduce((n,c)=>n+c.colSpan,0);
  const spans = Array(width).fill(0);
  for (const row of view.tBodies[0].rows) {
    let position = 0;
    for (const cell of row.cells) {
      while (spans[position] > 0) position++;
      for (let i=0;i<cell.colSpan;i++) {
        assert.ok(position+i < width, 'Cell extends beyond the table columns');
        assert.equal(spans[position+i],0, 'Cells must not overlap');
        spans[position+i] = cell.rowSpan;
      }
      position += cell.colSpan;
    }
    assert.ok(spans.every(n=>n>0), 'Each table row must cover every column');
    spans.forEach((n,i)=>{ spans[i]=n-1; });
  }
  assert.ok(spans.every(n=>n===0), 'Merged cells must end within the table');
}

async function run() {
  let dom = await open('?type=items&id=3');
  try {
    const doc = dom.window.document;
    const native = section(doc, 'Native fields');
    const params = section(doc, 'cs2 params');
    const rows = params.flatMap(n => [...n.querySelectorAll('tbody tr')]);
    assert.equal(rows.length, 2);
    assert.deepEqual(rows.map(r => [column(r,'raw_key').textContent, column(r,'key_name').textContent, column(r,'raw_val').textContent]), [
      ['31', 'Destroy on drop', '1'], ['1397', 'Protect on death', '1'],
    ]);
    assert.deepEqual(rows.map(r => r.querySelector('a').getAttribute('href')), [
      'index.html?type=params&id=31', 'index.html?type=params&id=1397',
    ]);
    assert.ok(native.some(n => n.textContent.includes("Nulodion's notes")));
    assert.ok(!native.some(n => n.textContent.includes('destroyondrop')));
    const nativeRows = native.flatMap(n => [...n.querySelectorAll('tbody tr')]);
    for (const row of nativeRows) {
      assert.ok(column(row,'key_name').textContent, 'Native key_name must not be blank');
      assert.ok(column(row,'type').textContent, 'Native type must not be blank');
    }
    for (const [key, type] of [['name','string'], ['model','model'], ['members','boolean'], ['2dzoom','int']]) {
      const row = nativeRows.find(r => r.cells[0].textContent === key);
      assert.ok(row, `Missing field ${key}`);
      assert.equal(column(row,'type').textContent, type);
    }
    assert.ok(rows.every(r => column(r,'type').textContent === 'int'));
    assert.ok(!params.some(n => n.classList.contains('table-metadata')));
    const zoom = nativeRows.find(r => r.cells[0].textContent === '2dzoom');
    assert.equal(zoom.cells[1].textContent, 'Inventory model zoom');
    assert.equal(zoom.cells[1].title, 'Dump key: 2dzoom');
    assert.equal(zoom.cells[0].querySelector('a').getAttribute('href'), 'index.html?type=item_params&id=2dzoom');
    assert.equal(nativeRows.find(r => r.cells[0].textContent === 'iop1').cells[1].textContent, 'Inventory action 1');
    for (const [key,id] of [['cursor3',45],['icursor1',50]]) {
      const row = nativeRows.find(r => column(r,'raw_key').textContent === key);
      const reference = column(row,'parsed_val').querySelector('.cursor-reference');
      assert.equal(reference.firstElementChild.tagName,'IMG');
      assert.equal(reference.lastElementChild.getAttribute('href'),`index.html?type=cursors&id=${id}`);
      assert.ok(reference.firstElementChild.src.startsWith('https://chisel.weirdgloop.org/static/img/rs3-graphic/'));
    }
    assert.ok([...doc.querySelectorAll('h2')].some(h => h.textContent === 'References (0)'));
  } finally { dom.window.close(); }

  dom = await open('?type=enums&id=29');
  try {
    const doc = dom.window.document;
    const metadata = doc.querySelector('main > .table-metadata');
    assert.equal(metadata.hidden,false);
    for (const key of ['inputtype','outputtype','default']) assert.ok(metadata.querySelector(`[data-column="${key}"] dd`));
    const fallback = metadata.querySelector('[data-column="default"] dd');
    assert.equal(fallback.querySelector('a').getAttribute('href'),'index.html?type=items&id=4069');
    const view = doc.querySelector('main > .table-wrap > table');
    assert.equal(view.tBodies[0].rows.length,4);
    assert.ok([...view.tBodies[0].rows].every(row=>!['inputtype','outputtype','default'].includes(column(row,'raw_key').textContent)));
    assert.equal(metadata.querySelector('[data-column="type"]'),null,'Output type already supplies the shared value type');
  } finally { dom.window.close(); }

  const enumFixture = {id:0,name:'enum_metadata_fixture',references:[],rows:[
    {key:'inputtype',key_name:'inputtype',raw:'string',type:'type',parsed:[{text:'string'}]},
    {key:'outputtype',key_name:'outputtype',raw:'struct',type:'type',parsed:[{text:'struct'}]},
    {key:'default',key_name:'default',raw:'example',type:'struct',parsed:[{type:'structs',id:0,text:'example'}]},
    ...Array.from({length:251},(_,i)=>{
      const key = ['inputtype','outputtype','default'][i] || `key${i}`;
      return {key,key_name:'val',raw:'example',type:'struct',parsedKey:{text:key},parsed:[{type:'structs',id:0,text:'example'}]};
    }),
  ]};
  dom = await open('?type=enums&id=0',{'0':enumFixture},'data/enums/0.json');
  try {
    const doc = dom.window.document;
    const view = doc.querySelector('main > .table-wrap > table');
    assert.equal(view.tBodies[0].rows.length,250);
    assert.deepEqual([...view.tBodies[0].rows].slice(0,3).map(row=>column(row,'raw_key').textContent),['inputtype','outputtype','default']);
    const fallback = doc.querySelector('.table-metadata [data-column="default"] dd');
    assert.equal(fallback.querySelector('a').getAttribute('href'),'index.html?type=structs&id=0');
    const controls = doc.querySelector('main > .pagination');
    assert.equal(controls.querySelector('[role=status]').textContent,'1–250 of 251 entries');
    [...controls.querySelectorAll('button')].find(button=>button.textContent==='Next').click();
    assert.equal(view.tBodies[0].rows.length,1);
    assert.equal(column(view.tBodies[0].rows[0],'raw_key').textContent,'key250');
    assert.equal(controls.querySelector('[role=status]').textContent,'251–251 of 251 entries');
  } finally { dom.window.close(); }

  enumFixture.rows = enumFixture.rows.slice(0,3);
  dom = await open('?type=enums&id=0',{'0':enumFixture},'data/enums/0.json');
  try {
    assert.ok(dom.window.document.querySelector('.table-metadata [data-column="default"] a'));
    assert.equal(dom.window.document.querySelector('main > .table-wrap'),null);
    assert.ok(dom.window.document.querySelector('main').textContent.includes('This enum has no explicit entries.'));
  } finally { dom.window.close(); }

  dom = await open('?type=dbtables&id=39');
  try {
    const nodes = section(dom.window.document, 'Database rows (14)');
    assert.ok(!nodes.some(n=>n.classList.contains('reference-list')));
    const view = nodes.find(n=>n.classList.contains('table-wrap')).querySelector('table');
    assert.equal(new Set([...view.tBodies[0].rows].map(row=>row.dataset.dbrow)).size,14);
    assert.equal(view.tHead.rows[0].cells.length,15);
    const header = column(view.tHead.rows[0],'col13');
    assert.equal(header.colSpan,2);
    assert.equal(header.querySelector('.db-column-type').textContent,'obj, int');
    const row = view.tBodies[0].rows[0];
    assert.equal(row.cells[0].querySelector('a').getAttribute('href'),'index.html?type=dbrows&id=89');
    assert.equal(column(row,'col4').textContent,'null');
    assert.ok(column(row,'col4').classList.contains('db-null'));
    const entries = [...view.tBodies[0].rows].filter(row=>row.dataset.dbrow==='89');
    assert.deepEqual(entries.map(r=>column(r,'col11').textContent),['8778: plank_oak, 10, true','1539: nails, 75, true']);
    assert.equal(row.cells[0].rowSpan,entries.length);
    const item = column(row,'col13');
    assert.equal(item.querySelector('a').getAttribute('href'),'index.html?type=items&id=44152');
    assert.equal(column(row,'col13-quantity').textContent,'1');
    assert.ok(view.tBodies[0].rows.length > 1);
    assertTableGrid(view);
  } finally { dom.window.close(); }

  dom = await open('?type=dbtables&id=88');
  try {
    const view = dom.window.document.querySelector('.database-rows');
    const entries = [...view.tBodies[0].rows].filter(row=>row.dataset.dbrow==='2862');
    assert.equal(entries.length,2);
    assert.deepEqual(entries.map(row=>[
      column(row,'col15').querySelector('a').getAttribute('href'),
      column(row,'col15-quantity').textContent,
    ]),[
      ['index.html?type=items&id=49444','10'],
      ['index.html?type=items&id=49445','10'],
    ]);
    assert.equal(entries[0].cells[0].rowSpan,2);
    const plainItem = column(entries[0],'col14');
    assert.equal(plainItem.querySelector('a').getAttribute('href'),'index.html?type=items&id=49516');
    assert.equal(column(view.tHead.rows[0],'col17').colSpan,2);
    const dbrowLink = column(entries[0],'col17').querySelector('a');
    assert.equal(dbrowLink.getAttribute('href'),'index.html?type=dbrows&id=3005');
    assert.equal(column(entries[0],'col17-quantity').textContent,'100');
    assertTableGrid(view);
    const next = [...section(dom.window.document,'Database rows (149)').find(n=>n.classList.contains('pagination')).querySelectorAll('button')][1];
    next.click(); await settle(dom);
    assertTableGrid(view);
  } finally { dom.window.close(); }

  dom = await open('?type=dbtables&id=163');
  try {
    const nodes = section(dom.window.document,'Database rows (5,411)');
    const view = nodes.find(n=>n.classList.contains('table-wrap')).querySelector('table');
    const controls = nodes.find(n=>n.classList.contains('pagination'));
    const [previous,next] = controls.querySelectorAll('button');
    const first = view.tBodies[0].rows[0].cells[0].textContent;
    assert.equal(new Set([...view.tBodies[0].rows].map(row=>row.dataset.dbrow)).size,100);
    assertTableGrid(view);
    assert.equal(previous.disabled,true);
    assert.equal(controls.querySelector('[role=status]').textContent,'1–100 of 5,411 rows');
    next.click(); await settle(dom);
    assert.equal(new Set([...view.tBodies[0].rows].map(row=>row.dataset.dbrow)).size,100);
    assertTableGrid(view);
    assert.equal(controls.querySelector('[role=status]').textContent,'101–200 of 5,411 rows');
    assert.notEqual(view.tBodies[0].rows[0].cells[0].textContent,first);
    previous.click(); await settle(dom);
    assert.equal(view.tBodies[0].rows[0].cells[0].textContent,first);
  } finally { dom.window.close(); }

  for (const [id,count] of [[0,99],[3,0]]) {
    dom = await open(`?type=dbtables&id=${id}`);
    try {
      const nodes = section(dom.window.document,`Database rows (${count})`);
      if (count) {
        const view = nodes.find(n=>n.classList.contains('table-wrap')).querySelector('table');
        assert.equal(view.tHead.rows[0].cells.length,1);
        assert.equal(view.tBodies[0].rows.length,count);
      } else assert.ok(nodes.some(n=>n.textContent==='This table has no database rows.'));
    } finally { dom.window.close(); }
  }

  for (const [type,id,key,itemId,quantity,targetType='items'] of [['dbrows',89,'col13',44152,'1'], ['invs',1,'stock1',1267,'10'], ['items',39,'count1',13195,'2'], ['dbrows',13386,'col17',13390,'100','dbrows']]) {
    dom = await open(`?type=${type}&id=${id}`);
    try {
      const view = dom.window.document.querySelector('main > .table-wrap > table');
      assert.equal(view.tHead.rows.length,1, 'Item and quantity must share the parsed_val header');
      assert.equal(column(view.tHead.rows[0],'parsed_val').colSpan,2);
      const rows = [...view.tBodies[0].rows];
      const row = rows.find(r=>column(r,'raw_key').textContent===key);
      const item = column(row,'parsed_item');
      assert.equal(item.querySelector('a').getAttribute('href'),`index.html?type=${targetType}&id=${itemId}`);
      assert.equal(column(row,'parsed_quantity').textContent,quantity);
      assert.equal(column(rows[0],'parsed_val').colSpan,2, 'Other values must span both parsed columns');
    } finally { dom.window.close(); }
  }

  dom = await open('?type=invs&id=528');
  try {
    const doc = dom.window.document;
    const fields = section(doc,'Native fields');
    const view = fields.find(node=>node.classList.contains('table-wrap')).querySelector('table');
    assert.deepEqual([...view.tHead.rows[0].cells].map(cell=>cell.textContent),['raw_key','key_name','raw_val','type','parsed_val']);
    assert.equal(view.tBodies[0].rows.length,1);
    const row = view.tBodies[0].rows[0];
    assert.equal(column(row,'raw_key').textContent,'size');
    assert.equal(column(row,'key_name').textContent,'Inventory capacity');
    assert.equal(column(row,'type').textContent,'int');
    assert.ok([...doc.querySelectorAll('main > .table-metadata')].every(node=>node.hidden));
    assert.ok(!fields.some(node=>node.classList.contains('table-metadata')));
  } finally { dom.window.close(); }

  dom = await open('?type=scenery&id=116381');
  try {
    const nodes = section(dom.window.document,'cs2 params');
    const view = nodes.find(n=>n.classList.contains('table-wrap')).querySelector('table');
    assert.deepEqual([...view.tHead.rows[0].cells].map(c=>c.textContent),['raw_key','key_name','raw_val','type','parsed_val']);
    assert.equal(view.tBodies[0].rows.length,1);
    assert.equal(column(view.tBodies[0].rows[0],'type').textContent,'dbrow');
    assert.ok(column(view.tBodies[0].rows[0],'key_name').textContent);
    assert.ok(!nodes.some(n=>n.classList.contains('table-metadata')));
  } finally { dom.window.close(); }

  dom = await open('?type=cursors&id=0');
  try {
    const doc = dom.window.document;
    assert.match(doc.querySelector('h1').textContent,/CURSORS #0/);
    assert.ok([...doc.querySelectorAll('img')].some(img=>img.src.endsWith('/898-0.png')));
    const rows = [...section(doc,'Native fields').find(n=>n.classList.contains('table-wrap')).querySelector('tbody').rows];
    assert.equal(column(rows.find(r=>column(r,'raw_key').textContent==='hotspot'),'parsed_val').textContent,'X: 0, Y: 0');
    assert.equal(doc.querySelector('#config-type').selectedOptions[0].textContent,'Cursors');
    assert.equal(doc.querySelector('.config-shortcuts'),null);
    assert.ok(doc.querySelector('.config-graphic > img').src.endsWith('/898-0.png'));
  } finally { dom.window.close(); }

  dom = await open('?type=cursors');
  try {
    const doc = dom.window.document;
    assert.equal(doc.querySelectorAll('tbody tr').length,100);
    assert.equal(doc.querySelectorAll('.cursor-preview').length,100);
    const first = doc.querySelector('.cursor-preview');
    assert.ok(first.src.endsWith('/898-0.png'));
    assert.equal(first.parentElement.getAttribute('href'),'index.html?type=cursors&id=0');
  } finally { dom.window.close(); }

  dom = await open('?type=cursors&id=45');
  try {
    const doc = dom.window.document;
    assert.ok([...doc.querySelectorAll('main a')].some(a=>a.getAttribute('href')==='index.html?type=items&id=3'));
    const group = [...doc.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent.startsWith('items ('));
    assert.equal(group.querySelectorAll('li').length,250);
    group.querySelector('button').click();
    assert.equal(group.querySelectorAll('li').length,500);
  } finally { dom.window.close(); }

  dom = await open('?type=npcs&id=278');
  try {
    const nodes = section(dom.window.document,'Native fields');
    const rows = [...nodes.find(n=>n.classList.contains('table-wrap')).querySelector('tbody').rows];
    const row = rows.find(r=>column(r,'raw_key').textContent==='quest');
    assert.equal(column(row,'type').textContent,'quest[]');
    assert.equal(column(row,'raw_val').textContent,'cooks_assistant');
    const target = column(row,'parsed_val').querySelector('a');
    assert.equal(target.getAttribute('href'),'index.html?type=quests&id=257');
    assert.equal(target.textContent,'257: cooks_assistant');
  } finally { dom.window.close(); }

  dom = await open('?type=npc_params&id=quest');
  try {
    const rows = [...dom.window.document.querySelector('main > .table-wrap > table').tBodies[0].rows];
    const row = rows.find(r=>column(r,'raw_key').querySelector('a').getAttribute('href')==='index.html?type=npcs&id=278');
    assert.ok(row);
    assert.equal(column(row,'parsed_val').querySelector('a').getAttribute('href'),'index.html?type=quests&id=257');
  } finally { dom.window.close(); }

  dom = await open('?type=quests&id=257');
  try {
    const refs = section(dom.window.document,/^References/).flatMap(node=>[...node.querySelectorAll('a')]);
    assert.ok(refs.some(a=>a.getAttribute('href')==='index.html?type=npcs&id=278'));
  } finally { dom.window.close(); }

  dom = await open('?type=scenery&id=0');
  try {
    const doc = dom.window.document;
    assert.match(doc.querySelector('h1').textContent,/SCENERY #0/);
    const fields = section(doc,'Native fields');
    const rows = [...fields.find(n=>n.classList.contains('table-wrap')).querySelector('tbody').rows];
    const morph = rows.find(r=>column(r,'raw_key').textContent==='multiloc');
    assert.ok(column(morph,'parsed_val').querySelector('a').getAttribute('href').startsWith('index.html?type=scenery&id='));
    assert.equal(doc.querySelector('#config-type').selectedOptions[0].textContent,'Scenery');
    const shortcuts = [...doc.querySelector('.config-shortcuts').querySelectorAll('a')];
    assert.equal(new URL(shortcuts[0].href).pathname,'/gazproj/mrod');
    assert.equal(new URL(shortcuts[3].href).searchParams.get('type'),'object');
    assert.ok([...doc.querySelectorAll('h2')].some(h=>h.textContent==='cs2 params'));
  } finally { dom.window.close(); }

  dom = await open('');
  try {
    const index = [...dom.window.document.querySelectorAll('.categories a')];
    assert.ok(index.some(a=>a.getAttribute('href')==='index.html?type=scenery'));
    assert.ok(index.some(a=>a.getAttribute('href')==='index.html?type=scenery_params'));
    assert.ok(index.some(a=>a.getAttribute('href')==='index.html?type=cursors'));
    assert.ok(index.some(a=>a.getAttribute('href')==='index.html?type=cursor_params'));
    assert.ok(index.some(a=>a.getAttribute('href')==='index.html?type=quickchatcategories'));
    assert.ok(index.some(a=>a.getAttribute('href')==='index.html?type=quickchatphrases'));
    for (const type of ['varplayers','mapelements','mapsceneicons','animationsets','sequences','spoteffects','hitsplats','healthbars']) {
      assert.ok(index.some(a=>a.getAttribute('href')===`index.html?type=${type}`));
    }
  } finally { dom.window.close(); }

  for (const [type,total] of [['varplayers',13489],['mapelements',5843],['mapsceneicons',150],['animationsets',4936],['sequences',38317],['spoteffects',9491],['hitsplats',527],['healthbars',60]]) {
    dom = await open(`?type=${type}`);
    try {
      const doc = dom.window.document;
      const view = doc.querySelector('main > .table-wrap > table');
      assert.equal(view.tBodies[0].rows.length,Math.min(100,total));
      assert.equal(doc.querySelector('#config-type').value,type);
      assert.ok(doc.querySelector('.pagination [role=status]').textContent.endsWith(`of ${total.toLocaleString()}`));
      if (['mapelements','mapsceneicons','hitsplats','healthbars'].includes(type)) {
        assert.ok([...view.tHead.rows[0].cells].some(cell=>cell.textContent==='preview'));
      }
    } finally { dom.window.close(); }
  }

  for (const [type,kind,id] of [['varplayers','varp',4],['mapelements','mel',0],['mapsceneicons','msi',0],['animationsets','bas',0],['sequences','seq',0],['spoteffects','spot',0],['hitsplats','hitmark',0],['healthbars','headbar',0]]) {
    dom = await open(`?type=${type}&id=${id}`);
    try {
      const doc = dom.window.document;
      assert.ok(doc.querySelector('h1').textContent.startsWith(`${type.toUpperCase()} #${id}`));
      assert.equal(doc.querySelector('.config-shortcuts'),null);
      assert.equal(doc.querySelector('.browse-all').getAttribute('href'),`index.html?type=${type}`);
      const rows = [...doc.querySelector('main > .table-wrap > table').tBodies[0].rows];
      const byKey = key=>rows.find(row=>column(row,'raw_key').textContent===key);
      if (type==='mapelements') {
        const morph = column(byKey('multimel'),'parsed_val').querySelector('.config-reference');
        assert.equal(morph.firstElementChild.tagName,'IMG');
        assert.equal(morph.querySelector('a').getAttribute('href'),'index.html?type=mapelements&id=1992');
        const params = section(doc,'cs2 params').find(node=>node.classList.contains('table-wrap')).querySelector('table');
        assert.ok(column(params.tHead.rows[0],'key_name'));
        assert.ok(column(params.tHead.rows[0],'type'));
      }
      if (type==='animationsets') {
        const targets = [...column(byKey('readyanim'),'parsed_val').querySelectorAll('a')].map(a=>a.getAttribute('href'));
        assert.deepEqual(targets,['index.html?type=sequences&id=738','index.html?type=sequences&id=737']);
      }
      if (type==='sequences') {
        assert.equal(column(byKey('frame1'),'key_name').textContent,'Animation frame 1');
        assert.equal(column(byKey('frame1'),'type').textContent,'animframe');
        assert.equal(column(byKey('frame1'),'parsed_val').textContent,'animframe_16905_1');
        assert.equal(column(byKey('delay1'),'parsed_val').textContent,'2');
      }
      if (type==='spoteffects') assert.ok(column(byKey('anim'),'parsed_val').querySelector('a').getAttribute('href').startsWith('index.html?type=sequences&id='));
      if (['mapsceneicons','hitsplats','healthbars'].includes(type)) {
        assert.ok(doc.querySelector('.config-graphic > img').src.includes('/rs3-graphic/'));
        assert.ok(doc.querySelector('.graphic-value > img'));
      }
    } finally { dom.window.close(); }
  }

  dom = await open('?type=varplayerbits&id=0');
  try {
    const rows = [...dom.window.document.querySelector('main > .table-wrap > table').tBodies[0].rows];
    const base = rows.find(row=>column(row,'raw_key').textContent==='basevar');
    assert.equal(column(base,'parsed_val').querySelector('a').getAttribute('href'),'index.html?type=varplayers&id=4');
  } finally { dom.window.close(); }

  for (const [type,search,label,text,id] of [
    ['quickchatphrases','What is your level in Agility?','Phrase','What is your level in Agility?',0],
    ['quickchatcategories','Group events','Description','Group events',0],
  ]) {
    dom = await open(`?type=${type}&q=${encodeURIComponent(search)}`);
    try {
      const doc = dom.window.document;
      const view = doc.querySelector('main > .table-wrap > table');
      assert.deepEqual([...view.tHead.rows[0].cells].map(cell=>cell.textContent),['id','name',label,'size','refs']);
      assert.equal(view.tBodies[0].rows.length,1);
      assert.equal(view.tBodies[0].rows[0].cells[0].querySelector('a').getAttribute('href'),`index.html?type=${type}&id=${id}`);
      assert.equal(view.tBodies[0].rows[0].cells[2].textContent,text);
      assert.ok(doc.querySelector('#config-type').selectedOptions[0].textContent.startsWith('Quick Chat'));
      doc.querySelector('input[type=search]').value='no matching quick chat fixture';
      doc.querySelector('input[type=search]').dispatchEvent(new dom.window.Event('input'));
      assert.equal(view.tBodies[0].rows[0].textContent,'No matching records.');
    } finally { dom.window.close(); }
  }

  dom = await open('?type=quickchatcategories&id=0');
  try {
    const doc = dom.window.document;
    const rows = [...doc.querySelector('main > .table-wrap > table').tBodies[0].rows];
    const subcategories = rows.filter(row=>column(row,'raw_key').textContent==='subcat');
    assert.equal(subcategories.length,5);
    assert.equal(column(subcategories[0],'type').textContent,'chatcat, int');
    assert.equal(column(subcategories[0],'parsed_val').querySelector('a').getAttribute('href'),'index.html?type=quickchatcategories&id=1');
    assert.equal(column(subcategories[0],'parsed_val').textContent,'1: Organising, o (111)');
    assert.ok(rows.some(row=>[...column(row,'parsed_val').querySelectorAll('a')].some(a=>a.getAttribute('href')==='index.html?type=quickchatphrases&id=242')));
    assert.equal(doc.querySelector('.config-shortcuts'),null);
  } finally { dom.window.close(); }

  dom = await open('?type=quickchatphrases&id=1');
  try {
    const doc = dom.window.document;
    const rows = [...doc.querySelector('main > .table-wrap > table').tBodies[0].rows];
    const phrase = rows.find(row=>column(row,'raw_key').textContent==='phrase');
    assert.equal(column(phrase,'raw_val').textContent,'My Agility level is <stat_base(agility)>.');
    assert.equal(column(phrase,'parsed_val').textContent,'My Agility level is <stat_base(16: agility)>.');
    const responses = rows.filter(row=>column(row,'raw_key').textContent==='autoresponse');
    assert.equal(responses.length,6);
    assert.ok(responses.every(row=>column(row,'key_name').textContent==='Automatic response'));
    assert.ok(responses.every(row=>column(row,'parsed_val').querySelector('a').getAttribute('href').startsWith('index.html?type=quickchatphrases&id=')));
    const refs = section(doc,/^References/).flatMap(node=>[...node.querySelectorAll('a')]);
    assert.ok(refs.some(a=>a.getAttribute('href')==='index.html?type=quickchatphrases&id=0'));
    assert.equal(doc.querySelector('.browse-all').getAttribute('href'),'index.html?type=quickchatphrases');
  } finally { dom.window.close(); }

  for (const [id,type,target] of [[2,'enums',1505],[238,'varplayerbits',43415]]) {
    dom = await open(`?type=quickchatphrases&id=${id}`);
    try {
      const rows = [...dom.window.document.querySelector('main > .table-wrap > table').tBodies[0].rows];
      const phrase = rows.find(row=>column(row,'raw_key').textContent==='phrase');
      assert.ok([...column(phrase,'parsed_val').querySelectorAll('a')].some(a=>a.getAttribute('href')===`index.html?type=${type}&id=${target}`));
      assert.equal(column(phrase,'parsed_val').querySelectorAll('script,listdialog,tostring_varbit').length,0);
    } finally { dom.window.close(); }
  }

  dom = await open('?type=achievements&id=2241');
  try {
    const doc = dom.window.document;
    const fields = section(doc, 'Native fields');
    const fieldRows = [...fields.find(n => n.classList.contains('table-wrap')).querySelector('tbody').children];
    const requirement = fieldRows.find(r => r.cells[0].textContent === 'varbitreq');
    assert.ok(requirement, 'Missing grouped agility requirements');
    assert.equal(requirement.cells[1].textContent, 'Varbit requirements');
    const courses = requirement.querySelectorAll('.parsed-table tbody tr');
    assert.equal(courses.length, 16);
    assert.equal(courses[0].cells[2].textContent, 'Burthorpe');
    assert.equal(courses[0].cells[3].querySelector('a').getAttribute('href'), 'index.html?type=varplayerbits&id=42394');
    assert.ok([...courses].some(r => r.cells[2].textContent === "Het's Oasis Agility Course"));
    const description = fieldRows.find(r => r.cells[0].textContent === 'desc');
    assert.equal(description.cells[1].textContent, 'Description');
    assert.equal(column(description,'parsed_val').textContent, 'Complete each of the listed agility courses at least once.');
    assert.ok([...doc.querySelectorAll('img')].some(img => img.src.endsWith('/30108-0.png')));
    assert.ok([...doc.querySelectorAll('a')].some(a => a.getAttribute('href') === 'index.html?type=achievements&id=1784'));
    assert.ok(![...doc.querySelectorAll('h2')].some(h => h.textContent === 'cs2 params'));
  } finally { dom.window.close(); }

  for (const [query, name, type] of [['?type=params&id=31','Destroy on drop','int'], ['?type=achievement_params&id=varbitreq','Varbit requirements','int, int, string, varbit[]']]) {
    dom = await open(query);
    try {
      const doc = dom.window.document;
      const metadata = doc.querySelector('main > .table-metadata');
      assert.equal(metadata.hidden, false);
      const values = Object.fromEntries([...metadata.children].map(pair => [pair.dataset.column,pair.querySelector('dd').textContent]));
      assert.deepEqual(values, query.includes('achievement_params') ? {key_name:name,type} : {autodisable:'no',type,default:'0',key_name:name});
      if (query.includes('type=params')) {
        assert.equal(doc.querySelectorAll('main > .table-wrap').length,1,'Only the parameter uses remain in a table');
        assert.equal(metadata.querySelectorAll('[data-column="type"]').length,1);
        assert.equal(doc.querySelector('.config-shortcuts'),null);
      }
      const view = query.includes('achievement_params') ? doc.querySelector('main > .table-wrap > table') : section(doc, /^Parameter uses /).find(n => n.classList.contains('table-wrap')).querySelector('table');
      assert.deepEqual([...view.tHead.rows[0].cells].map(c => c.textContent), ['raw_key','raw_val','parsed_val']);
      assert.ok(view.tBodies[0].rows[0].querySelector('a'));
    } finally { dom.window.close(); }
  }

  const mixed = {id:3,name:'pagination_test',references:[],rows:Array.from({length:251},(_,i)=>({key:'name',key_name:i===250?'other':'name',raw:String(i),type:i===250?'int':'string',parsed:[{text:String(i)}]}))};
  dom = await open('?type=items&id=3', {'3':mixed});
  try {
    const view = dom.window.document.querySelector('main > .table-wrap > table');
    assert.deepEqual([...view.tHead.rows[0].cells].map(c => c.textContent), ['raw_key','key_name','raw_val','type','parsed_val']);
    assert.equal(view.tBodies[0].rows.length,250);
  } finally { dom.window.close(); }

  mixed.rows.forEach(row => { row.key_name = 'name'; });
  dom = await open('?type=items&id=3', {'3':mixed});
  try {
    const view = dom.window.document.querySelector('main > .table-wrap > table');
    assert.deepEqual([...view.tHead.rows[0].cells].map(c => c.textContent), ['raw_key','raw_val','type','parsed_val']);
    const summary = section(dom.window.document,'Native fields').find(n => n.classList.contains('table-metadata'));
    assert.equal(summary.querySelector('dd').textContent,'Name');
  } finally { dom.window.close(); }

  const item = {id: 3, name: 'example', rows: [{key: 'name', raw: 'Example', parsed: [{text: 'Example'}]}], references: []};
  dom = await open('?type=items&id=3', {'3': item});
  try {
    assert.match(section(dom.window.document, 'cs2 params').map(n => n.textContent).join(''), /does not have cs2 params/);
  } finally { dom.window.close(); }

  item.rows.push({kind:'param', key:'unlisted_param', raw:'1', type:'unknown', parsed:[{text:'1'}]});
  dom = await open('?type=items&id=3', {'3': item});
  try {
    const nodes = section(dom.window.document, 'cs2 params');
    assert.ok(nodes.some(n => n.textContent.includes('unlisted_param')));
    assert.ok(!nodes.some(n => n.querySelector('a')));
    assert.ok(!section(dom.window.document, 'Native fields').some(n => n.textContent.includes('unlisted_param')));
  } finally { dom.window.close(); }
  console.log('Passed: Quick Chat browsing/search/templates/references, database tables/pagination/item quantities, inventory, cursor previews/hotspots/reference batching, scenery, config rendering, metadata, achievements and parameters.');
}

async function smoke() {
  const manifest = JSON.parse(fs.readFileSync(path.join(dataRoot,'data/manifest.json'),'utf8'));
  for (const [type,count] of Object.entries(manifest.counts)) {
    const compressed = manifest.compression === 'gzip';
    let bytes = fs.readFileSync(path.join(dataRoot,`data/${type}/index.json${compressed ? '.gz' : ''}`));
    if (compressed) bytes = gunzipSync(bytes);
    const entries = JSON.parse(bytes.toString('utf8'));
    assert.equal(entries.length,count,`${type} index count`);
    let dom = await open(`?type=${type}`);
    try {
      const doc = dom.window.document;
      assert.equal(doc.querySelector('main .error'),null,`${type} listing failed`);
      assert.equal(doc.querySelector('#config-type').value,type);
      assert.equal(doc.querySelectorAll('main > .table-wrap > table > tbody > tr').length,Math.max(1,Math.min(100,count)));
    } finally { dom.window.close(); }
    if (!entries.length) continue;
    const entry = entries.find(entry=>entry.size>0) || entries[0];
    dom = await open(`?type=${type}&id=${encodeURIComponent(entry.id)}`);
    try {
      const doc = dom.window.document;
      assert.equal(doc.querySelector('main .error'),null,`${type} detail failed`);
      assert.ok(doc.querySelector('h1').textContent.startsWith(`${type.toUpperCase()} #${entry.id}`));
      assert.equal(doc.querySelector('.browse-all').getAttribute('href'),`index.html?type=${type}`);
    } finally { dom.window.close(); }
  }
  console.log(`Passed: listing and detail rendering for all ${Object.keys(manifest.counts).length} generated config types (${manifest.compression || 'plain'} JSON).`);
}

async function historyChecks() {
  function expandHistory(dom) {
    const entries = [...dom.window.document.querySelectorAll('.history-entry')];
    assert.ok(entries.length);
    assert.ok(entries.every(entry => !entry.open),'All history entries start collapsed');
    assert.equal(dom.window.document.querySelector('.history-table'),null,'History tables render only when opened');
    entries[0].open = true;
    entries[0].dispatchEvent(new dom.window.Event('toggle'));
  }
  function format(dom,value) {
    const input = dom.window.document.querySelector(`.history-format input[value="${value}"]`);
    assert.ok(input,`History ${value} toggle exists`);
    input.checked = true;
    input.dispatchEvent(new dom.window.Event('change',{bubbles:true}));
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(dataRoot,'data/manifest.json'),'utf8'));
  manifest.history = {chunkSize:64,chunks:{items:[0]},types:['items'],from:'2026-11-01',through:'2026-11-02',typePages:{struct:'structs'},
    reports:[{before:{date:'2026-11-01',sha:'a'.repeat(40)},after:{date:'2026-11-02',revision:'951',sha:'b'.repeat(40)}}]};
  const fields = Array.from({length:101}, (_,i)=>({field:`field${i}`,before_field:`field${i}`,after_field:`field${i}`,
    before:i===0 ? null : ['','null','<img src=x onerror=alert(1)>'], after:['same_name'],
    before_references:i===1 ? [{type:'struct',id:624},{type:'model',id:99}] : [],
    after_references:i===1 ? [{type:'struct',id:625}] : []}));
  fields[100].after_parsed = [{type:'structs',id:625,text:'Historical struct'}];
  const replacements = new Map([
    ['data/manifest.json',manifest], ['data/items/0.json',null],
    ['data/history/items/0.json',{'3':{id:3,name:'removed_example',events:[{report:0,kind:'removed',fields}]}}],
  ]);
  let dom = await open('?type=items&id=3',replacements);
  try {
    const doc = dom.window.document;
    assert.equal(doc.querySelector('.error'),null);
    assert.match(doc.querySelector('main').textContent,/not present in the current dump/);
    assert.ok(doc.querySelector('#history'));
    expandHistory(dom);
    const view = doc.querySelector('.history-table');
    assert.equal(view.tBodies[0].rows.length,100);
    assert.equal(view.tBodies[0].rows[0].cells[1].textContent,'Not present');
    assert.match(view.tBodies[0].rows[1].cells[1].textContent,/"" \(empty string\)/);
    assert.equal(view.querySelector('img[src="x"]'),null,'Historical values must render as text');
    assert.equal(view.querySelector('a'),null,'History must not show reference links');
    assert.ok(!view.textContent.includes('struct #624'));
    assert.ok(!view.textContent.includes('model #99'));
    doc.querySelector('.history-entry > button').click();
    assert.equal(view.tBodies[0].rows.length,101);
    assert.equal(doc.querySelector('.history-entry > button').hidden,true);
    assert.equal(doc.querySelector('.history-format input[value="raw"]').checked,true);
    format(dom,'parsed');
    assert.equal(view.tBodies[0].rows.length,101,'Toggling preserves expanded field pagination');
    const last = view.tBodies[0].rows[100];
    assert.equal(last.cells[2].querySelector('a').getAttribute('href'),'index.html?type=structs&id=625');
    assert.equal(view.querySelector('img[src="x"]'),null,'Parsed fallback text remains safe');
    assert.equal(view.tBodies[0].rows[0].cells[1].textContent,'Not present');
    format(dom,'raw');
    assert.equal(view.querySelector('a'),null);
    assert.equal(last.cells[2].textContent,'same_name');
  } finally { dom.window.close(); }
  const changedFields = [
    {field:'statprereq',before:['0,115,Skill: 115 Slayer,slayer'],after:['0,95,Skill: 95 Slayer,slayer'],
      before_references:[{value_index:0,path:[3],type:'stat',id:18}],after_references:[{value_index:0,path:[3],type:'stat',id:18}]},
    {field:'repeated',before:['one','two'],after:['new','one','two']},
    {field:'empty',before:[''],after:['value']},
    {field:'empty_unchanged',before:['','old'],after:['','new']},
    {field:'punctuation',before:['café: 10!'],after:['café: 10?']},
    {field:'reference_only',before:['same_name'],after:['same_name'],before_references:[{type:'model',id:99}],after_references:[{type:'model',id:100}]},
    {field:'long',before:['prefix ' + 'old,'.repeat(400) + ' suffix'],after:['prefix ' + 'new;'.repeat(400) + ' suffix']},
    {field:'removed',before:['gone'],after:null},
    {field:'added_empty',before:null,after:['']},
  ];
  replacements.set('data/history/items/0.json',{'3':{id:3,name:'diff_example',events:[{report:0,kind:'modified',fields:changedFields}]}});
  dom = await open('?type=items&id=3',replacements);
  try {
    const doc = dom.window.document;
    expandHistory(dom);
    const rows = [...doc.querySelectorAll('.history-table tbody tr')];
    const highlights = (cell,tag) => [...cell.querySelectorAll(`.history-value ${tag}`)].map(node=>node.textContent);
    assert.deepEqual(highlights(rows[0].cells[1],'del'),['115','115']);
    assert.deepEqual(highlights(rows[0].cells[2],'ins'),['95','95']);
    assert.equal(rows[0].querySelector('.history-reference'),null,'Unchanged unsupported metadata must not appear as raw diff text');
    assert.equal(rows[0].cells[1].textContent,changedFields[0].before[0]);
    assert.equal(rows[0].cells[2].textContent,changedFields[0].after[0]);
    assert.deepEqual(highlights(rows[1].cells[1],'del'),[]);
    assert.deepEqual(highlights(rows[1].cells[2],'ins'),['new']);
    assert.equal(rows[1].cells[1].textContent,'onetwo');
    assert.deepEqual(highlights(rows[2].cells[1],'del'),['"" (empty string)']);
    assert.deepEqual(highlights(rows[3].cells[1],'del'),['old']);
    assert.deepEqual(highlights(rows[4].cells[1],'del'),['!']);
    assert.deepEqual(highlights(rows[4].cells[2],'ins'),['?']);
    assert.deepEqual(highlights(rows[5].cells[1],'del'),[],'Equal raw text must not be marked as changed');
    assert.equal(rows[5].cells[1].textContent,'same_name');
    assert.equal(rows[5].cells[2].textContent,'same_name');
    assert.equal(doc.querySelector('.history-reference'),null,'History must not show resolved reference labels');
    assert.equal(rows[6].cells[1].textContent,changedFields[6].before[0]);
    assert.equal(rows[6].cells[2].textContent,changedFields[6].after[0]);
    assert.ok(!highlights(rows[6].cells[1],'del').join('').includes('prefix'));
    assert.ok(!highlights(rows[6].cells[2],'ins').join('').includes('suffix'));
    assert.deepEqual(highlights(rows[7].cells[1],'del'),['gone']);
    assert.deepEqual(highlights(rows[8].cells[2],'ins'),['"" (empty string)']);
  } finally { dom.window.close(); }
  const parameterFields = [
    {field:'param[param_1326]',identity:{field:'param',entry:{type:'param',id:1326}},before:['12'],after:null},
    {field:'param[param_751]',identity:{field:'param',entry:{type:'param',id:751}},before:['attack'],after:['strength']},
    {field:'param[param_237]',identity:{field:'param',entry:{type:'param',id:237}},before:['0'],after:['1']},
    {field:'param[param_999999]',identity:{field:'param',entry:{type:'param',id:999999}},before:['0'],after:['1']},
    {field:'param[historical_only_name]',identity:{field:'param',entry:{type:'param',id:999998}},before:['0'],after:['1']},
    {field:'param[param_5551]',before:['old'],after:['new']},
    {field:'param[param_1326]',identity:{field:'param',entry:{type:'param',id:5551}},before:['old'],after:['new']},
  ];
  replacements.set('data/history/items/0.json',{'3':{id:3,name:'parameter_labels',events:[{report:0,kind:'modified',fields:parameterFields}]}});
  replacements.set('data/params/index.json',[
    {id:1326,name:'constitution_increase'},{id:751,name:'wear_requires_stat2'},
    {id:237,name:'param_237'},{id:5551,name:'invent_augmented_version'},
  ]);
  dom = await open('?type=items&id=3',replacements);
  try {
    const doc = dom.window.document;
    expandHistory(dom);
    const rows = [...doc.querySelectorAll('.history-table tbody tr')];
    const labels = rows.map(row => row.querySelector('.history-field-label').textContent);
    assert.deepEqual(labels,['Constitution increase','Wear requires stat 2','Is god arrows 2','Parameter 999999','Historical only name','Invent augmented version','Invent augmented version']);
    assert.deepEqual(rows.map(row => row.cells[0].querySelector('code').textContent),parameterFields.map(field=>field.field),'Historical field keys remain verbatim');
    assert.equal(rows[0].querySelector('.history-field-label').title,'Current parameter name: constitution_increase (ID 1326)');
    assert.equal(rows[0].cells[0].querySelector('a'),null,'Field labels do not add reference links');
    format(dom,'parsed');
    assert.deepEqual(rows.map(row=>row.querySelector('.history-field-label').textContent),labels);
    assert.equal(rows[0].cells[0].querySelector('code').textContent,'param[param_1326]');
  } finally { dom.window.close(); }
  replacements.delete('data/params/index.json');
  replacements.set('data/items/0.json',{'4':{id:4,name:'unchanged',rows:[],references:[]}});
  dom = await open('?type=items&id=4',replacements);
  try {
    assert.match(dom.window.document.querySelector('main').textContent,/No changes recorded in the imported comparisons/);
  } finally { dom.window.close(); }
  console.log('Passed: history text highlighting without references, removed configs, coverage and field pagination.');
  const actual = JSON.parse(fs.readFileSync(path.join(dataRoot,'data/manifest.json'),'utf8'));
  if (actual.revision === 'd215783ad35d9c7ff2e6d3562ebfd0a0abbde916' && actual.history) {
    dom = await open('?type=enums&id=1467');
    try {
      const doc = dom.window.document;
      assert.match(doc.querySelector('.history-entry').textContent,/2026-11-17/);
      expandHistory(dom);
      const row = doc.querySelector('.history-table tbody tr');
      assert.match(row.cells[1].textContent,/login_facebook_data/);
      assert.equal(row.cells[2].textContent,'Not present');
      assert.equal(row.cells[1].textContent,'login_facebook_data');
      assert.equal(row.querySelector('a'),null);
      format(dom,'parsed');
      const target = row.cells[1].querySelector('a');
      assert.equal(target.getAttribute('href'),'index.html?type=structs&id=624');
      assert.ok(!row.textContent.includes('References:'));
      format(dom,'raw');
      assert.equal(row.cells[1].textContent,'login_facebook_data');
    } finally { dom.window.close(); }
    dom = await open('?type=items&id=231');
    try {
      expandHistory(dom);
      const row = dom.window.document.querySelector('.history-table tbody tr');
      assert.match(row.cells[0].textContent,/param\[levelrequire\]/);
      assert.equal(row.cells[1].textContent,'80');
      assert.equal(row.cells[2].textContent,'34');
    } finally { dom.window.close(); }
    dom = await open('?type=achievements&id=1350');
    try {
      const doc = dom.window.document;
      expandHistory(dom);
      const row = [...doc.querySelectorAll('.history-table tbody tr')].find(row=>row.cells[0].textContent.includes('statprereq'));
      assert.ok(row,'Achievement 1350 includes the Slayer prerequisite change');
      assert.deepEqual([...row.cells[1].querySelectorAll('del')].map(node=>node.textContent),['115','115']);
      assert.deepEqual([...row.cells[2].querySelectorAll('ins')].map(node=>node.textContent),['95','95']);
      assert.ok(!row.textContent.includes('stat #18'));
      format(dom,'parsed');
      assert.equal(row.querySelectorAll('.parsed-table').length,2,'Parsed prerequisites use the standard requirement tables');
      assert.deepEqual([...row.cells[1].querySelectorAll('del')].map(node=>node.textContent),['115','115']);
      assert.deepEqual([...row.cells[2].querySelectorAll('ins')].map(node=>node.textContent),['95','95']);
      assert.ok(!row.textContent.includes('stat #18'));
      format(dom,'raw');
      assert.equal(row.querySelector('.parsed-table'),null);
    } finally { dom.window.close(); }
    console.log('Passed: imported enum 1467, item 231 and achievement 1350 history.');
  }
}

(async () => { await historyChecks(); await (process.argv.includes('--smoke') ? smoke() : run()); })().catch(error => { console.error(error); process.exitCode = 1; });
