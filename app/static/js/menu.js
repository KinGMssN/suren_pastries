function encodeObj(obj) {
  return btoa(encodeURIComponent(JSON.stringify(obj)));
}
function decodeObj(str) {
  return JSON.parse(decodeURIComponent(atob(str)));
}
function encodeAttr(str) {
  return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

let menu = {};
let cats = [];
let active = 'All';
let cartCount = parseInt(localStorage.getItem('cartCount') || 0);

const ccountEl = document.getElementById('ccount');
if (ccountEl) ccountEl.textContent = cartCount;

async function loadMenu() {
  const area = document.getElementById('items-area');
  try {
    const res = await fetch('/api/menu');
    menu = await res.json();
    cats = Object.keys(menu);
    renderTabs();
    renderItems();
  } catch (err) {
    area.innerHTML = `<div class="empty"><div class="empty-icon">⚠️</div><p>Could not load the menu right now. Please refresh.</p></div>`;
  }
}

function renderTabs() {
  let allCount = cats.reduce((sum, c) => sum + menu[c].length, 0);
  let tabsHTML = `<button class="tab ${active === 'All' ? 'active' : ''}" data-action="set-active-cat" data-cat="All">All <span style="font-size:11px;opacity:0.6">(${allCount})</span></button>`;
  tabsHTML += cats.map(c => `
    <button class="tab ${c === active ? 'active' : ''}" data-action="set-active-cat" data-cat="${encodeAttr(c)}">${c} <span style="font-size:11px;opacity:0.6">(${menu[c].length})</span></button>
  `).join('');
  document.getElementById('tabs').innerHTML = tabsHTML;
}
function setActive(c) { active = c; renderTabs(); renderItems(); }

function renderItems() {
  const q = document.getElementById('search').value.toLowerCase().trim();
  const area = document.getElementById('items-area');
  if (q) {
    const results = cats.flatMap(c => menu[c].filter(i => i.name.toLowerCase().includes(q) || (i.desc || '').toLowerCase().includes(q)));
    if (!results.length) { area.innerHTML = `<div class="empty"><div class="empty-icon">🔍</div><p>No dishes found for "${q}"</p></div>`; return; }
    area.innerHTML = `<div class="category-label">Search results (${results.length})</div><div class="items-grid">${results.map(itemHTML).join('')}</div>`;
    return;
  }

  if (active === 'All') {
    let html = '';
    cats.forEach((c, idx) => {
      const items = menu[c];
      if (!items.length) return;
      html += `<div class="category-label" ${idx > 0 ? 'style="margin-top:40px"' : ''}>${c} — ${items.length} dishes</div>`;
      html += `<div class="items-grid">${items.map(itemHTML).join('')}</div>`;
    });
    area.innerHTML = html || `<div class="empty"><div class="empty-icon">🍽️</div><p>The menu is empty right now.</p></div>`;
  } else {
    const items = menu[active] || [];
    area.innerHTML = `
      <div class="category-label">${active} — ${items.length} dishes</div>
      <div class="items-grid">${items.map(itemHTML).join('')}</div>
    `;
  }
}
function itemHTML(i) {
  const media = i.image
    ? `<div class="item-emoji" style="padding:0;overflow:hidden"><img src="${i.image}" alt="${i.name}" style="width:100%;height:100%;object-fit:cover"/></div>`
    : `<div class="item-emoji">${i.emoji}</div>`;
  const outOfStock = i.in_stock === false;
  return `<div class="item" style="${outOfStock ? 'opacity:.55' : ''}">
    ${media}
    <div class="item-body">
      <div class="item-top">
        <div class="item-name">${i.name}</div>
        ${outOfStock ? `<div class="item-tag" style="background:#7A7570">Out of stock</div>` : (i.tag ? `<div class="item-tag">${i.tag}</div>` : '')}
      </div>
      <div class="item-desc">${i.desc || ''}</div>
      <div class="item-foot">
        <div class="price">₹${i.price}</div>
        ${outOfStock
          ? `<button class="add-btn" disabled style="opacity:.5;cursor:not-allowed">Unavailable</button>`
          : `<button class="add-btn" data-action="add-cart" data-id="${i.id}" data-name="${encodeAttr(i.name)}" data-price="${i.price}" data-emoji="${encodeAttr(i.emoji)}">+ Add</button>`}
      </div>
    </div>
  </div>`;
}

function addCart(el, id, name, price, emoji) {
  let cart = JSON.parse(localStorage.getItem('surenPastriesCart')) || [];
  let existing = cart.find(i => i.id === id);
  if (existing) { existing.qty++; }
  else { cart.push({ id: id, name: name, price: price, qty: 1, emoji: emoji }); }
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
  if (el.dataset.action === 'set-active-cat') setActive(el.dataset.cat);
  if (el.dataset.action === 'add-cart') {
    addCart(el, parseInt(el.dataset.id, 10), el.dataset.name, parseFloat(el.dataset.price), el.dataset.emoji);
  }
});
document.addEventListener('input', (e) => {
  if (e.target.id === 'search') renderItems();
});

updateFC();
loadMenu();
