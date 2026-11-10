function encodeObj(obj) {
  return btoa(encodeURIComponent(JSON.stringify(obj)));
}
function decodeObj(str) {
  return JSON.parse(decodeURIComponent(atob(str)));
}
function escapeHTML(value) {
  const entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(value ?? '').replace(/[&<>"']/g, char => entities[char]);
}

// Menu data, generated from Main_menu.csv (public/static/js/menu-variants.js).
// One entry per dish, keyed by dish name. Size labels are NOT in here:
// they come from the "(...)" suffixes on the actual menu rows, because the
// live menu says Regular/Large and the CSV says Small/Large for the same
// prices. Every priced choice is its own MenuItem row in the DB (checkout
// prices lines from MenuItem.price), so the sheet only picks which row
// goes into the cart. Nothing here invents a price.
const META = window.SUREN_MENU_META || {};
const META_INDEX = {};
Object.keys(META).forEach(k => { META_INDEX[normName(k)] = META[k]; });

function normName(name) {
  return String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

// "Simple Veg Pizza (Large) + Extra Cheese" -> "Simple Veg Pizza"
function baseName(rowName) {
  return rowName
    .replace(/ \+ (Extra Cheese|Schezwan)$/, '')
    .replace(/ \((Small|Large|Medium|Regular)\)$/, '');
}
function sizeSuffix(rowName) {
  const m = rowName.match(/ \((Small|Large|Medium|Regular)\)(?: \+ (?:Extra Cheese|Schezwan))?$/);
  return m ? m[1] : null;
}

const CATEGORY_EMOJI = [
  ['pizza', '🍕'], ['burger', '🍔'], ['sandwich', '🥪'], ['soup', '🥣'],
  ['starter', '🍗'], ['biryani', '🍛'], ['curr', '🍛'], ['fried rice', '🍚'],
  ['noodle', '🍜'], ['quick bite', '🍟'], ['dessert', '🍰'],
  ['milk', '🥤'], ['mocktail', '🍹'],
];
function categoryEmoji(cat) {
  const c = (cat || '').toLowerCase();
  const hit = CATEGORY_EMOJI.find(([kw]) => c.includes(kw));
  return hit ? hit[1] : null;
}
// Add-on for a dish, from the CSV data when the name matches, otherwise
// from the dish's category (covers dishes renamed in the live menu).
function addonFor(cat, name) {
  const meta = META_INDEX[normName(name)];
  if (meta && meta.addons) return meta.addons[0];
  const c = (cat || '').toLowerCase();
  if (c.includes('pizza')) return { label: 'Extra Cheese', price: 30, suffix: ' + Extra Cheese' };
  if (c.includes('burger') || c.includes('sandwich')) return { label: 'Extra Cheese', price: 20, suffix: ' + Extra Cheese' };
  if (c.includes('fried rice') || c.includes('noodle')) return { label: 'Schezwan', price: 30, suffix: ' + Schezwan' };
  return null;
}
function metaFor(cat, name) {
  const meta = META_INDEX[normName(name)] || {};
  const c = (cat || '').toLowerCase();
  return {
    veg: meta.veg !== undefined ? meta.veg : null,
    emoji: categoryEmoji(cat) || meta.emoji || '🍽️',
    sizes: !!(meta.sizes || c.includes('pizza')),
    addon: addonFor(cat, name),
  };
}

let menu = {};
let dishes = {}; // category -> [dish]
let cats = [];
let active = 'All';
let cartCount = parseInt(localStorage.getItem('cartCount') || 0);

const ccountEl = document.getElementById('ccount');
if (ccountEl) ccountEl.textContent = cartCount;

function buildDishes() {
  dishes = {};
  cats = Object.keys(menu);
  cats.forEach(cat => {
    const byName = {};
    const order = [];
    (menu[cat] || []).forEach(row => {
      const base = baseName(row.name);
      if (!byName[base]) {
        byName[base] = { cat, name: base, rows: {}, meta: metaFor(cat, base) };
        order.push(base);
      }
      byName[base].rows[row.name] = row;
    });
    dishes[cat] = order.map(name => {
      const d = byName[name];
      const prices = Object.values(d.rows).map(r => r.price);
      d.minPrice = Math.min(...prices);
      // Size options come from the rows that actually exist, so the sheet
      // shows Regular/Large where the menu says that and Small/Large
      // where it says that.
      // One option per size label: the plain row's price wins over the
      // "+ Extra Cheese" row, which shares the same size label.
      const sizeByLabel = {};
      Object.values(d.rows).forEach(r => {
        const label = sizeSuffix(r.name);
        if (!label) return;
        const rowName = `${d.name} (${label})`;
        if (!sizeByLabel[label] || r.name === rowName) sizeByLabel[label] = { label, price: r.price, row: rowName };
      });
      d.sizes = Object.values(sizeByLabel).sort((a, b) => a.price - b.price);
      d.hasOptions = d.sizes.length > 0 || !!d.meta.addon;
      d.anyInStock = Object.values(d.rows).some(r => r.in_stock !== false);
      return d;
    });
  });
}

async function loadMenu() {
  const area = document.getElementById('items-area');
  try {
    const res = await fetch('/api/menu');
    menu = await res.json();
    buildDishes();
    renderTabs();
    renderItems();
  } catch (err) {
    area.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><p>Could not load the menu right now. Please refresh.</p></div>`;
  }
}

function renderTabs() {
  const allCount = cats.reduce((sum, c) => sum + dishes[c].length, 0);
  let tabsHTML = `<button class="tab ${active === 'All' ? 'active' : ''}" data-action="set-active-cat" data-cat="All">All <span style="font-size:11px;opacity:0.6">(${allCount})</span></button>`;
  tabsHTML += cats.map(c => `
    <button class="tab ${c === active ? 'active' : ''}" data-action="set-active-cat" data-cat="${escapeHTML(c)}">${escapeHTML(c)} <span style="font-size:11px;opacity:0.6">(${dishes[c].length})</span></button>
  `).join('');
  document.getElementById('tabs').innerHTML = tabsHTML;
}
function setActive(c) { active = c; renderTabs(); renderItems(); }

function renderItems() {
  const q = document.getElementById('search').value.toLowerCase().trim();
  const area = document.getElementById('items-area');
  if (q) {
    const results = cats.flatMap(c => dishes[c].filter(d =>
      d.name.toLowerCase().includes(q)));
    if (!results.length) { area.innerHTML = `<div class="empty"><div class="empty-icon">🔍</div><p>No dishes found for "${escapeHTML(q)}"</p></div>`; return; }
    area.innerHTML = `<div class="category-label">Search results (${results.length})</div><div class="items-grid">${results.map(dishHTML).join('')}</div>`;
    return;
  }

  if (active === 'All') {
    let html = '';
    cats.forEach((c, idx) => {
      const items = dishes[c];
      if (!items.length) return;
      html += `<div class="category-label" ${idx > 0 ? 'style="margin-top:40px"' : ''}>${escapeHTML(c)} — ${items.length} dishes</div>`;
      html += `<div class="items-grid">${items.map(dishHTML).join('')}</div>`;
    });
    area.innerHTML = html || `<div class="empty"><div class="empty-icon">🍽️</div><p>The menu is empty right now.</p></div>`;
  } else {
    const items = dishes[active] || [];
    area.innerHTML = `
      <div class="category-label">${escapeHTML(active)} — ${items.length} dishes</div>
      <div class="items-grid">${items.map(dishHTML).join('')}</div>
    `;
  }
}

function dishHTML(d) {
  const emoji = d.meta.emoji || '🍽️';
  const baseRow = Object.values(d.rows)[0];
  const image = typeof baseRow.image === 'string'
    && /^data:image\/(?:png|jpe?g);base64,[A-Za-z0-9+/]+={0,2}$/.test(baseRow.image)
    ? baseRow.image
    : '';
  const media = image
    ? `<div class="item-emoji" style="padding:0;overflow:hidden"><img src="${escapeHTML(image)}" width="300" height="300" loading="lazy" alt="${escapeHTML(d.name)}" style="width:100%;height:100%;object-fit:cover"/></div>`
    : `<div class="item-emoji">${escapeHTML(emoji)}</div>`;
  const priceLabel = d.sizes.length > 0 ? `from ₹${d.minPrice}` : `₹${d.minPrice}`;
  const foot = !d.anyInStock
    ? `<button class="add-btn" disabled style="opacity:.5;cursor:not-allowed">Unavailable</button>`
    : d.hasOptions
      ? `<button class="add-btn" data-action="customise" data-cat="${escapeHTML(d.cat)}" data-name="${escapeHTML(d.name)}">+ Add</button>`
      : `<button class="add-btn" data-action="add-cart" data-id="${baseRow.id}" data-name="${escapeHTML(d.name)}" data-price="${d.minPrice}" data-emoji="${escapeHTML(emoji)}">+ Add</button>`;
  return `<div class="item" style="${d.anyInStock ? '' : 'opacity:.55'}">
    ${media}
    <div class="item-body">
      <div class="item-top">
        <div class="item-name">${escapeHTML(d.name)}</div>
        ${d.hasOptions ? `<div class="item-tag">Customisable</div>` : ''}
      </div>
      <div class="item-foot">
        <div class="price">${priceLabel}</div>
        ${foot}
      </div>
    </div>
  </div>`;
}

// ───────────────────────── customise sheet (Swiggy style) ─────────────────────────
let sheetDish = null;
let sheetSize = 0;      // index into sheetDish.sizes
let sheetAddon = false; // the one add-on for this dish, if any
let sheetQty = 1;

function sheetRowName() {
  if (!sheetDish) return '';
  let name = sheetDish.name;
  if (sheetDish.sizes.length) name += ` (${sheetDish.sizes[sheetSize].label})`;
  if (sheetAddon && sheetDish.meta.addon) name += sheetDish.meta.addon.suffix;
  return name;
}
function sheetRow() {
  return sheetDish ? sheetDish.rows[sheetRowName()] : null;
}
function sheetTotal() {
  const row = sheetRow();
  return row ? row.price * sheetQty : 0;
}

function openSheet(cat, name) {
  sheetDish = (dishes[cat] || []).find(d => d.name === name);
  if (!sheetDish) return;
  sheetSize = 0;
  sheetAddon = false;
  sheetQty = 1;
  renderSheet();
  document.getElementById('sheet-overlay').classList.add('show');
  document.getElementById('custom-sheet').classList.add('show');
  document.body.style.overflow = 'hidden';
}
function closeSheet() {
  document.getElementById('sheet-overlay').classList.remove('show');
  document.getElementById('custom-sheet').classList.remove('show');
  document.body.style.overflow = '';
  sheetDish = null;
}

function showSheetToast(msg) {
  const toastEl = document.getElementById('toast');
  if (!toastEl) return;
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  setTimeout(() => toastEl.classList.remove('show'), 3500);
}

function renderSheet() {
  const d = sheetDish;
  const meta = d.meta;
  const emoji = meta.emoji || '🍽️';
  let sections = '';

  if (d.sizes.length) {
    sections += `<div class="sheet-sec-title">Choose your size</div>
      <div class="sheet-sec-sub">Select any 1</div>
      <div class="sheet-options">${d.sizes.map((s, i) => {
        const row = d.rows[s.row];
        const disabled = !row || row.in_stock === false;
        return `<button type="button" class="sheet-opt ${i === sheetSize ? 'selected' : ''}" data-action="sheet-size" data-idx="${i}" ${disabled ? 'disabled' : ''}>
          <span class="sheet-opt-name">${escapeHTML(s.label)}</span>
          <span class="sheet-opt-price">₹${s.price}</span>
          <span class="sheet-radio"></span>
        </button>`;
      }).join('')}</div>`;
  } else if (meta.sizes) {
    sections += `<div class="sheet-note">Size choices are not on the menu yet. Ask the admin to tap "Load CSV menu" in Admin &gt; Menu.</div>`;
  }

  if (meta.addon) {
    const a = meta.addon;
    let addonRowName = sheetDish.name;
    if (d.sizes.length) addonRowName += ` (${d.sizes[sheetSize].label})`;
    addonRowName += a.suffix;
    const addonRow = sheetDish.rows[addonRowName];
    const addonDisabled = !addonRow || addonRow.in_stock === false;
    if (addonDisabled) sheetAddon = false;
    sections += `<div class="sheet-sec-title">Add-ons</div>
      <div class="sheet-sec-sub">${escapeHTML(a.label)} · +₹${a.price}</div>
      <div class="sheet-options">
        <button type="button" class="sheet-opt ${sheetAddon ? 'selected' : ''}" data-action="sheet-addon" ${addonDisabled ? 'disabled' : ''}>
          <span class="sheet-opt-name">${escapeHTML(a.label)}</span>
          <span class="sheet-opt-price">+ ₹${a.price}</span>
          <span class="sheet-check"></span>
        </button>
      </div>`;
  }

  document.getElementById('custom-sheet').innerHTML = `
    <button type="button" class="sheet-close" data-action="sheet-close" aria-label="Close">✕</button>
    <div class="sheet-head">
      <div class="sheet-thumb">${escapeHTML(emoji)}</div>
      <div>
        <div class="sheet-name">${escapeHTML(d.name)}</div>
        <div class="sheet-sub">${d.hasOptions ? 'Customise it your way' : ''}</div>
      </div>
    </div>
    <div class="sheet-body">${sections}</div>
    <div class="sheet-foot">
      <div class="sheet-qty">
        <button type="button" data-action="sheet-qty" data-delta="-1" aria-label="Decrease quantity">−</button>
        <span>${sheetQty}</span>
        <button type="button" data-action="sheet-qty" data-delta="1" aria-label="Increase quantity">+</button>
      </div>
      <button type="button" class="sheet-add" data-action="sheet-add" ${sheetRow() ? '' : 'disabled style="opacity:.5;cursor:not-allowed"'}>Add Item | ₹${sheetTotal()}</button>
    </div>`;
}

function refreshSheetTotal() {
  const btn = document.querySelector('#custom-sheet .sheet-add');
  if (btn) btn.textContent = `Add Item | ₹${sheetTotal()}`;
  const qty = document.querySelector('#custom-sheet .sheet-qty span');
  if (qty) qty.textContent = sheetQty;
}

function addCart(el, id, name, price, emoji, qty) {
  qty = qty || 1;
  let cart = JSON.parse(localStorage.getItem('surenPastriesCart')) || [];
  let existing = cart.find(i => i.id === id);
  if (existing) { existing.qty += qty; }
  else { cart.push({ id: id, name: name, price: price, qty: qty, emoji: emoji }); }
  localStorage.setItem('surenPastriesCart', JSON.stringify(cart));
  cartCount = cart.reduce((s, i) => s + i.qty, 0);
  localStorage.setItem('cartCount', cartCount);
  const cc = document.getElementById('ccount');
  if (cc) cc.textContent = cartCount;

  const t = document.getElementById('toast');
  if (t) {
    t.textContent = 'Added ' + name + ' · ₹' + price;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
  }

  if (el) {
    const btn = el;
    const oldText = btn.textContent;
    btn.textContent = '✓ Added';
    btn.style.background = '#4CAF50';
    btn.style.borderColor = '#4CAF50';
    btn.style.color = '#fff';
    setTimeout(() => {
      btn.textContent = oldText;
      btn.style.background = '';
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 2000);
  }
  if (typeof updateFC === 'function') updateFC();
}

function updateFC() {
  let c = parseInt(localStorage.getItem('cartCount') || 0);
  const fc = document.getElementById('nav-cart'), fb = document.getElementById('ccount');
  if (fc && fb) { if (c > 0) { fc.style.display = 'flex'; fb.textContent = c; } else { fc.style.display = 'none'; } }
}

// ───────────────────────── event delegation ─────────────────────────
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  if (action === 'set-active-cat') setActive(el.dataset.cat);
  if (action === 'add-cart') {
    addCart(el, parseInt(el.dataset.id, 10), el.dataset.name, parseFloat(el.dataset.price), el.dataset.emoji);
  }
  if (action === 'customise') openSheet(el.dataset.cat, el.dataset.name);
  if (action === 'sheet-close') closeSheet();
  if (action === 'sheet-size') {
    sheetSize = parseInt(el.dataset.idx, 10);
    renderSheet();
  }
  if (action === 'sheet-addon') {
    sheetAddon = !sheetAddon;
    renderSheet();
  }
  if (action === 'sheet-qty') {
    sheetQty = Math.max(1, Math.min(20, sheetQty + parseInt(el.dataset.delta, 10)));
    refreshSheetTotal();
  }
  if (action === 'sheet-add') {
    const row = sheetRow();
    if (!row) {
      showSheetToast('That choice is not on the menu yet. Ask the admin to tap "Load CSV menu" in Admin > Menu.');
      return;
    }
    addCart(null, row.id, row.name, row.price, row.emoji, sheetQty);
    closeSheet();
  }
});
document.addEventListener('click', (e) => {
  if (e.target.id === 'sheet-overlay') closeSheet();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && sheetDish) closeSheet();
});
document.addEventListener('input', (e) => {
  if (e.target.id === 'search') renderItems();
});

updateFC();
loadMenu();
