let cart = JSON.parse(localStorage.getItem('surenPastriesCart')) || [];
let discountAmt = 0;
let appliedCoupon = null;

function save() {
  localStorage.setItem('surenPastriesCart', JSON.stringify(cart));
  localStorage.setItem('cartCount', cart.reduce((s, i) => s + i.qty, 0));
}

function render() {
  const card = document.getElementById('items-card');
  const sum = document.getElementById('summary-card');
  const count = cart.reduce((s, i) => s + i.qty, 0);
  document.getElementById('item-count').textContent = count ? `${count} item${count > 1 ? 's' : ''} in your cart` : 'Your cart is empty';

  if (!cart.length) {
    card.innerHTML = `<div class="empty"><div class="empty-big">🛒</div><h3>Your cart is empty</h3><p>Add some delicious items from our menu</p><a class="btn-p" href="${window.MENU_URL}">Browse menu</a></div>`;
    sum.style.display = 'none';
    return;
  }
  sum.style.display = 'block';
  card.innerHTML = `
    <div class="items-card-head"><h3>Items (${count})</h3><button class="clear-btn" onclick="clearCart()">Clear all</button></div>
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
            <button class="qb" onclick="change(${i.id},-1)">−</button>
            <div class="qn">${i.qty}</div>
            <button class="qb" onclick="change(${i.id},1)">+</button>
          </div>
        </div>
        <button class="del-btn" onclick="remove(${i.id})">🗑</button>
      </div>
    `).join('')}
  `;
  updateSummary();
}

function updateSummary() {
  const sub = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const delivery = sub >= window.FREE_DELIVERY_THRESHOLD ? 0 : window.DELIVERY_FEE;
  const tax = Math.round(sub * window.TAX_RATE);
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
    const res = await fetch(window.API_BASE + '/api/coupon/apply', {
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
  const overlay = document.getElementById('overlay');
  try {
    const res = await fetch(window.API_BASE + '/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        items: cart,
        channel: method,
        coupon_code: appliedCoupon
      })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) { alert(data.error || 'Something went wrong placing your order.'); return; }

    if (method === 'online') {
      document.getElementById('modal-icon').textContent = '💳';
      document.getElementById('modal-title').textContent = 'Payment successful!';
      document.getElementById('modal-sub').textContent = `Order ${data.order_number} confirmed — total ₹${data.total}. Delivery in 25–35 minutes.`;
    } else {
      document.getElementById('modal-icon').textContent = '💬';
      document.getElementById('modal-title').textContent = 'Order placed!';
      document.getElementById('modal-sub').textContent = `Order ${data.order_number} confirmed — total ₹${data.total}. Complete the chat on WhatsApp for live updates.`;
    }
    overlay.classList.add('show');
  } catch (err) {
    alert('Could not reach the server, please check your connection and try again.');
  }
}

function closeModal() {
  document.getElementById('overlay').classList.remove('show');
  cart = []; discountAmt = 0; appliedCoupon = null;
  save(); render();
  location.href = window.HOME_URL;
}

render();
