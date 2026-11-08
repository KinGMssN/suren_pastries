const STAGES = ['pending', 'accepted', 'preparing', 'ready', 'delivered'];
const STAGE_LABELS = { pending: 'Pending', accepted: 'Accepted', preparing: 'Preparing', ready: 'Ready', delivered: 'Delivered' };
const ORDER_NUMBER = document.body.dataset.orderNumber;
const payButton = document.getElementById('tr-pay-online');
const confirmQuoteButton = document.getElementById('tr-confirm-quote');
const paymentMessage = document.getElementById('tr-payment-message');
const referenceImageButton = document.getElementById('tr-reference-button');
const referenceImagePreview = document.getElementById('tr-reference-preview');

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
    if (!['delivered', 'rejected'].includes(order.status)) {
      setTimeout(loadTrackedOrder, 8000);
    }
  } catch (err) {
    document.getElementById('tr-submessage').textContent = 'Could not reach the server — retrying…';
    setTimeout(loadTrackedOrder, 8000);
  }
}

function render(order) {
  const cakeDetails = document.getElementById('tr-cake-details');
  if (order.custom_cake_details) {
    const details = order.custom_cake_details;
    cakeDetails.hidden = false;
    cakeDetails.textContent = [
      `Cake details: ${details.description}`,
      `Needed: ${details.required_date}`,
    ].filter(Boolean).join(' · ');
    referenceImageButton.hidden = !details.has_reference_image;
    if (!details.has_reference_image) {
      referenceImagePreview.hidden = true;
      referenceImagePreview.replaceChildren();
    }
  } else {
    cakeDetails.hidden = true;
    referenceImageButton.hidden = true;
    referenceImagePreview.hidden = true;
    referenceImagePreview.replaceChildren();
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
  document.getElementById('tr-payment').textContent = order.channel === 'cod'
    ? 'Cash on delivery'
    : order.payment_status === 'paid' ? 'Paid online' : 'Online payment';
  const needsQuoteConfirmation = Boolean(
    order.custom_cake_details && order.status === 'accepted' && !order.quote_confirmed
  );
  confirmQuoteButton.hidden = !needsQuoteConfirmation;
  payButton.hidden = order.channel !== 'online'
    || order.status !== 'accepted'
    || order.payment_status === 'paid'
    || Boolean(order.custom_cake_details && !order.quote_confirmed);
  paymentMessage.textContent = order.channel === 'online'
    ? order.payment_status === 'paid'
      ? 'Payment confirmed.'
      : order.status === 'accepted'
        ? order.custom_cake_details
          ? order.quote_confirmed
            ? 'Quote confirmed. Complete online payment to begin preparation.'
            : `The bakery quoted ₹${order.total}. Confirm the price to continue.`
          : 'Your order is accepted. Complete payment to begin preparation.'
        : order.status === 'rejected'
          ? 'No payment has been collected for this rejected order.'
          : 'Payment will be available after the admin accepts your order.'
    : order.custom_cake_details && order.status === 'accepted'
      ? order.quote_confirmed
        ? `Quote confirmed: ₹${order.total}.`
        : `The bakery quoted ₹${order.total}. Confirm the price to continue.`
      : '';

  if (order.status === 'rejected') {
    document.getElementById('tr-stepper').replaceChildren();
    document.getElementById('tr-message').textContent = 'Your order is rejected.';
    document.getElementById('tr-submessage').textContent = '';
    document.getElementById('tr-partner').style.display = 'none';
    return;
  }

  const currentIndex = STAGES.indexOf(order.status);
  document.getElementById('tr-stepper').innerHTML = STAGES.map((s, i) => {
    const cls = i < currentIndex ? 'done' : (i === currentIndex ? 'current' : '');
    const icon = i < currentIndex ? '✓' : (i + 1);
    return `<div class="tr-step ${cls}"><div class="tr-step-dot">${icon}</div><div class="tr-step-label">${STAGE_LABELS[s]}</div></div>`;
  }).join('');

  const messages = {
    pending: ['Order received!', 'Your order is waiting for bakery approval.'],
    accepted: ['Order accepted!', order.custom_cake_details ? 'Review the bakery’s quote below.' : 'Complete your online payment to begin preparation.'],
    preparing: ['Your food is being prepared 👨‍🍳', 'Our kitchen is working on it right now.'],
    ready: [order.has_delivery_person ? 'Order ready · on the way 🚴' : 'Order ready!', ''],
    delivered: ['Delivered! Enjoy your meal 🎉', order.delivered_at ? `Delivered at ${order.delivered_at}` : ''],
  };
  const [msg, sub] = messages[order.status] || ['Order status: ' + order.status, ''];
  document.getElementById('tr-message').textContent = msg;
  document.getElementById('tr-submessage').textContent = sub;

  const partnerEl = document.getElementById('tr-partner');
  if (order.has_delivery_person && order.status !== 'delivered') {
    partnerEl.style.display = 'flex';
    partnerEl.textContent = 'Delivery partner assigned';
  } else {
    partnerEl.style.display = 'none';
  }

}

async function payOnline() {
  payButton.disabled = true;
  paymentMessage.textContent = 'Preparing secure payment…';
  try {
    const response = await customerFetch('/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'create_payment', order_number: ORDER_NUMBER }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      if (response.status === 401) {
        window.location.href = '/login';
        return;
      }
      throw new Error(data.error || 'Could not start payment.');
    }
    if (data.payment_status === 'paid') {
      await loadTrackedOrder();
      return;
    }
    if (typeof window.Razorpay !== 'function') {
      throw new Error('The secure payment window could not be loaded. Please try again.');
    }

    const checkout = new window.Razorpay({
      key: data.key_id,
      amount: data.amount,
      currency: data.currency,
      name: 'Suren Pastries',
      description: `Order ${data.order_number}`,
      order_id: data.razorpay_order_id,
      prefill: { name: data.customer_name, contact: data.customer_phone },
      handler: async (payment) => {
        try {
          const verification = await customerFetch('/api/checkout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              action: 'verify_payment',
              order_number: ORDER_NUMBER,
              razorpay_order_id: payment.razorpay_order_id,
              razorpay_payment_id: payment.razorpay_payment_id,
              razorpay_signature: payment.razorpay_signature,
            }),
          });
          const result = await verification.json();
          if (!verification.ok || !result.ok) throw new Error(result.error || 'Payment verification failed.');
          paymentMessage.textContent = 'Payment confirmed. Your order is being prepared.';
          await loadTrackedOrder();
        } catch (err) {
          paymentMessage.textContent = err.message || 'Could not verify payment. Please try again.';
          payButton.disabled = false;
        }
      },
      modal: {
        ondismiss: () => {
          payButton.disabled = false;
          paymentMessage.textContent = 'Payment was not completed.';
        },
      },
    });
    checkout.on('payment.failed', (event) => {
      payButton.disabled = false;
      paymentMessage.textContent = event.error?.description || 'Payment failed. Please try again.';
    });
    checkout.open();
  } catch (err) {
    payButton.disabled = false;
    paymentMessage.textContent = err.message || 'Could not start payment. Please try again.';
  }
}

async function confirmCakeQuote() {
  confirmQuoteButton.disabled = true;
  paymentMessage.textContent = 'Confirming your quote…';
  try {
    const response = await customerFetch('/api/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'confirm_cake_quote', order_number: ORDER_NUMBER }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      if (response.status === 401) {
        window.location.href = '/login';
        return;
      }
      throw new Error(data.error || 'Could not confirm the quote.');
    }
    paymentMessage.textContent = 'Quote confirmed.';
    await loadTrackedOrder();
  } catch (err) {
    paymentMessage.textContent = err.message || 'Could not confirm the quote. Please try again.';
    confirmQuoteButton.disabled = false;
  }
}

referenceImageButton.addEventListener('click', async () => {
  if (!referenceImagePreview.hidden) {
    referenceImagePreview.hidden = true;
    referenceImageButton.textContent = 'View your reference photo';
    return;
  }
  if (referenceImagePreview.firstChild) {
    referenceImagePreview.hidden = false;
    referenceImageButton.textContent = 'Hide reference photo';
    return;
  }
  referenceImageButton.disabled = true;
  try {
    const response = await fetch(
      `/api/orders/track/${encodeURIComponent(ORDER_NUMBER)}?include_reference_image=1`
    );
    const data = await response.json();
    const imageData = data.custom_cake_details?.reference_image;
    if (!response.ok || !imageData) {
      throw new Error(data.error || 'Could not load your reference photo.');
    }
    const image = document.createElement('img');
    image.src = imageData;
    image.alt = 'Your cake reference photo';
    image.width = 800;
    image.height = 600;
    image.loading = 'lazy';
    referenceImagePreview.replaceChildren(image);
    referenceImagePreview.hidden = false;
    referenceImageButton.textContent = 'Hide reference photo';
  } catch (error) {
    paymentMessage.textContent = error.message || 'Could not load your reference photo.';
  } finally {
    referenceImageButton.disabled = false;
  }
});

payButton.addEventListener('click', payOnline);
confirmQuoteButton.addEventListener('click', confirmCakeQuote);
loadTrackedOrder();