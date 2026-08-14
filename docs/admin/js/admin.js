// ───────────────────────── tab switching ─────────────────────────
function setTab(name, el) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelectorAll('.sb-link').forEach(l => l.classList.remove('active'));
  if (el) el.classList.add('active');

  if (name === 'dashboard') loadDashboard();
  if (name === 'orders') loadOrders();
  if (name === 'menu') loadMenuEditor();
  if (name === 'offers') loadOffers();
  if (name === 'content') loadContent();
}

function toast(msg) {
  const t = document.getElementById('toast-el');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

async function api(path, opts) {
  const res = await fetch(window.API_BASE + '/api/admin' + path, {
    credentials: 'include',   // send/receive the cross-site session cookie
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (res.status === 401) {
    window.location.href = 'login.html';
    throw new Error('Session expired');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

const STATUS_LABEL = { pending: 'Pending', preparing: 'Preparing', ready: 'Ready', delivered: 'Delivered' };
const STATUS_CLASS = { pending: 's-pending', preparing: 's-preparing', ready: 's-ready', delivered: 's-delivered' };

// ───────────────────────── dashboard ─────────────────────────
async function loadDashboard() {
  try {
    const s = await api('/stats');
    document.getElementById('stat-revenue').textContent = '₹' + s.revenue;
    document.getElementById('stat-revenue-sub').textContent = s.total_orders + ' orders total';
    document.getElementById('stat-orders').textContent = s.total_orders;
    document.getElementById('stat-orders-sub').textContent = s.pending_orders + ' pending';
    document.getElementById('stat-pending').textContent = s.pending_orders;
    document.getElementById('stat-menu').textContent = s.menu_count;

    const body = document.getElementById('recent-orders-body');
    if (!s.recent_orders.length) {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">No recent orders found</td></tr>`;
    } else {
      body.innerHTML = s.recent_orders.map(o => `
        <tr>
          <td>${o.order_number}</td>
          <td>${o.customer_name}</td>
          <td>${o.item_count}</td>
          <td>₹${o.total}</td>
          <td><span class="tstatus ${STATUS_CLASS[o.status]}">${STATUS_LABEL[o.status]}</span></td>
          <td>${o.created_at}</td>
        </tr>
      `).join('');
    }
  } catch (err) { toast(err.message); }
}

// ───────────────────────── orders ─────────────────────────
async function loadOrders() {
  const status = document.getElementById('order-status-filter').value;
  const body = document.getElementById('orders-body');
  body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">Loading…</td></tr>`;
  try {
    const orders = await api('/orders' + (status ? `?status=${status}` : ''));
    if (!orders.length) {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">No orders found</td></tr>`;
      return;
    }
    body.innerHTML = orders.map(o => `
      <tr>
        <td>${o.order_number}</td>
        <td>${o.customer_name}</td>
        <td>${o.items.map(i => `${i.qty}× ${i.name}`).join(', ')}</td>
        <td>₹${o.total}</td>
        <td style="text-transform:capitalize">${o.channel}</td>
        <td>
          <select class="form-input" style="width:auto;padding:6px 10px;font-size:12px" onchange="updateOrderStatus(${o.id}, this.value)">
            ${Object.keys(STATUS_LABEL).map(s => `<option value="${s}" ${s === o.status ? 'selected' : ''}>${STATUS_LABEL[s]}</option>`).join('')}
          </select>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:24px">Could not load orders</td></tr>`;
  }
}

async function updateOrderStatus(id, status) {
  try {
    await api(`/orders/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) });
    toast('Order status updated');
    loadOrders();
  } catch (err) { toast(err.message); }
}

// ───────────────────────── menu editor ─────────────────────────
let editingItemId = null;
let knownCategories = new Set();

async function loadMenuEditor() {
  const grid = document.getElementById('menu-editor-grid');
  grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Loading…</div>`;
  try {
    const items = await api('/menu');
    knownCategories = new Set(items.map(i => i.category).filter(Boolean));
    document.getElementById('category-list').innerHTML =
      [...knownCategories].map(c => `<option value="${c}">`).join('');

    if (!items.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted);border:1px dashed var(--border);border-radius:12px">No menu items added yet. Click "+ Add item" to get started.</div>`;
      return;
    }
    grid.innerHTML = items.map(i => `
      <div class="me-card">
        <div class="me-emoji">${i.emoji}</div>
        <div class="me-info">
          <div class="me-name">${i.name} ${i.is_available ? '' : '<span style="color:var(--muted);font-weight:400">(hidden)</span>'}</div>
          <div class="me-cat">${i.category || 'Uncategorized'}${i.tag ? ' · ' + i.tag : ''}</div>
          <div class="me-price">₹${i.price}</div>
        </div>
        <div class="me-actions">
          <button class="me-btn" onclick='openEditModal(${JSON.stringify(i)})'>Edit</button>
          <button class="me-btn" onclick="toggleAvailability(${i.id})">${i.is_available ? 'Hide' : 'Show'}</button>
          <button class="me-btn me-del" onclick="deleteMenuItem(${i.id})">Delete</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Could not load the menu</div>`;
  }
}

function showModal() {
  editingItemId = null;
  document.getElementById('menu-modal-title').textContent = 'Add menu item';
  ['id', 'name', 'price', 'description', 'category', 'tag', 'emoji'].forEach(f => document.getElementById('mi-' + f).value = '');
  document.getElementById('modal').classList.add('show');
}
function openEditModal(item) {
  editingItemId = item.id;
  document.getElementById('menu-modal-title').textContent = 'Edit menu item';
  document.getElementById('mi-id').value = item.id;
  document.getElementById('mi-name').value = item.name;
  document.getElementById('mi-price').value = item.price;
  document.getElementById('mi-description').value = item.desc || '';
  document.getElementById('mi-category').value = item.category || '';
  document.getElementById('mi-tag').value = item.tag || '';
  document.getElementById('mi-emoji').value = item.emoji || '';
  document.getElementById('modal').classList.add('show');
}
function hideModal() { document.getElementById('modal').classList.remove('show'); }

async function submitMenuItem() {
  const payload = {
    name: document.getElementById('mi-name').value.trim(),
    price: parseInt(document.getElementById('mi-price').value || '0', 10),
    description: document.getElementById('mi-description').value.trim(),
    category: document.getElementById('mi-category').value.trim(),
    tag: document.getElementById('mi-tag').value.trim(),
    emoji: document.getElementById('mi-emoji').value.trim() || '🍽️',
  };
  if (!payload.name || !payload.category || !payload.price) {
    toast('Name, category and price are required'); return;
  }
  try {
    if (editingItemId) {
      await api(`/menu/${editingItemId}`, { method: 'PUT', body: JSON.stringify(payload) });
      toast('Item updated');
    } else {
      await api('/menu', { method: 'POST', body: JSON.stringify(payload) });
      toast('Item added to menu!');
    }
    hideModal();
    loadMenuEditor();
  } catch (err) { toast(err.message); }
}

async function toggleAvailability(id) {
  try { await api(`/menu/${id}/toggle`, { method: 'POST' }); loadMenuEditor(); }
  catch (err) { toast(err.message); }
}
async function deleteMenuItem(id) {
  if (!confirm('Remove this item from the menu?')) return;
  try { await api(`/menu/${id}`, { method: 'DELETE' }); toast('Item removed'); loadMenuEditor(); }
  catch (err) { toast(err.message); }
}

document.getElementById('modal').addEventListener('click', e => { if (e.target === document.getElementById('modal')) hideModal(); });

// ───────────────────────── offers / coupons ─────────────────────────
async function loadOffers() {
  const body = document.getElementById('offers-body');
  body.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">Loading…</td></tr>`;
  try {
    const coupons = await api('/coupons');
    if (!coupons.length) {
      body.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">No offers available</td></tr>`;
      return;
    }
    body.innerHTML = coupons.map(c => `
      <tr>
        <td>${c.code}</td>
        <td>${c.description || '—'}</td>
        <td>${c.discount_type === 'percent' ? c.value + '%' : '₹' + c.value}</td>
        <td>${c.uses}${c.max_uses ? ' / ' + c.max_uses : ''}</td>
        <td>${c.expires_at || 'No expiry'}</td>
        <td><span class="tstatus ${c.is_valid ? 's-ready' : 's-pending'}">${c.is_valid ? 'Active' : 'Inactive'}</span></td>
        <td>
          <button class="me-btn" onclick="toggleCoupon(${c.id})">${c.active ? 'Disable' : 'Enable'}</button>
          <button class="me-btn me-del" onclick="deleteCoupon(${c.id})">Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    body.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">Could not load offers</td></tr>`;
  }
}
function showCouponModal() {
  ['code', 'value', 'expiry', 'description'].forEach(f => document.getElementById('co-' + f).value = '');
  document.getElementById('co-type').value = 'percent';
  document.getElementById('couponModal').classList.add('show');
}
function hideCouponModal() { document.getElementById('couponModal').classList.remove('show'); }
async function submitCoupon() {
  const payload = {
    code: document.getElementById('co-code').value.trim(),
    discount_type: document.getElementById('co-type').value,
    value: parseInt(document.getElementById('co-value').value || '0', 10),
    expires_at: document.getElementById('co-expiry').value || null,
    description: document.getElementById('co-description').value.trim(),
  };
  if (!payload.code || !payload.value) { toast('Code and value are required'); return; }
  try {
    await api('/coupons', { method: 'POST', body: JSON.stringify(payload) });
    toast('Offer created!');
    hideCouponModal();
    loadOffers();
  } catch (err) { toast(err.message); }
}
async function toggleCoupon(id) {
  try { await api(`/coupons/${id}/toggle`, { method: 'POST' }); loadOffers(); }
  catch (err) { toast(err.message); }
}
async function deleteCoupon(id) {
  if (!confirm('Delete this offer?')) return;
  try { await api(`/coupons/${id}`, { method: 'DELETE' }); toast('Offer deleted'); loadOffers(); }
  catch (err) { toast(err.message); }
}
document.getElementById('couponModal').addEventListener('click', e => { if (e.target === document.getElementById('couponModal')) hideCouponModal(); });

// ───────────────────────── site content ─────────────────────────
const CONTENT_FIELDS = [
  'phone_display', 'email', 'address_short', 'address_full',
  'hero_title_line1', 'hero_title_line2', 'hero_title_em', 'hero_sub',
  'stat_years', 'stat_dishes', 'stat_guests',
];
async function loadContent() {
  try {
    const data = await api('/content');
    CONTENT_FIELDS.forEach(f => {
      const el = document.getElementById('c-' + f);
      if (el && data[f] !== undefined) el.value = data[f];
    });
  } catch (err) { toast(err.message); }
}
async function saveContent() {
  const payload = {};
  CONTENT_FIELDS.forEach(f => {
    const el = document.getElementById('c-' + f);
    if (el) payload[f] = el.value;
  });
  try {
    await api('/content', { method: 'POST', body: JSON.stringify(payload) });
    toast('Changes saved!');
  } catch (err) { toast(err.message); }
}

// ───────────────────────── boot ─────────────────────────
loadDashboard();
