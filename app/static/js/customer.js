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

function updateAccountNav() {
  const link = document.getElementById('nav-account');
  if (!link) return;
  const customer = getCustomer();
  link.classList.add('nav-avatar');
  if (customer) {
    link.classList.remove('guest');
    link.textContent = customer.name.trim().charAt(0).toUpperCase() || '👤';
    link.title = customer.name;
    link.href = '/account';
  } else {
    link.classList.add('guest');
    link.textContent = '👤';
    link.title = 'Log in';
    link.href = '/login';
  }
}

// ───────────────────────── login page ─────────────────────────
async function customerLogin(event) {
  if (event) event.preventDefault();
  const phone = document.getElementById('login-phone').value.trim();
  const errBox = document.getElementById('login-error');
  if (errBox) errBox.style.display = 'none';

  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/request-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, mode: 'login' }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (data.needs_name) {
        window.location.href = '/signup?phone=' + encodeURIComponent(phone);
        return;
      }
      if (errBox) { errBox.textContent = data.error || 'Something went wrong.'; errBox.style.display = 'block'; }
      return;
    }
    if (data.debug_code) document.getElementById('login-code').value = data.debug_code;
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('verify-form').style.display = 'block';
  } catch (err) {
    if (errBox) { errBox.textContent = 'Could not reach the server. Please try again.'; errBox.style.display = 'block'; }
  }
}

async function customerSignup(event) {
  event.preventDefault();
  const phone = document.getElementById('signup-phone').value.trim();
  const name = document.getElementById('signup-name').value.trim();
  const errBox = document.getElementById('signup-error');
  if (errBox) errBox.style.display = 'none';
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/request-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, name, mode: 'signup' }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Could not create your account.');
    if (data.debug_code) document.getElementById('signup-code').value = data.debug_code;
    document.getElementById('signup-form').style.display = 'none';
    document.getElementById('signup-verify-form').style.display = 'block';
  } catch (err) {
    if (errBox) { errBox.textContent = err.message; errBox.style.display = 'block'; }
  }
}

async function verifySignupOtp(event) {
  event.preventDefault();
  const errBox = document.getElementById('signup-error');
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phone: document.getElementById('signup-phone').value.trim(),
        code: document.getElementById('signup-code').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Invalid verification code.');
    setCustomer(data.customer);
    window.location.href = '/account';
  } catch (err) {
    if (errBox) { errBox.textContent = err.message; errBox.style.display = 'block'; }
  }
}

async function verifyCustomerOtp(event) {
  event.preventDefault();
  const errBox = document.getElementById('login-error');
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phone: document.getElementById('login-phone').value.trim(),
        code: document.getElementById('login-code').value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Invalid verification code.');
    setCustomer(data.customer);
    window.location.href = '/account';
  } catch (err) {
    if (errBox) { errBox.textContent = err.message; errBox.style.display = 'block'; }
  }
}

function customerLogout() {
  fetch(CUSTOMER_API_BASE + '/api/customer/logout', { method: 'POST' });
  clearCustomer();
  window.location.href = '/home';
}

async function deleteCustomerAccount() {
  if (!confirm('Delete your account and saved addresses? Your completed orders will be retained without your personal details.')) return;
  try {
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/account', { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Could not delete your account.');
    clearCustomer();
    window.location.href = '/home';
  } catch (err) {
    alert(err.message);
  }
}

// ───────────────────────── account page ─────────────────────────
async function loadAccountPage() {
  const customer = getCustomer();
  if (!customer) { window.location.href = '/login'; return; }

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
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/addresses');
    const addresses = await res.json();
    if (!addresses.length) {
      list.innerHTML = '<p style="color:var(--muted);font-size:13px">No saved addresses yet. Add one below.</p>';
      return;
    }
    list.innerHTML = addresses.map(a => `
      <div class="addr-card" data-id="${a.id}">
        <div class="addr-top">
          <strong>${a.label}</strong>
          ${a.is_default ? '<span class="addr-default">Default</span>' : `<button class="addr-link-btn" data-action="set-default-address" data-id="${a.id}">Set default</button>`}
        </div>
        <div class="addr-text">${a.address_line}${a.city ? ', ' + a.city : ''}${a.pincode ? ' - ' + a.pincode : ''}</div>
        <button class="addr-link-btn" data-action="delete-address" data-id="${a.id}">Delete</button>
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
    const res = await fetch(CUSTOMER_API_BASE + '/api/customer/orders');
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

// ───────────────────────── event delegation ─────────────────────────
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const id = el.dataset.id ? parseInt(el.dataset.id, 10) : null;
  switch (el.dataset.action) {
    case 'logout': customerLogout(); break;
    case 'delete-account': deleteCustomerAccount(); break;
    case 'set-default-address': setDefaultAddress(id); break;
    case 'delete-address': deleteAddress(id); break;
  }
});

document.addEventListener('submit', (e) => {
  if (e.target.id === 'login-form') customerLogin(e);
  if (e.target.id === 'signup-form') customerSignup(e);
  if (e.target.id === 'verify-form') verifyCustomerOtp(e);
  if (e.target.id === 'signup-verify-form') verifySignupOtp(e);
  if (e.target.id === 'add-address-form') addAddress(e);
});

document.addEventListener('DOMContentLoaded', () => {
  updateAccountNav();
  const signupPhone = new URLSearchParams(window.location.search).get('phone');
  if (signupPhone && document.getElementById('signup-phone')) document.getElementById('signup-phone').value = signupPhone;
  if (document.getElementById('address-list')) loadAccountPage();
});
