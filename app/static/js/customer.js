// Works in both contexts, same as menu.js/cart.js:
// - Server-rendered pages: window.API_BASE is unset, falls back to '' (relative paths)
// - Static frontend (GitHub Pages): config.js sets window.API_BASE to the Render URL
const CUSTOMER_API_BASE = window.API_BASE || '';

function getCustomer() {
  const raw = localStorage.getItem('surenCustomer');
  return raw ? JSON.parse(raw) : null;
}
function setCustomer(customer) {
  localStorage.setItem('surenCustomer', JSON.stringify(customer));
}
function clearCustomer() {
  localStorage.removeItem('surenCustomer');
}
function isLoggedIn() {
  return !!getCustomer();
}

// Updates any "Login" / "Hi, <name>" nav link found on the page.
function updateAccountNav() {
  const link = document.getElementById('nav-account');
  if (!link) return;
  const customer = getCustomer();
  if (customer) {
    link.textContent = 'Hi, ' + customer.name.split(' ')[0];
    link.href = window.ACCOUNT_URL || 'account.html';
  } else {
    link.textContent = 'Login';
    link.href = window.LOGIN_URL || 'login.html';
  }
}

// ───────────────────────── login page ─────────────────────────
async function customerLogin(event) {
  if (event) event.preventDefault();
  const phone = document.getElementById('login-phone').value.trim();
  const name = document.getElementById('login-name').value.trim();
  const errBox = document.getElementById('login-error');
  if (errBox) errBox.style.display = 'none';

  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, name }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (errBox) { errBox.textContent = data.error || 'Something went wrong.'; errBox.style.display = 'block'; }
      return;
    }
    setCustomer(data.customer);
    window.location.href = window.AFTER_LOGIN_URL || 'account.html';
  } catch (err) {
    if (errBox) { errBox.textContent = 'Could not reach the server. Please try again.'; errBox.style.display = 'block'; }
  }
}

function customerLogout() {
  clearCustomer();
  window.location.href = window.HOME_URL || 'landing.html';
}

// ───────────────────────── account page ─────────────────────────
async function loadAccountPage() {
  const customer = getCustomer();
  if (!customer) { window.location.href = window.LOGIN_URL || 'login.html'; return; }

  const nameEl = document.getElementById('acct-name');
  const phoneEl = document.getElementById('acct-phone');
  if (nameEl) nameEl.textContent = customer.name;
  if (phoneEl) phoneEl.textContent = customer.phone;

  await Promise.all([loadAddresses(), loadOrderHistory()]);
}

async function loadAddresses() {
  const customer = getCustomer();
  const list = document.getElementById('address-list');
  if (!list || !customer) return;
  list.innerHTML = '<p style="color:var(--muted);font-size:13px">Loading…</p>';
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/addresses?phone=' + encodeURIComponent(customer.phone));
    const addresses = await res.json();
    if (!addresses.length) {
      list.innerHTML = '<p style="color:var(--muted);font-size:13px">No saved addresses yet. Add one below.</p>';
      return;
    }
    list.innerHTML = addresses.map(a => `
      <div class="addr-card" data-id="${a.id}">
        <div class="addr-top">
          <strong>${a.label}</strong>
          ${a.is_default ? '<span class="addr-default">Default</span>' : `<button class="addr-link-btn" onclick="setDefaultAddress(${a.id})">Set default</button>`}
        </div>
        <div class="addr-text">${a.address_line}${a.city ? ', ' + a.city : ''}${a.pincode ? ' - ' + a.pincode : ''}</div>
        <button class="addr-link-btn" onclick="deleteAddress(${a.id})">Delete</button>
      </div>
    `).join('');
  } catch (err) {
    list.innerHTML = '<p style="color:var(--muted);font-size:13px">Could not load addresses.</p>';
  }
}

async function addAddress(event) {
  event.preventDefault();
  const customer = getCustomer();
  if (!customer) return;
  const payload = {
    phone: customer.phone,
    label: document.getElementById('addr-label').value.trim() || 'Home',
    address_line: document.getElementById('addr-line').value.trim(),
    city: document.getElementById('addr-city').value.trim(),
    pincode: document.getElementById('addr-pincode').value.trim(),
    is_default: document.getElementById('addr-default').checked,
  };
  if (!payload.address_line) { alert('Address is required'); return; }
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/addresses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) { alert(data.error || 'Could not save address'); return; }
    document.getElementById('addr-line').value = '';
    document.getElementById('addr-city').value = '';
    document.getElementById('addr-pincode').value = '';
    document.getElementById('addr-default').checked = false;
    loadAddresses();
  } catch (err) { alert('Could not reach the server.'); }
}

async function deleteAddress(id) {
  if (!confirm('Delete this address?')) return;
  try {
    await fetch(CUSTOMER_API_BASE + '/api/customer/addresses/' + id, { method: 'DELETE' });
    loadAddresses();
  } catch (err) { alert('Could not delete address.'); }
}

async function setDefaultAddress(id) {
  try {
    await fetch(CUSTOMER_API_BASE + '/api/customer/addresses/' + id, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_default: true }),
    });
    loadAddresses();
  } catch (err) { alert('Could not update address.'); }
}

async function loadOrderHistory() {
  const customer = getCustomer();
  const list = document.getElementById('order-history-list');
  if (!list || !customer) return;
  list.innerHTML = '<p style="color:var(--muted);font-size:13px">Loading…</p>';
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/orders?phone=' + encodeURIComponent(customer.phone));
    const orders = await res.json();
    if (!orders.length) {
      list.innerHTML = '<p style="color:var(--muted);font-size:13px">No past orders yet.</p>';
      return;
    }
    list.innerHTML = orders.map(o => `
      <div class="order-card">
        <div class="order-card-top">
          <strong>${o.order_number}</strong>
          <span class="order-status-pill">${o.status}</span>
        </div>
        <div class="order-items-line">${o.items.map(i => `${i.qty}× ${i.name}`).join(', ')}</div>
        <div class="order-card-bottom"><span>${o.created_at}</span><strong>₹${o.total}</strong></div>
      </div>
    `).join('');
  } catch (err) {
    list.innerHTML = '<p style="color:var(--muted);font-size:13px">Could not load past orders.</p>';
  }
}

document.addEventListener('DOMContentLoaded', updateAccountNav);
