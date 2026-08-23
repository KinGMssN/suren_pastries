const STAGES = ['pending', 'preparing', 'ready', 'delivered'];
const STAGE_LABELS = { pending: 'Order placed', preparing: 'Preparing', ready: 'Ready', delivered: 'Delivered' };

async function loadTrackedOrder() {
  try {
    const res = await fetch('/api/orders/track/' + window.ORDER_NUMBER);
    const order = await res.json();
    if (!res.ok) {
      document.getElementById('tr-message').textContent = 'Order not found';
      document.getElementById('tr-submessage').textContent = order.error || '';
      return;
    }
    render(order);
    if (order.status !== 'delivered') {
      setTimeout(loadTrackedOrder, 8000); // keep polling until delivered
    }
  } catch (err) {
    document.getElementById('tr-submessage').textContent = 'Could not reach the server — retrying…';
    setTimeout(loadTrackedOrder, 8000);
  }
}

function render(order) {
  // Stepper
  const currentIndex = STAGES.indexOf(order.status);
  document.getElementById('tr-stepper').innerHTML = STAGES.map((s, i) => {
    const cls = i < currentIndex ? 'done' : (i === currentIndex ? 'current' : '');
    const icon = i < currentIndex ? '✓' : (i + 1);
    return `<div class="tr-step ${cls}"><div class="tr-step-dot">${icon}</div><div class="tr-step-label">${STAGE_LABELS[s]}</div></div>`;
  }).join('');

  // Headline message
  const messages = {
    pending: ['Order received!', "We've got your order and we're getting started."],
    preparing: ['Your food is being prepared 👨‍🍳', 'Our kitchen is working on it right now.'],
    ready: [order.delivery_person ? 'Food is prepared! On the way 🚴' : 'Food is ready!', order.delivery_person ? `${order.delivery_person} has your order.` : 'Waiting for a delivery partner to pick it up.'],
    delivered: ['Delivered! Enjoy your meal 🎉', order.delivered_at ? `Delivered at ${order.delivered_at}` : ''],
  };
  const [msg, sub] = messages[order.status] || ['Order status: ' + order.status, ''];
  document.getElementById('tr-message').textContent = msg;
  document.getElementById('tr-submessage').textContent = sub;

  // Delivery partner card (shown once assigned)
  const partnerEl = document.getElementById('tr-partner');
  if (order.delivery_person && order.status !== 'delivered') {
    partnerEl.style.display = 'flex';
    partnerEl.innerHTML = `
      <div class="tr-partner-avatar">🚴</div>
      <div>
        <div class="tr-partner-name">${order.delivery_person}</div>
        <div class="tr-partner-role">Your delivery partner</div>
      </div>
    `;
  } else {
    partnerEl.style.display = 'none';
  }

  // Order summary
  document.getElementById('tr-items').innerHTML = order.items.map(i =>
    `<div class="tr-item-row"><span>${i.qty}× ${i.name}</span><span>₹${i.price * i.qty}</span></div>`
  ).join('');
  document.getElementById('tr-total').textContent = '₹' + order.total;
  document.getElementById('tr-address').textContent =
    [order.delivery_address, order.delivery_city, order.delivery_pincode].filter(Boolean).join(', ');
  document.getElementById('tr-payment').textContent =
    order.channel === 'cod' ? 'Cash on delivery' + (order.cod_collected ? ' (paid)' : '') : order.channel;
}

loadTrackedOrder();