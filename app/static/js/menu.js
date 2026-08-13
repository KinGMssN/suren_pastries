// Menu data now comes from the database via /api/menu instead of being
// hardcoded, so whatever the admin edits in Admin > Menu shows up here.
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
  let tabsHTML = `<button class="tab ${active === 'All' ? 'active' : ''}" onclick="setActive('All')">All <span style="font-size:11px;opacity:0.6">(${allCount})</span></button>`;
  tabsHTML += cats.map(c => `
    <button class="tab ${c === active ? 'active' : ''}" onclick="setActive('${c}')">${c} <span style="font-size:11px;opacity:0.6">(${menu[c].length})</span></button>
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
  return `<div class="item">
    <div class="item-emoji">${i.emoji}</div>
    <div class="item-body">
      <div class="item-top">
        <div class="item-name">${i.name}</div>
        ${i.tag ? `<div class="item-tag">${i.tag}</div>` : ''}
      </div>
      <div class="item-desc">${i.desc || ''}</div>
      <div class="item-foot">
        <div class="price">₹${i.price}</div>
        <button class="add-btn" onclick='addCart(event, ${i.id}, ${JSON.stringify(i.name)}, ${i.price}, ${JSON.stringify(i.emoji)})'>+ Add</button>
      </div>
    </div>
  </div>`;
}

function addCart(event, id, name, price, emoji) {
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

  if (event && event.currentTarget) {
    const btn = event.currentTarget;
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

updateFC();
loadMenu();
