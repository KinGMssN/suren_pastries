const STAGES = ['pending', 'preparing', 'ready', 'delivered'];
const STAGE_LABELS = { pending: 'Order placed', preparing: 'Preparing', ready: 'Ready', delivered: 'Delivered' };
const ORDER_NUMBER = document.body.dataset.orderNumber;

async function loadTrackedOrder() {
  try {
    const res = await fetch('/api/orders/track/' + ORDER_NUMBER);
    const order = await res.json();
    if (!res.ok) {
      document.getElementById('tr-message').textContent = 'Order not found';
      document.getElementById('tr-submessage').textContent = order.error || '';
      return;
    }
    render(order);
    if (order.status !== 'delivered') {
      setTimeout(loadTrackedOrder, 8000);
    }
  } catch (err) {
    document.getElementById('tr-submessage').textContent = 'Could not reach the server — retrying…';
    setTimeout(loadTrackedOrder, 8000);
  }
}

function render(order) {
  const currentIndex = STAGES.indexOf(order.status);
  document.getElementById('tr-stepper').innerHTML = STAGES.map((s, i) => {
    const cls = i < currentIndex ? 'done' : (i === currentIndex ? 'current' : '');
    const icon = i < currentIndex ? '✓' : (i + 1);
    return `<div class="tr-step ${cls}"><div class="tr-step-dot">${icon}</div><div class="tr-step-label">${STAGE_LABELS[s]}</div></div>`;
  }).join('');

  const messages = {
    pending: ['Order received!', "We've got your order and we're getting started."],
    preparing: ['Your food is being prepared 👨‍🍳', 'Our kitchen is working on it right now.'],
    ready: [order.has_delivery_person ? 'Food is prepared! On the way 🚴' : 'Food is ready!', order.has_delivery_person ? 'A delivery partner has your order.' : 'Waiting for a delivery partner to pick it up.'],
    delivered: ['Delivered! Enjoy your meal 🎉', order.delivered_at ? `Delivered at ${order.delivered_at}` : ''],
  };
  const [msg, sub] = messages[order.status] || ['Order status: ' + order.status, ''];
  document.getElementById('tr-message').textContent = msg;
  document.getElementById('tr-submessage').textContent = sub;

  const partnerEl = document.getElementById('tr-partner');
  if (order.has_delivery_person && order.status !== 'delivered') {
    partnerEl.style.display = 'flex';
    partnerEl.textContent = 'A delivery partner has been assigned to your order.';
  } else {
    partnerEl.style.display = 'none';
  }

  document.getElementById('tr-items').innerHTML = order.items.map(i =>
    `<div class="tr-item-row"><span>${i.qty}× ${i.name}</span><span>₹${i.price * i.qty}</span></div>`
  ).join('');
  document.getElementById('tr-subtotal').textContent = '₹' + order.subtotal;
  document.getElementById('tr-delivery-fee').textContent = order.delivery_fee === 0 ? 'FREE' : '₹' + order.delivery_fee;
  document.getElementById('tr-tax').textContent = '₹' + order.tax;
  document.getElementById('tr-discount').textContent = '−₹' + order.discount;
  document.getElementById('tr-discount-row').hidden = !order.discount;
  document.getElementById('tr-total').textContent = '₹' + order.total;
  document.getElementById('tr-payment').textContent =
    order.channel === 'cod' ? 'Cash on delivery' : 'Payment status unavailable';
}

loadTrackedOrder();