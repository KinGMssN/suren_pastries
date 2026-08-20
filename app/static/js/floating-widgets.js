// Injects two floating buttons into the page:
//  - a cart bubble (bottom-right) showing the current item count
//  - a "track order" pill (bottom-left), shown only when the logged-in
//    customer has an order that isn't delivered yet
// Not loaded on cart.html — no point showing "go to cart" while already there.

(function () {
  function renderCartBubble() {
    const count = parseInt(localStorage.getItem('cartCount') || '0', 10);
    let btn = document.getElementById('floating-cart-btn');
    if (!count) {
      if (btn) btn.remove();
      return;
    }
    if (!btn) {
      btn = document.createElement('a');
      btn.id = 'floating-cart-btn';
      btn.className = 'floating-cart-btn';
      btn.href = '/cart';
      document.body.appendChild(btn);
    }
    btn.innerHTML = `🛒<span class="floating-badge">${count}</span>`;
  }

  async function renderTrackPill() {
    if (typeof getCustomer !== 'function') return;
    const customer = getCustomer();
    if (!customer) return;
    try {
      const base = window.API_BASE || '';
      const res = await fetch(base + '/api/customer/orders?phone=' + encodeURIComponent(customer.phone));
      const orders = await res.json();
      const active = orders.find(o => o.status !== 'delivered');
      const existing = document.getElementById('floating-track-btn');
      if (!active) { if (existing) existing.remove(); return; }
      if (existing) existing.remove(); // rebuild so the status label stays current

      const btn = document.createElement('a');
      btn.id = 'floating-track-btn';
      btn.className = 'floating-track-btn';
      btn.href = '/track/' + active.order_number;
      btn.innerHTML = `📦 Track order <span class="floating-track-status">${active.status}</span>`;
      document.body.appendChild(btn);
    } catch (err) { /* fail silently, not critical */ }
  }

  renderCartBubble();
  renderTrackPill();
  setInterval(renderCartBubble, 2000);   // picks up cart changes made on this tab
  setInterval(renderTrackPill, 20000);   // occasional refresh of order status label
})();