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
    card.innerHTML = `<div class="empty"><div class="empty-big">🛒</div><h3>Your cart is empty</h3><p>Add some delicious items from our menu</p><a class="btn-p" href="/menu">Browse menu</a></div>`;
    sum.style.display = 'none';
    return;
  }
  sum.style.display = 'block';
  card.innerHTML = `
    <div class="items-card-head"><h3>Items (${count})</h3><button class="clear-btn" data-action="clear-cart">Clear all</button></div>
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
            <button class="qb" data-action="change-qty" data-id="${i.id}" data-delta="-1">−</button>
            <div class="qn">${i.qty}</div>
            <button class="qb" data-action="change-qty" data-id="${i.id}" data-delta="1">+</button>
          </div>
        </div>
        <button class="del-btn" data-action="remove-item" data-id="${i.id}">🗑</button>
      </div>
    `).join('')}
  `;
  updateSummary();
  await renderCheckoutArea();
}

function updateSummary() {
  const sub = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const delivery = sub >= 499 ? 0 : 40;
  const tax = Math.round(sub * 0.05);
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

// Swaps the checkout buttons for a "please log in" prompt, or an address
// picker + payment buttons, depending on login state.
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
    const res = await fetch((window.API_BASE || '') + '/api/customer/addresses?phone=' + encodeURIComponent(customer.phone));
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
      <label class="acct-label">Deliver to</label>
      <select class="acct-input" id="address-select" data-action="select-address">
        ${addresses.map(a => `<option value="${a.id}" ${a.id === selectedAddressId ? 'selected' : ''}>${a.label} — ${a.address_line}${a.city ? ', ' + a.city : ''}</option>`).join('')}
      </select>
    </div>
    <div class="checkout-stack">
      <button class="co-btn co-wa" data-action="checkout" data-method="whatsapp">💬 Order via WhatsApp</button>
      <button class="co-btn co-online" data-action="checkout" data-method="online">💳 Pay online</button>
      <button class="co-btn co-cod" data-action="checkout" data-method="cod">💵 Cash on delivery</button>
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

  try {
    const res = await fetch((window.API_BASE || '') + '/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: cart,
        channel: method,
        coupon_code: appliedCoupon,
        phone: customer.phone,
        address_id: selectedAddressId,
      })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (res.status === 401) { window.location.href = '/login'; return; }
      alert(data.error || 'Something went wrong placing your order.');
      return;
    }

    cart = []; discountAmt = 0; appliedCoupon = null;
    save();
    window.location.href = '/track/' + data.order_number;
  } catch (err) {
    alert('Could not reach the server, please check your connection and try again.');
  }
}

function closeModal() {
  document.getElementById('overlay').classList.remove('show');
  cart = []; discountAmt = 0; appliedCoupon = null;
  save(); render();
  location.href = '/home';
}

// ───────────────────────── event delegation ─────────────────────────
// Dynamically-generated buttons use data-action instead of onclick="...",
// since inline event handlers are blocked by this site's CSP.
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