let cart = JSON.parse(localStorage.getItem('surenPastriesCart')) || [];
let discountAmt = 0;
let appliedCoupon = null;
let addresses = [];
let selectedAddressId = null;

function save() {
  localStorage.setItem('surenPastriesCart', JSON.stringify(cart));
  localStorage.setItem('cartCount', cart.reduce((s, i) => s + i.qty, 0));
}

async function render() {
  const card = document.getElementById('items-card');
  const sum = document.getElementById('summary-card');
  const count = cart.reduce((s, i) => s + i.qty, 0);
  document.getElementById('item-count').textContent = count ? `${count} item${count > 1 ? 's' : ''} in your cart` : 'Your cart is empty';

  if (!cart.length) {
    card.innerHTML = `<div class="empty"><div class="empty-big" aria-hidden="true">🛒</div><h3>Your cart is empty</h3><p>Add some items from our menu</p><a class="btn-p" href="/menu">Browse menu</a></div>`;
    sum.style.display = 'none';
    return;
  }
  sum.style.display = 'block';
  card.innerHTML = `
    <div class="items-card-head"><h3>Items (${count})</h3><button class="clear-btn" type="button" data-action="clear-cart">Clear all items</button></div>
    ${cart.map(i => `
      <div class="cart-item">
        <div class="ci-emoji">${i.emoji}</div>
        <div class="ci-info">
          <div class="ci-name">${i.name}</div>
          <div class="ci-note">₹${i.price} each</div>
        </div>
        <div class="ci-right">
          <div class="ci-price">₹${i.price * i.qty}</div>
          <div class="qty-ctrl">
            <button class="qb" aria-label="Decrease quantity of ${i.name}" data-action="change-qty" data-id="${i.id}" data-delta="-1">−</button>
            <div class="qn">${i.qty}</div>
            <button class="qb" aria-label="Increase quantity of ${i.name}" data-action="change-qty" data-id="${i.id}" data-delta="1">+</button>
          </div>
        </div>
        <button class="del-btn" aria-label="Remove ${i.name} from cart" data-action="remove-item" data-id="${i.id}">Remove</button>
      </div>
    `).join('')}
  `;
  updateSummary();
  await renderCheckoutArea();
}

function updateSummary() {
  const sub = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const delivery = sub >= 499 ? 0 : 40;
  const tax = Math.floor(sub * 0.05 + 0.5);
  const total = Math.max(sub + delivery + tax - discountAmt, 0);
  document.getElementById('subtotal').textContent = '₹' + sub;
  document.getElementById('delivery').textContent = delivery === 0 ? 'FREE' : '₹' + delivery;
  document.getElementById('tax').textContent = '₹' + tax;
  document.getElementById('total').textContent = '₹' + total;
  if (discountAmt) {
    document.getElementById('discount-row').style.display = 'flex';
    document.getElementById('discount-val').textContent = '−₹' + discountAmt;
  } else {
    document.getElementById('discount-row').style.display = 'none';
  }
}

async function renderCheckoutArea() {
  const area = document.getElementById('checkout-area');
  if (!area) return;
  const customer = typeof getCustomer === 'function' ? getCustomer() : null;

  if (!customer) {
    area.innerHTML = `
      <div class="login-prompt">
        <p>Log in to save your address and place an order.</p>
        <a class="acct-btn-primary" style="display:block;text-align:center;text-decoration:none" href="/login">Log in to checkout</a>
      </div>
    `;
    return;
  }

  try {
    const activeResponse = await customerFetch('/api/customer/active-order');
    const activeData = await activeResponse.json();
    if (!activeResponse.ok || !activeData.ok) {
      throw new Error(activeData.error || 'Could not check your current orders.');
    }
    if (activeData.active_order) {
      const notice = document.createElement('div');
      notice.className = 'login-prompt';
      const message = document.createElement('p');
      message.textContent =
        `You already have an active order (${activeData.active_order.order_number}). ` +
        'You can place another order after it is delivered or rejected.';
      const link = document.createElement('a');
      link.className = 'acct-btn-primary';
      link.style.cssText = 'display:block;text-align:center;text-decoration:none';
      link.href = '/track/' + encodeURIComponent(activeData.active_order.order_number);
      link.textContent = 'Track current order';
      notice.append(message, link);
      area.replaceChildren(notice);
      return;
    }
  } catch (err) {
    const notice = document.createElement('div');
    notice.className = 'login-prompt';
    notice.textContent = err.message || 'Could not check your current orders. Please try again.';
    area.replaceChildren(notice);
    return;
  }

  try {
    const res = await customerFetch('/api/customer/addresses');
    addresses = await res.json();
  } catch (err) {
    addresses = [];
  }

  if (!addresses.length) {
    area.innerHTML = `
      <div class="login-prompt">
        <p>Add a delivery address to your account before checking out.</p>
        <a class="acct-btn-primary" style="display:block;text-align:center;text-decoration:none" href="/account">Add an address</a>
      </div>
    `;
    return;
  }

  if (!selectedAddressId) {
    const def = addresses.find(a => a.is_default) || addresses[0];
    selectedAddressId = def.id;
  }

  area.innerHTML = `
    <div class="addr-picker">
      <label class="acct-label" for="address-select">Deliver to</label>
      <select class="acct-input" id="address-select" aria-label="Delivery address" data-action="select-address">
        ${addresses.map(a => `<option value="${a.id}" ${a.id === selectedAddressId ? 'selected' : ''}>${a.label} — ${a.address_line}${a.city ? ', ' + a.city : ''}</option>`).join('')}
      </select>
    </div>
    <div class="checkout-stack">
      <button class="co-btn co-online" data-action="checkout" data-method="online">💳 Pay online</button>
      <button class="co-btn co-cod" data-action="checkout" data-method="cod">💵 Place cash-on-delivery order</button>
    </div>
  `;
}

function change(id, d) {
  const i = cart.find(x => x.id === id);
  if (!i) return;
  i.qty += d;
  if (i.qty <= 0) cart = cart.filter(x => x.id !== id);
  save(); render();
}
function remove(id) { cart = cart.filter(x => x.id !== id); save(); render(); }
function clearCart() { cart = []; discountAmt = 0; appliedCoupon = null; save(); render(); }

async function applyCoupon() {
  const v = document.getElementById('coupon').value.trim().toUpperCase();
  if (!v) { alert('Enter a promo code'); return; }
  const subtotal = cart.reduce((s, i) => s + i.price * i.qty, 0);
  try {
    const res = await fetch((window.API_BASE || '') + '/api/coupon/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: v, subtotal })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) { alert(data.error || 'Invalid promo code'); return; }
    discountAmt = data.discount;
    appliedCoupon = data.code;
    updateSummary();
    alert('Promo code applied! You saved ₹' + data.discount);
  } catch (err) {
    alert('Could not apply the code right now, please try again.');
  }
}

async function checkout(method) {
  if (!cart.length) return;
  const customer = typeof getCustomer === 'function' ? getCustomer() : null;
  if (!customer) { window.location.href = '/login'; return; }
  if (!selectedAddressId) { alert('Please select a delivery address.'); return; }

  const checkoutPayload = {
    items: cart.map(item => ({ item_id: item.id, qty: item.qty })),
    channel: method,
    coupon_code: appliedCoupon,
    phone: customer.phone,
    address_id: selectedAddressId,
  };

  try {
    const idempotencyKey = checkoutIdempotencyKey(checkoutPayload);
    const res = await customerFetch('/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(checkoutPayload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (res.status === 401) { window.location.href = '/login'; return; }
      alert(data.error || 'Something went wrong placing your order.');
      return;
    }

    cart = []; discountAmt = 0; appliedCoupon = null;
    sessionStorage.removeItem('surenCheckoutRequest');
    save();
    window.location.href = '/track/' + data.order_number;
  } catch (err) {
    alert('Could not reach the server, please check your connection and try again.');
  }
}

function checkoutIdempotencyKey(payload) {
  const fingerprint = JSON.stringify(payload);
  let saved = null;
  try {
    saved = JSON.parse(sessionStorage.getItem('surenCheckoutRequest') || 'null');
  } catch (err) {
    sessionStorage.removeItem('surenCheckoutRequest');
  }
  if (!saved || saved.fingerprint !== fingerprint) {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    const key = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    saved = { fingerprint, key };
    sessionStorage.setItem('surenCheckoutRequest', JSON.stringify(saved));
  }
  return saved.key;
}

function closeModal() {
  document.getElementById('overlay').classList.remove('show');
  cart = []; discountAmt = 0; appliedCoupon = null;
  save(); render();
  location.href = '/home';
}

// ───────────────────────── event delegation ─────────────────────────
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  switch (el.dataset.action) {
    case 'clear-cart': clearCart(); break;
    case 'change-qty': change(parseInt(el.dataset.id, 10), parseInt(el.dataset.delta, 10)); break;
    case 'remove-item': remove(parseInt(el.dataset.id, 10)); break;
    case 'checkout': checkout(el.dataset.method); break;
    case 'apply-coupon': applyCoupon(); break;
    case 'close-modal': closeModal(); break;
  }
});
document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  if (el.dataset.action === 'select-address') {
    selectedAddressId = parseInt(el.value, 10);
  }
});

render();
