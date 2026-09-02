async function loadOrderDetail() {
  const box = document.getElementById('do-content');
  const orderId = document.body.dataset.orderId;
  try {
    const res = await fetch('/api/delivery/orders/' + orderId);
    const o = await res.json();
    if (!res.ok) { box.innerHTML = `<p class="dl-empty">${o.error || 'Order not found'}</p>`; return; }

    const mapsUrl = 'https://maps.google.com/?q=' + encodeURIComponent(
      [o.delivery_address, o.delivery_city, o.delivery_pincode].filter(Boolean).join(', ')
    );
    const alreadyDelivered = o.status === 'delivered';

    box.innerHTML = `
      <div class="dl-card">
        <div class="dl-top">
          <strong>${o.order_number}</strong>
          <span class="dl-status">${o.status}</span>
        </div>
        <div class="dl-customer" style="font-size:15px;margin-bottom:8px">${o.customer_name} · <a href="tel:${o.customer_phone}">📞 ${o.customer_phone}</a></div>
        <div class="dl-address" style="font-size:14px;margin-bottom:12px">📍 <a href="${mapsUrl}" target="_blank" rel="noopener">${o.delivery_address}${o.delivery_city ? ', ' + o.delivery_city : ''}${o.delivery_pincode ? ' - ' + o.delivery_pincode : ''}</a></div>
        <div class="tr-divider"></div>
        <div class="tr-card-title" style="margin-top:12px">Items</div>
        ${o.items.map(i => `<div class="tr-item-row"><span>${i.qty}× ${i.name}</span><span>₹${i.price * i.qty}</span></div>`).join('')}
        <div class="tr-divider"></div>
        <div class="tr-total-row"><span>Total</span><span>₹${o.total}</span></div>
        <div class="dl-bottom" style="margin-top:12px">
          <span>${o.channel === 'cod' ? '💵 Collect cash on delivery' : '✅ Already paid (' + o.channel + ')'}</span>
        </div>
      </div>
      ${alreadyDelivered
        ? `<p class="dl-empty">This order has already been marked delivered.</p>`
        : `<button class="dl-btn dl-btn-deliver" style="width:100%;padding:14px" data-action="mark-delivered-detail" data-id="${o.id}" data-cod="${o.channel === 'cod'}">Mark delivered</button>`
      }
    `;
  } catch (err) {
    box.innerHTML = `<p class="dl-empty">Could not load order details.</p>`;
  }
}

async function markDeliveredFromDetail(orderId, isCod) {
  let codCollected = true;
  if (isCod) codCollected = confirm('Did you collect the cash payment for this order?');
  if (!confirm('Mark this order as delivered?')) return;
  const personId = localStorage.getItem('surenDeliveryPersonId') || '';
  try {
    await fetch('/api/delivery/orders/' + orderId + '/deliver', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delivery_person_id: personId ? parseInt(personId) : null, cod_collected: codCollected }),
    });
    loadOrderDetail();
  } catch (err) { alert('Could not update order.'); }
}
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  if (el.dataset.action === 'mark-delivered-detail') {
    markDeliveredFromDetail(parseInt(el.dataset.id, 10), el.dataset.cod === 'true');
  }
});

loadOrderDetail();