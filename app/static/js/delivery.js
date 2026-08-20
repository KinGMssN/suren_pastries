const DELIVERY_API_BASE = window.API_BASE || '';

function getDeliveryPersonId() {
  return localStorage.getItem('surenDeliveryPersonId') || '';
}
function setDeliveryPersonId(id) {
  localStorage.setItem('surenDeliveryPersonId', id);
}

async function loadPeoplePicker() {
  const select = document.getElementById('who-am-i');
  try {
    const res = await fetch(DELIVERY_API_BASE + '/api/delivery/people');
    const people = await res.json();
    if (!people.length) {
      select.innerHTML = '<option value="">No delivery staff added yet — ask admin to add you</option>';
      return;
    }
    select.innerHTML = '<option value="">Select your name…</option>' +
      people.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
    const saved = getDeliveryPersonId();
    if (saved) select.value = saved;
  } catch (err) {
    select.innerHTML = '<option value="">Could not load staff list</option>';
  }
}

function onWhoAmIChange() {
  const id = document.getElementById('who-am-i').value;
  setDeliveryPersonId(id);
  loadOrders();
}

const STATUS_LABEL = { pending: 'New', preparing: 'Preparing', ready: 'Ready for pickup', delivered: 'Delivered' };

async function loadOrders() {
  const list = document.getElementById('delivery-orders');
  list.innerHTML = '<p class="dl-empty">Loading…</p>';
  try {
    const res = await fetch(DELIVERY_API_BASE + '/api/delivery/orders');
    const orders = await res.json();
    if (!orders.length) {
      list.innerHTML = '<p class="dl-empty">No orders need delivery right now 🎉</p>';
      return;
    }
    const myId = getDeliveryPersonId();
    list.innerHTML = orders.map(o => {
      const isMine = myId && String(o.delivery_person_id) === String(myId);
      const isUnassigned = !o.delivery_person_id;
      const mapsUrl = 'https://maps.google.com/?q=' + encodeURIComponent(
        [o.delivery_address, o.delivery_city, o.delivery_pincode].filter(Boolean).join(', ')
      );
      return `
        <div class="dl-card">
          <div class="dl-top">
            <strong>${o.order_number}</strong>
            <span class="dl-status">${STATUS_LABEL[o.status] || o.status}</span>
          </div>
          <div class="dl-customer">${o.customer_name} · <a href="tel:${o.customer_phone}">${o.customer_phone}</a></div>
          <div class="dl-address">📍 <a href="${mapsUrl}" target="_blank" rel="noopener">${o.delivery_address}${o.delivery_city ? ', ' + o.delivery_city : ''}${o.delivery_pincode ? ' - ' + o.delivery_pincode : ''}</a></div>
          <div class="dl-items">${o.items.map(i => `${i.qty}× ${i.name}`).join(', ')}</div>
          <div class="dl-bottom">
            <span class="dl-total">₹${o.total}${o.channel === 'cod' ? ' · Cash on delivery' : ' · ' + o.channel}</span>
            ${o.delivery_person ? `<span class="dl-assigned">Assigned: ${o.delivery_person}</span>` : ''}
          </div>
          <div class="dl-actions">
            ${isUnassigned ? `<button class="dl-btn dl-btn-assign" onclick="assignToMe(${o.id})">Take this order</button>` : ''}
            ${isMine ? `<button class="dl-btn dl-btn-deliver" onclick="markDelivered(${o.id}, ${o.channel === 'cod'})">Mark delivered</button>` : ''}
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    list.innerHTML = '<p class="dl-empty">Could not load orders.</p>';
  }
}

async function assignToMe(orderId) {
  const personId = getDeliveryPersonId();
  if (!personId) { alert('Select your name first.'); return; }
  try {
    await fetch(DELIVERY_API_BASE + '/api/delivery/orders/' + orderId + '/assign', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delivery_person_id: parseInt(personId) }),
    });
    loadOrders();
    window.open('/delivery/order/' + orderId, '_blank');
  } catch (err) { alert('Could not assign order.'); }
}

async function markDelivered(orderId, isCod) {
  let codCollected = true;
  if (isCod) {
    codCollected = confirm('Did you collect the cash payment for this order?');
  }
  if (!confirm('Mark this order as delivered?')) return;
  try {
    await fetch(DELIVERY_API_BASE + '/api/delivery/orders/' + orderId + '/deliver', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delivery_person_id: parseInt(getDeliveryPersonId()), cod_collected: codCollected }),
    });
    loadOrders();
  } catch (err) { alert('Could not update order.'); }
}

loadPeoplePicker();
loadOrders();
setInterval(loadOrders, 20000); // light auto-refresh so the list stays current