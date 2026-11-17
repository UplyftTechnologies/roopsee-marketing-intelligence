// Roopsee Ads Launcher UI - plain ES modules, no build step. All text goes through textContent (never innerHTML).
const $ = (s, r = document) => r.querySelector(s);

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'hidden') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: { 'X-Launcher': '1' } };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 3500);
}
const fail = (e) => toast('Error: ' + (e.message || e));

let S = null;          // /api/state
let CFG = null;        // /api/config
const reload = async () => { S = await api('/api/state'); CFG = await api('/api/config'); };

// ---- shared pieces ------------------------------------------------------------------------------------------------------
function Msgs(res) {
  const box = h('div');
  (res.errors || []).forEach((e) => box.append(h('div', { class: 'msg bad' }, e)));
  (res.warnings || []).forEach((e) => box.append(h('div', { class: 'msg warn' }, e)));
  if (!(res.errors || []).length) box.append(h('div', { class: 'msg good' }, `Valid (${(res.warnings || []).length} warning(s))`));
  return box;
}

function Field(label, input, hint) {
  return h('label', { class: 'f' }, h('span', {}, label), input, hint ? h('span', { class: 'sub' }, hint) : null);
}

function Counter(label, input, limit) {
  const c = h('span', { class: 'count' });
  const upd = () => { const n = input.value.length; c.textContent = `${n}/${limit}`; c.className = 'count' + (n > limit ? ' over' : ''); };
  input.addEventListener('input', upd); upd();
  return h('label', { class: 'f' }, h('span', {}, label, c), input);
}

function Log() {
  const el = h('pre', { class: 'log' }, 'Nothing run yet.');
  return el;
}

/** Runs a command on the server and streams its log into `logEl`. */
async function runJob(body, logEl) {
  logEl.textContent = '...';
  const { job } = await api('/api/run', { method: 'POST', body });
  for (;;) {
    const j = await api('/api/jobs/' + job);
    logEl.textContent = j.log || '...';
    logEl.scrollTop = logEl.scrollHeight;
    if (j.status === 'done') return j;
    await new Promise((r) => setTimeout(r, 600));
  }
}

const batchOptions = (sel) => S.batches.map((b) => h('option', { value: b.name, selected: b.name === sel }, `${b.name}${b.frozen ? ' (frozen)' : ''} - ${b.ready}/${b.ads} ready`));

// ---- Health ---------------------------------------------------------------------------------------------------------------
async function Health() {
  const log = Log();
  const checks = h('div', { class: 'checks' }, h('div', { class: 'muted' }, 'Run the health check to see the results.'));
  const run = async () => {
    btn.disabled = true;
    try {
      const j = await runJob({ command: 'doctor' }, log);
      checks.replaceChildren();
      for (const ln of j.log.split('\n')) {
        const m = ln.match(/^\s+(OK|FAIL|note|skip)\s+(.*)$/);
        if (m) checks.append(h('div', {}, h('span', { class: 'pill ' + (m[1] === 'OK' ? 'good' : m[1] === 'FAIL' ? 'bad' : 'warn') }, m[1]), h('span', {}, m[2])));
      }
      if (!checks.children.length) checks.append(h('div', { class: 'msg bad' }, j.log));
    } catch (e) { fail(e); }
    btn.disabled = false;
  };
  const btn = h('button', { class: 'primary', onclick: run }, 'Run health check');
  const liveLog = Log(); liveLog.hidden = true;
  const showLive = async () => { liveLog.hidden = false; try { await runJob({ command: 'live' }, liveLog); } catch (e) { fail(e); } };
  const ents = Object.entries(S.entities);
  const ads = Object.entries(S.ads);
  return h('div', {},
    h('div', { class: 'card' }, h('div', { class: 'row' }, h('h2', { class: 'grow' }, 'Health check'), btn),
      h('div', { class: 'sub' }, `Read-only. Checks credentials, token, permissions, ad account (${S.account || 'not set'}) and Page (${S.page_id || 'not set'}).`),
      S.missing.length ? h('div', { class: 'msg bad' }, 'Missing in .env: ' + S.missing.join(', ')) : null, checks, log),
    h('div', { class: 'card' }, h('div', { class: 'row' }, h('h3', { class: 'grow' }, 'What exists on Meta (' + S.env + ')'), h('button', { onclick: showLive }, 'Show live from Meta')), liveLog,
      ents.length ? h('table', { class: 'tbl' }, h('tr', {}, h('th', {}, 'Item'), h('th', {}, 'Meta id'), h('th', {}, 'Status')),
        ents.map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', {}, v.id || ''), h('td', {}, h('span', { class: 'pill' }, v.status || ''))))) : h('div', { class: 'muted' }, 'Nothing created yet.'),
      ads.length ? h('div', { class: 'sub' }, `${ads.length} ad(s): ` + ads.map(([k, v]) => `${k} (${v.status})`).join(', ')) : null));
}

// ---- Library --------------------------------------------------------------------------------------------------------------
async function Library() {
  const items = await api('/api/creatives');
  const cats = [...new Set(items.map((i) => i.category))];
  const file = h('input', { type: 'file', accept: '.jpg,.jpeg,.png' });
  const cat = h('input', { list: 'cats', placeholder: 'acne', value: cats[0] || '' });
  const key = h('input', { placeholder: 'RS_ACNE_001' });
  const suggest = () => {
    const c = (cat.value || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (!c) return;
    const used = items.filter((i) => i.key.startsWith(`RS_${c}_`)).map((i) => parseInt(i.key.split('_').pop(), 10) || 0);
    key.value = `RS_${c}_${String(Math.max(0, ...used) + 1).padStart(3, '0')}`;
  };
  cat.addEventListener('input', suggest); if (cat.value) suggest();
  const drop = h('div', { class: 'drop' }, 'Drop an image here, or choose a file');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) { file.files = e.dataTransfer.files; drop.textContent = e.dataTransfer.files[0].name; } });
  file.addEventListener('change', () => { if (file.files[0]) drop.textContent = file.files[0].name; });
  const save = async () => {
    if (!file.files[0]) return toast('Choose an image first');
    const fd = new FormData(); fd.append('file', file.files[0]); fd.append('category', cat.value.trim().toLowerCase()); fd.append('ad_key', key.value.trim());
    try { const r = await api('/api/creatives', { method: 'POST', body: fd }); toast(`Saved ${r.saved} (${r.width}x${r.height})`); route(); } catch (e) { fail(e); }
  };
  const metaLog = Log(); metaLog.hidden = true;
  const listMeta = async () => { metaLog.hidden = false; try { await runJob({ command: 'images' }, metaLog); } catch (e) { fail(e); } };
  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Creative library'),
      h('div', { class: 'sub' }, 'Images are saved to creatives/<category>/<KEY>.jpg|png. The file name is the ad key, and keys are never reused. Use 1080px+ wide, 1:1 or 4:5.'),
      drop, file,
      h('div', { class: 'grid g2' }, Field('Category (folder)', cat), Field('Ad key', key, 'RS_<CATEGORY>_<NNN>')),
      h('datalist', { id: 'cats' }, cats.map((c) => h('option', { value: c }))),
      h('div', { class: 'row' }, h('button', { class: 'primary', onclick: save }, 'Save to library'), h('button', { onclick: listMeta }, 'List images already on Meta (hashes)')), metaLog),
    h('div', { class: 'thumbs' }, items.length ? items.map((i) => {
      const warn = i.width && i.width < 1080;
      return h('div', { class: 'thumb' }, h('img', { src: '/' + i.path, alt: i.key }),
        h('div', {}, h('b', {}, i.key), h('span', { class: 'sub' }, `${i.category} - ${i.width}x${i.height} - ${(i.bytes / 1024).toFixed(0)} KB`),
          h('div', {}, h('span', { class: 'pill ' + (i.hash ? 'good' : '') }, i.hash ? 'on Meta' : 'not uploaded'), warn ? h('span', { class: 'pill warn' }, 'small') : null),
          h('button', { class: 'small', onclick: () => { location.hash = '#/ads?image=' + encodeURIComponent(i.path); } }, 'Create ad')));
    }) : h('div', { class: 'muted' }, 'No images yet.')));
}

// ---- Ads (builder) --------------------------------------------------------------------------------------------------------
const CTA_TEXT = { LEARN_MORE: 'Learn more', SHOP_NOW: 'Shop now', SIGN_UP: 'Sign up', GET_OFFER: 'Get offer', ORDER_NOW: 'Order now', CONTACT_US: 'Contact us', SUBSCRIBE: 'Subscribe' };
let currentBatch = null;

async function Ads(params) {
  currentBatch = currentBatch || (S.batches[0] && S.batches[0].name) || 'batch_001';
  const { batch, frozen } = await api('/api/batches/' + currentBatch);
  const lib = await api('/api/creatives');
  const adsets = (CFG.adsets && CFG.adsets.adsets) || [];
  const holder = h('div');
  const result = h('div');

  const saveBatch = async () => {
    try { const r = await api('/api/batches/' + currentBatch, { method: 'PUT', body: batch }); result.replaceChildren(Msgs(r)); toast('Batch saved'); await reload(); } catch (e) { fail(e); }
  };

  const edit = (idx, preset) => {
    const ad = Object.assign({ ad_key: '', adset_key: adsets[0] ? adsets[0].key : '', primary_text: '', headline: '', cta: 'LEARN_MORE', destination: 'https://roopsee.com/', status: 'DRAFT' }, preset || (idx != null ? batch.ads[idx] : {}));
    const useHash = h('input', { type: 'checkbox', checked: !!ad.image_hash });
    const key = h('input', { value: ad.ad_key, placeholder: 'RS_ACNE_001', disabled: idx != null });
    const set = h('select', {}, adsets.map((a) => h('option', { value: a.key, selected: a.key === ad.adset_key }, a.key)));
    const img = h('select', {}, h('option', { value: '' }, '- choose from library -'), lib.map((i) => h('option', { value: i.path, selected: i.path === ad.image }, `${i.key} (${i.width}x${i.height})`)));
    const hash = h('input', { value: ad.image_hash || '', placeholder: '32-character image hash' });
    const pt = h('textarea', { value: ad.primary_text });
    const hl = h('input', { value: ad.headline });
    const ds = h('input', { value: ad.description || '' });
    const cta = h('select', {}, S.enums.ctas.map((c) => h('option', { value: c, selected: c === ad.cta }, CTA_TEXT[c] || c)));
    const url = h('input', { value: ad.destination });
    const st = h('select', {}, ['DRAFT', 'READY'].map((x) => h('option', { value: x, selected: x === ad.status }, x)));
    const pv = h('div', { class: 'preview' });
    const paint = () => {
      const src = !useHash.checked && img.value ? '/' + img.value : null;
      let host = ''; try { host = new URL(url.value).host; } catch { /* ignore */ }
      pv.replaceChildren(h('div', { class: 'ph' }, h('i', {}, 'R'), 'Roopsee.', h('span', { class: 'sub', style: 'font-weight:400' }, 'Sponsored')),
        h('div', { class: 'pt' }, pt.value || 'Primary text appears here'),
        src ? h('img', { src, alt: '' }) : h('div', { class: 'noimg' }, useHash.checked ? 'Image from Meta hash (no local preview)' : 'No image selected'),
        h('div', { class: 'cta' }, h('div', {}, h('small', {}, host), h('b', {}, hl.value || 'Headline'), ds.value ? h('small', { style: 'text-transform:none' }, ds.value) : null), h('span', {}, CTA_TEXT[cta.value] || cta.value)));
    };
    [useHash, img, pt, hl, ds, cta, url].forEach((e) => e.addEventListener('input', paint));
    paint();
    const done = () => {
      const o = { ad_key: key.value.trim(), adset_key: set.value };
      if (useHash.checked) o.image_hash = hash.value.trim(); else o.image = img.value;
      Object.assign(o, { primary_text: pt.value, headline: hl.value });
      if (ds.value) o.description = ds.value;
      Object.assign(o, { cta: cta.value, destination: url.value.trim(), status: st.value });
      if (idx == null) batch.ads.push(o); else batch.ads[idx] = o;
      saveBatch().then(() => route());
    };
    holder.replaceChildren(h('div', { class: 'card' }, h('h3', {}, idx == null ? 'New ad' : 'Edit ' + ad.ad_key),
      h('div', { class: 'split' }, h('div', { class: 'grid' },
        h('div', { class: 'grid g2' }, Field('Ad key', key, 'RS_<ANGLE>_<NNN>, must match the image file name'), Field('Ad set', set)),
        h('fieldset', {}, h('legend', {}, 'Image'), h('label', { class: 'chk' }, useHash, 'Use an image already on Meta (hash)'), Field('Library image', img), Field('Image hash', hash, 'List yours in the Library tab')),
        Counter('Primary text (about 125 chars shown before "See more")', pt, 125), Counter('Headline', hl, 40), Field('Description (optional)', ds),
        h('div', { class: 'grid g2' }, Field('Call to action', cta), Field('Status', st, 'DRAFT is checked but never sent; READY is launched')),
        Field('Destination URL', url, 'Plain https URL. UTM tags are added automatically'),
        h('div', { class: 'row' }, h('button', { class: 'primary', onclick: done }, 'Save ad'), h('button', { onclick: () => route() }, 'Cancel'))), pv)));
    holder.scrollIntoView({ behavior: 'smooth' });
  };

  const sel = h('select', { onchange: (e) => { currentBatch = e.target.value; route(); } }, batchOptions(currentBatch));
  const newBatch = () => {
    const n = prompt('New batch name (for example batch_002)'); if (!n) return;
    api('/api/batches/' + n, { method: 'PUT', body: { batch_id: 'ROOPSEE_' + n.toUpperCase(), ads: [] } }).then(async () => { currentBatch = n; await reload(); route(); }).catch(fail);
  };
  const rows = batch.ads.map((a, i) => h('tr', {},
    h('td', {}, a.ad_key), h('td', {}, a.adset_key), h('td', {}, a.image_hash ? 'hash ' + a.image_hash.slice(0, 8) + '...' : a.image || ''),
    h('td', {}, a.headline), h('td', {}, h('span', { class: 'pill ' + (a.status === 'READY' ? 'good' : '') }, a.status)),
    h('td', {}, frozen ? null : [h('button', { class: 'small', onclick: () => edit(i) }, 'Edit'), ' ',
      h('button', { class: 'small danger', onclick: () => { if (confirm('Remove ' + a.ad_key + ' from this batch?')) { batch.ads.splice(i, 1); saveBatch().then(() => route()); } } }, 'Remove')])));
  const view = h('div', {},
    h('div', { class: 'card' }, h('div', { class: 'row' }, h('h2', { class: 'grow' }, 'Ads'), sel, h('button', { onclick: newBatch }, 'New batch'),
      h('button', { class: 'primary', disabled: frozen || !adsets.length, onclick: () => edit(null) }, 'Add ad')),
      frozen ? h('div', { class: 'msg warn' }, 'This batch was already submitted and is frozen. Put changes in a new batch with new ad keys.') : null,
      !adsets.length ? h('div', { class: 'msg warn' }, 'Create an ad set first (Setup tab).') : null,
      h('table', { class: 'tbl' }, h('tr', {}, ['Key', 'Ad set', 'Image', 'Headline', 'Status', ''].map((t) => h('th', {}, t))), rows.length ? rows : h('tr', {}, h('td', { colspan: 6, class: 'muted' }, 'No ads in this batch yet.'))),
      result), holder);
  api('/api/validate?batch=' + currentBatch).then((r) => result.replaceChildren(Msgs(r))).catch(() => {});
  if (params.get('image') && !frozen) { const p = params.get('image'); const k = p.split('/').pop().replace(/\.[^.]+$/, ''); setTimeout(() => edit(null, { ad_key: k, image: p }), 0); }
  return view;
}

// ---- Setup (config editors) -----------------------------------------------------------------------------------------------
function ListEditor({ title, hint, name, top, items, fields, blank, extraSave }) {
  const state = items.map((x) => ({ ...x }));
  const out = h('div');
  const result = h('div');
  const draw = () => {
    out.replaceChildren(...state.map((it, i) => h('fieldset', {}, h('legend', {}, it.key || 'new'),
      h('div', { class: 'grid g2' }, fields.map((f) => f.render(it, draw))),
      h('button', { class: 'small danger', onclick: () => { state.splice(i, 1); draw(); } }, 'Remove'))));
  };
  draw();
  const save = async () => {
    try { const r = await api('/api/config/' + name, { method: 'PUT', body: extraSave(state) }); result.replaceChildren(Msgs(r)); toast(title + ' saved'); await reload(); } catch (e) { fail(e); }
  };
  return h('div', { class: 'card' }, h('h3', {}, title), h('div', { class: 'sub' }, hint), out,
    h('div', { class: 'row' }, h('button', { onclick: () => { state.push({ ...blank }); draw(); } }, 'Add'), h('button', { class: 'primary', onclick: save }, 'Save ' + title.toLowerCase())), result);
}

const fText = (k, label, hint) => ({ render: (it) => Field(label, h('input', { value: it[k] ?? '', oninput: (e) => (it[k] = e.target.value) }), hint) });
const fNum = (k, label, hint) => ({ render: (it) => Field(label, h('input', { type: 'number', value: it[k] ?? '', oninput: (e) => { it[k] = e.target.value === '' ? undefined : Number(e.target.value); } }), hint) });
const fSel = (k, label, opts, blank) => ({ render: (it) => Field(label, h('select', { onchange: (e) => (it[k] = e.target.value || undefined) }, blank ? h('option', { value: '' }, blank) : null, opts().map((o) => h('option', { value: o, selected: it[k] === o }, o)))) });

async function Setup() {
  const camps = (CFG.campaigns.campaigns || []);
  const sets = (CFG.adsets.adsets || []);
  const auds = Object.entries(CFG.audiences.audiences || {}).map(([key, v]) => ({ key, ...v, countries_text: (v.countries || []).join(', '), genders_text: (v.genders || []).join(',') }));
  const acc = CFG.account || {};
  const accState = { ...acc };
  const accResult = h('div');
  return h('div', {},
    h('div', { class: 'card' }, h('h2', {}, 'Setup'), h('div', { class: 'sub' }, 'These forms edit the files in config/. Everything is validated on save. Campaigns and ad sets are created PAUSED when you run the pipeline.')),
    ListEditor({ title: 'Campaigns', hint: 'Daily budget is in rupees (500 is sent to Meta as 50000). CBO needs a budget here; ABO puts budgets on the ad sets.', name: 'campaigns', top: 'campaigns', items: camps,
      blank: { key: '', objective: 'OUTCOME_TRAFFIC', budget_strategy: 'CBO', daily_budget: 500, status: 'PAUSED' },
      fields: [fText('key', 'Key (name on Meta)'), fSel('objective', 'Objective', () => S.enums.objectives), fSel('budget_strategy', 'Budget strategy', () => ['CBO', 'ABO']), fNum('daily_budget', 'Daily budget (INR)')],
      extraSave: (st) => ({ campaigns: st.map((c) => ({ ...c, status: 'PAUSED' })) }) }),
    ListEditor({ title: 'Ad sets', hint: 'Audience and placements. Conversion goals (OFFSITE_CONVERSIONS) need a pixel in .env.', name: 'adsets', top: 'adsets', items: sets,
      blank: { key: '', campaign_key: camps[0] ? camps[0].key : '', audience: auds[0] ? auds[0].key : '', placements: ['instagram'], optimization_goal: 'LINK_CLICKS' },
      fields: [fText('key', 'Key'), fSel('campaign_key', 'Campaign', () => camps.map((c) => c.key)), fSel('audience', 'Audience', () => auds.map((a) => a.key)),
        { render: (it) => Field('Placements', h('div', {}, S.enums.placements.map((p) => h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: (it.placements || []).includes(p), onchange: (e) => { const s = new Set(it.placements || []); e.target.checked ? s.add(p) : s.delete(p); it.placements = [...s]; } }), p)))) },
        fSel('optimization_goal', 'Optimisation goal', () => S.enums.goals), fText('optimization_event', 'Conversion event (e.g. PURCHASE)'), fNum('daily_budget', 'Daily budget (INR, ABO only)')],
      extraSave: (st) => ({ adsets: st.map((a) => { const o = { ...a }; if (!o.optimization_event) delete o.optimization_event; if (o.daily_budget === undefined) delete o.daily_budget; return o; }) }) }),
    ListEditor({ title: 'Audiences', hint: 'Countries as codes, comma separated. Genders: 1 men, 2 women, empty for everyone.', name: 'audiences', top: 'audiences', items: auds,
      blank: { key: '', countries_text: 'IN', age_min: 18, age_max: 45, genders_text: '' },
      fields: [fText('key', 'Name'), fText('countries_text', 'Countries'), fNum('age_min', 'Min age'), fNum('age_max', 'Max age'), fText('genders_text', 'Genders (1, 2 or empty)')],
      extraSave: (st) => ({ audiences: Object.fromEntries(st.map((a) => [a.key, { countries: String(a.countries_text || '').split(',').map((x) => x.trim().toUpperCase()).filter(Boolean), age_min: a.age_min, age_max: a.age_max, genders: String(a.genders_text || '').split(',').map((x) => parseInt(x, 10)).filter((x) => x === 1 || x === 2) }])) }) }),
    h('div', { class: 'card' }, h('h3', {}, 'Account and tracking'),
      h('div', { class: 'grid g2' }, Field('Currency', h('input', { value: acc.currency || '', oninput: (e) => (accState.currency = e.target.value) })), Field('Minor units per 1 currency unit', h('input', { type: 'number', value: acc.currency_offset || 100, oninput: (e) => (accState.currency_offset = Number(e.target.value)) }))),
      Field('URL tags (UTM template)', h('textarea', { value: acc.url_tags || '', oninput: (e) => (accState.url_tags = e.target.value) }), 'Meta replaces {{campaign.id}}, {{ad.id}}, {{adset.id}}; {ad_key} and {batch_id} are filled by the launcher'),
      h('button', { class: 'primary', onclick: async () => { try { const r = await api('/api/config/account', { method: 'PUT', body: accState }); accResult.replaceChildren(Msgs(r)); toast('Saved'); await reload(); } catch (e) { fail(e); } } }, 'Save account'), accResult));
}

// ---- Run ------------------------------------------------------------------------------------------------------------------
async function Run() {
  currentBatch = currentBatch || (S.batches[0] && S.batches[0].name) || 'batch_001';
  const log = Log();
  const sel = h('select', { onchange: (e) => { currentBatch = e.target.value; route(); } }, batchOptions(currentBatch));
  let mode = 'dry';
  const modes = [['dry', 'Dry run (sends nothing)'], ['check', 'Check with Meta (creates nothing)'], ['real', 'Run for real']];
  const modeBox = h('div', { class: 'row' }, modes.map(([v, l]) => h('label', { class: 'chk' }, h('input', { type: 'radio', name: 'mode', value: v, checked: v === mode, onchange: () => (mode = v) }), l)));
  const prod = S.env === 'production';
  const prodChk = h('input', { type: 'checkbox' });
  const buttons = [];
  const go = async (cmd, extra = {}) => {
    buttons.forEach((b) => (b.disabled = true));
    try {
      if (mode === 'real' && prod && !prodChk.checked) throw new Error('Production: tick the confirmation box first');
      await runJob({ command: cmd, batch: currentBatch, mode, confirm_production: prodChk.checked, ...extra }, log);
      await reload();
    } catch (e) { fail(e); }
    buttons.forEach((b) => (b.disabled = false));
  };
  const step = (n, cmd, label, desc) => { const b = h('button', { class: 'primary', onclick: () => go(cmd) }, label); buttons.push(b); return h('div', { class: 'row' }, h('span', { class: 'pill' }, n), b, h('span', { class: 'sub grow' }, desc)); };
  const confirm = h('input', { placeholder: 'type PUBLISH' });
  const pub = h('button', { class: 'danger', onclick: () => go('publish', { confirm_text: confirm.value }) }, 'Publish (activate)'); buttons.push(pub);
  const toPublish = Object.entries(S.ads).filter(([, v]) => v.batch === currentBatch && v.status !== 'ACTIVE');
  const sb = h('button', { onclick: async () => { buttons.forEach((b) => (b.disabled = true)); try { await runJob({ command: 'status', mode: 'real', live: true }, log); } catch (e) { fail(e); } buttons.forEach((b) => (b.disabled = false)); } }, 'Status (live from Meta)');
  const vb = h('button', { onclick: async () => { try { await runJob({ command: 'validate', batch: currentBatch }, log); } catch (e) { fail(e); } } }, 'Validate');
  return h('div', {},
    h('div', { class: 'card' }, h('div', { class: 'row' }, h('h2', { class: 'grow' }, 'Run the pipeline'), sel),
      h('div', { class: 'sub' }, 'Steps run in order. Start with Dry run, then Check with Meta, then Run for real. Everything is created PAUSED. Re-running a step is safe.'),
      modeBox,
      prod ? h('label', { class: 'chk' }, prodChk, h('b', {}, 'I understand this is PRODUCTION and will write to the real ad account')) : null,
      step('1', 'upload', 'Upload images', 'Sends each READY image once and stores its hash'),
      step('2', 'setup', 'Create campaign + ad set', 'PAUSED'),
      step('3', 'prepare', 'Create creative + ad', 'PAUSED; freezes the batch when complete'),
      h('div', { class: 'row' }, vb, sb)),
    h('div', { class: 'card' }, h('h3', {}, 'Review and publish'),
      toPublish.length ? h('table', { class: 'tbl' }, h('tr', {}, ['Ad', 'Ad set', 'Status'].map((t) => h('th', {}, t))), toPublish.map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', {}, v.adset_key), h('td', {}, h('span', { class: 'pill warn' }, v.status))))) : h('div', { class: 'muted' }, 'No paused ads in this batch yet. Run steps 1-3 first.'),
      h('div', { class: 'sub' }, 'Publishing switches the campaign, ad set and ad to ACTIVE. Meta reviews the ad, then it can spend. Only use "Run for real" mode.'),
      h('div', { class: 'row' }, confirm, pub)),
    h('div', { class: 'card' }, h('h3', {}, 'Log'), log));
}

// ---- shell ----------------------------------------------------------------------------------------------------------------
const TABS = { health: ['Health', Health], library: ['Library', Library], ads: ['Ads', Ads], setup: ['Setup', Setup], run: ['Run', Run] };

async function route() {
  const [path, qs] = (location.hash.replace(/^#\/?/, '') || 'health').split('?');
  const name = TABS[path] ? path : 'health';
  const params = new URLSearchParams(qs || '');
  const nav = $('#nav'); nav.replaceChildren(...Object.entries(TABS).map(([k, [l]]) => h('a', { href: '#/' + k, class: k === name ? 'on' : '' }, l)));
  const view = $('#view');
  try {
    if (!S) await reload();
    const bar = $('#envbar'); bar.className = 'envbar' + (S.env === 'production' ? ' prod' : '');
    bar.textContent = S.env === 'production' ? 'PRODUCTION - writes affect the real ad account' : `SANDBOX - no delivery, no spend  |  account ${S.account || '(not set)'}`;
    view.replaceChildren(await TABS[name][1](params));
  } catch (e) { view.replaceChildren(h('div', { class: 'msg bad' }, 'Error: ' + e.message)); }
}

window.addEventListener('hashchange', route);
route();
