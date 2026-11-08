function appendText(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value;
  parent.appendChild(element);
  return element;
}

function showOrderError(message, needsLogin = false) {
  const box = document.getElementById('do-content');
  box.replaceChildren();
  appendText(box, 'p', 'dl-empty', message);
  if (needsLogin) {
    const link = appendText(box, 'a', 'dl-empty', 'Sign in to the delivery portal');
    link.href = '/delivery';
  }
}

async function loadOrderDetail() {
  const box = document.getElementById('do-content');
  const orderId = document.body.dataset.orderId;
  try {
    const res = await fetch('/api/delivery/orders/' + encodeURIComponent(orderId));
    const order = await res.json().catch(() => ({}));
    if (!res.ok) {
      showOrderError(order.error || 'Could not load this order.', res.status === 401);
      return;
    }

    box.replaceChildren();
    const card = document.createElement('article');
    card.className = 'dl-card';
    const top = document.createElement('div');
    top.className = 'dl-top';
    appendText(top, 'strong', '', order.order_number);
    appendText(top, 'span', 'dl-status', order.status);
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

    card.appendChild(document.createElement('hr'));
    appendText(card, 'h2', 'tr-card-title', 'Items');
    order.items.forEach(item => {
      appendText(card, 'div', 'tr-item-row', `${item.qty}× ${item.name} — ₹${item.price * item.qty}`);
    });
    appendText(card, 'div', 'tr-total-row', `Total: ₹${order.total}`);
    appendText(card, 'div', 'dl-bottom', order.channel === 'cod' ? 'Cash on delivery' : `Payment channel: ${order.channel}`);
    box.appendChild(card);

    if (order.status === 'ready') {
      const button = appendText(box, 'button', 'dl-btn dl-btn-deliver', 'Mark delivered');
      button.type = 'button';
      button.dataset.action = 'mark-delivered-detail';
      button.dataset.id = order.id;
      button.dataset.cod = String(order.channel === 'cod');
    } else if (order.status === 'delivered') {
      appendText(box, 'p', 'dl-empty', 'This order has already been marked delivered.');
    } else {
      appendText(box, 'p', 'dl-empty', 'An administrator must mark this order ready before delivery.');
    }
  } catch (err) {
    showOrderError('Could not reach the server. Please try again.');
  }
}

async function markDeliveredFromDetail(orderId, isCod) {
  const codCollected = isCod ? confirm('Did you collect the cash payment for this order?') : false;
  if (isCod && !codCollected) {
    alert('The order cannot be marked delivered until the COD payment is collected.');
    return;
  }
  if (!confirm('Mark this order as delivered?')) return;
  try {
    const response = await fetch('/api/delivery/orders/' + encodeURIComponent(orderId) + '/deliver', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cod_collected: codCollected }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showOrderError(data.error || 'Could not update this order.', response.status === 401);
      return;
    }
    await loadOrderDetail();
  } catch (err) {
    alert('Could not reach the server. Please try again.');
  }
}

document.addEventListener('click', event => {
  const element = event.target.closest('[data-action="mark-delivered-detail"]');
  if (element) {
    markDeliveredFromDetail(parseInt(element.dataset.id, 10), element.dataset.cod === 'true');
  }
});

loadOrderDetail();
