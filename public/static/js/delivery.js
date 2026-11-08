const DELIVERY_API_BASE = window.API_BASE || '';

const STATUS_LABEL = { pending: 'New', preparing: 'Preparing', ready: 'Ready for pickup', delivered: 'Delivered' };

function addText(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value;
  parent.appendChild(element);
  return element;
}

function showDeliveryError(message) {
  const error = document.getElementById('delivery-error');
  error.textContent = message;
  error.hidden = false;
}

async function readResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(data.error || 'Request failed.');
  }
  return data;
}

function showLogin() {
  document.getElementById('delivery-login-form').hidden = false;
  document.getElementById('delivery-work').hidden = true;
}

function showWork() {
  document.getElementById('delivery-login-form').hidden = true;
  document.getElementById('delivery-work').hidden = false;
}

async function loadOrders() {
  const list = document.getElementById('delivery-orders');
  list.replaceChildren();
  addText(list, 'p', 'dl-empty', 'Loading…');
  try {
    const res = await fetch(DELIVERY_API_BASE + '/api/delivery/orders');
    const orders = await readResponse(res);
    showWork();
    list.replaceChildren();
    if (!orders.length) {
      addText(list, 'p', 'dl-empty', 'No orders assigned to you need delivery right now.');
      return;
    }
    orders.forEach(order => {
      const card = document.createElement('article');
      card.className = 'dl-card';
      const top = document.createElement('div');
      top.className = 'dl-top';
      addText(top, 'strong', '', order.order_number);
      addText(top, 'span', 'dl-status', STATUS_LABEL[order.status] || order.status);
      card.appendChild(top);

      const customer = document.createElement('div');
      customer.className = 'dl-customer';
      customer.appendChild(document.createTextNode((order.customer_name || 'Customer') + ' · '));
      const phone = document.createElement('a');
      const safePhone = String(order.customer_phone || '').replace(/[^\d+]/g, '');
      phone.setAttribute('href', 'tel:' + safePhone);
      phone.textContent = order.customer_phone || '';
      customer.appendChild(phone);
      card.appendChild(customer);

      const address = document.createElement('div');
      address.className = 'dl-address';
      const mapsUrl = 'https://maps.google.com/?q=' + encodeURIComponent(
        [order.delivery_address, order.delivery_city, order.delivery_pincode].filter(Boolean).join(', ')
      );
      const mapLink = document.createElement('a');
      mapLink.setAttribute('href', mapsUrl);
      mapLink.setAttribute('target', '_blank');
      mapLink.setAttribute('rel', 'noopener');
      mapLink.textContent = [order.delivery_address, order.delivery_city, order.delivery_pincode].filter(Boolean).join(', ');
      address.append(document.createTextNode('📍 '), mapLink);
      card.appendChild(address);

      addText(card, 'div', 'dl-items', order.items.map(item => `${item.qty}× ${item.name}`).join(', '));
      addText(card, 'div', 'dl-total', `₹${order.total} · ${order.channel === 'cod' ? 'Cash on delivery' : order.channel}`);
      if (order.status === 'ready') {
        const actions = document.createElement('div');
        actions.className = 'dl-actions';
        const button = addText(actions, 'button', 'dl-btn dl-btn-deliver', 'Mark delivered');
        button.type = 'button';
        button.dataset.action = 'mark-delivered';
        button.dataset.id = order.id;
        button.dataset.cod = String(order.channel === 'cod');
        card.appendChild(actions);
      } else {
        addText(card, 'p', 'dl-empty', 'The order must be marked ready by an administrator before delivery.');
      }
      list.appendChild(card);
    });
  } catch (err) {
    list.replaceChildren();
    addText(list, 'p', 'dl-empty', err.message || 'Could not load orders.');
  }
}

async function login(event) {
  event.preventDefault();
  const error = document.getElementById('delivery-error');
  error.hidden = true;
  try {
    const res = await fetch(DELIVERY_API_BASE + '/api/delivery/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: document.getElementById('delivery-name').value.trim(),
        password: document.getElementById('delivery-password').value,
      }),
    });
    await readResponse(res);
    document.getElementById('delivery-password').value = '';
    showWork();
    await loadOrders();
  } catch (err) {
    showDeliveryError(err.message);
  }
}

async function logout() {
  try {
    await fetch(DELIVERY_API_BASE + '/api/delivery/logout', { method: 'POST' });
  } finally {
    showLogin();
    document.getElementById('delivery-orders').replaceChildren();
  }
}

async function markDelivered(orderId, isCod) {
  const codCollected = isCod ? confirm('Did you collect the cash payment for this order?') : false;
  if (isCod && !codCollected) {
    alert('The order cannot be marked delivered until the COD payment is collected.');
    return;
  }
  if (!confirm('Mark this order as delivered?')) return;
  try {
    const res = await fetch(DELIVERY_API_BASE + '/api/delivery/orders/' + orderId + '/deliver', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cod_collected: codCollected }),
    });
    await readResponse(res);
    loadOrders();
  } catch (err) { alert(err.message || 'Could not update order.'); }
}

// ───────────────────────── event delegation ─────────────────────────
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const id = parseInt(el.dataset.id, 10);
  if (el.dataset.action === 'mark-delivered') markDelivered(id, el.dataset.cod === 'true');
  if (el.dataset.action === 'delivery-logout') logout();
});
document.getElementById('delivery-login-form').addEventListener('submit', login);

fetch(DELIVERY_API_BASE + '/api/delivery/orders')
  .then(readResponse)
  .then(() => { showWork(); loadOrders(); })
  .catch(() => showLogin());

setInterval(() => {
  if (!document.getElementById('delivery-work').hidden) loadOrders();
}, 20000);