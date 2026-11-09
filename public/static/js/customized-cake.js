(() => {
  const form = document.getElementById('cake-request-form');
  if (!form) return;

  const addressSelect = document.getElementById('cake-address');
  const addressNote = document.getElementById('cake-address-note');
  const status = document.getElementById('cake-form-status');
  const submitButton = document.getElementById('cake-submit');
  const activeOrderNotice = document.getElementById('cake-active-order');
  const dateInput = document.getElementById('cake-date');
  const referenceImageInput = document.getElementById('cake-reference-image');
  const referenceImagePreview = document.getElementById('cake-reference-preview');
  const referenceImagePreviewImage = document.getElementById('cake-reference-preview-image');
  const referenceImageSelected = document.getElementById('cake-reference-selected');
  const removeReferenceImageButton = document.getElementById('cake-remove-photo');
  const maxReferenceImageBytes = 2 * 1024 * 1024;
  let referencePreviewUrl = null;
  const today = new Date();
  dateInput.min = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, '0'),
    String(today.getDate()).padStart(2, '0'),
  ].join('-');

  referenceImageInput.addEventListener('change', () => {
    const [file] = referenceImageInput.files;
    status.textContent = '';
    if (!file) {
      if (referencePreviewUrl) URL.revokeObjectURL(referencePreviewUrl);
      referencePreviewUrl = null;
      referenceImagePreview.hidden = true;
      referenceImagePreviewImage.removeAttribute('src');
      return;
    }
    if (referencePreviewUrl) URL.revokeObjectURL(referencePreviewUrl);
    referencePreviewUrl = null;
    referenceImagePreview.hidden = true;
    referenceImagePreviewImage.removeAttribute('src');
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      referenceImageInput.value = '';
      status.textContent = 'Choose a JPEG, PNG, or WebP cake photo.';
      return;
    }
    if (file.size > maxReferenceImageBytes) {
      referenceImageInput.value = '';
      status.textContent = 'The cake photo must be 2 MB or smaller.';
      return;
    }
    referencePreviewUrl = URL.createObjectURL(file);
    referenceImagePreviewImage.src = referencePreviewUrl;
    referenceImageSelected.checked = true;
    referenceImagePreview.hidden = false;
  });

  removeReferenceImageButton.addEventListener('click', () => {
    referenceImageInput.value = '';
    if (referencePreviewUrl) URL.revokeObjectURL(referencePreviewUrl);
    referencePreviewUrl = null;
    referenceImagePreviewImage.removeAttribute('src');
    referenceImagePreview.hidden = true;
    referenceImageSelected.checked = false;
  });

  async function loadActiveOrder() {
    if (typeof getCustomer !== 'function' || !getCustomer()) return false;
    try {
      const response = await customerFetch('/api/customer/active-order');
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Could not check your current orders.');
      }
      if (!data.active_order) return false;

      activeOrderNotice.hidden = false;
      activeOrderNotice.replaceChildren();
      const message = document.createElement('p');
      message.textContent = `Active order ${data.active_order.order_number}`;
      const link = document.createElement('a');
      link.className = 'cake-button';
      link.href = '/track/' + encodeURIComponent(data.active_order.order_number);
      link.textContent = 'Track order';
      activeOrderNotice.append(message, link);
      form.hidden = true;
      return true;
    } catch (error) {
      activeOrderNotice.hidden = false;
      activeOrderNotice.textContent =
        error.message || 'Could not check your current orders. Please try again.';
      form.hidden = true;
      return true;
    }
  }

  async function loadAddresses() {
    if (typeof getCustomer !== 'function' || !getCustomer()) {
      addressSelect.innerHTML = '<option value="">Log in to continue</option>';
      addressSelect.disabled = true;
      addressNote.innerHTML = '<a href="/login">Log in</a> or <a href="/signup">create an account</a>.';
      return;
    }

    try {
      const response = await customerFetch('/api/customer/addresses');
      const addresses = await response.json();
      if (!response.ok) throw new Error(addresses.error || 'Could not load saved addresses.');
      if (!addresses.length) {
        addressSelect.innerHTML = '<option value="">No saved addresses</option>';
        addressSelect.disabled = true;
        addressNote.innerHTML = '<a href="/account">Add an address</a>';
        return;
      }

      addressSelect.innerHTML = '<option value="">Choose a delivery address</option>' +
        addresses.map(address => {
          const option = document.createElement('option');
          option.value = address.id;
          option.textContent = `${address.label} — ${address.address_line}${address.city ? `, ${address.city}` : ''}`;
          return option.outerHTML;
        }).join('');
      addressSelect.disabled = false;
      addressNote.textContent = '';
    } catch (error) {
      addressSelect.innerHTML = '<option value="">Could not load addresses</option>';
      addressSelect.disabled = true;
      status.textContent = error.message || 'Could not load saved addresses.';
    }
  }

  async function idempotencyKey(payload) {
    const fingerprintPayload = { ...payload };
    if (fingerprintPayload.reference_image) {
      const digest = await crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(fingerprintPayload.reference_image),
      );
      fingerprintPayload.reference_image_hash = Array.from(new Uint8Array(digest))
        .map(byte => byte.toString(16).padStart(2, '0')).join('');
      delete fingerprintPayload.reference_image;
    }
    const fingerprint = JSON.stringify(fingerprintPayload);
    let saved;
    try {
      saved = JSON.parse(sessionStorage.getItem('surenCakeRequest') || 'null');
    } catch (error) {
      sessionStorage.removeItem('surenCakeRequest');
    }
    if (saved?.fingerprint === fingerprint) return saved.key;
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    const key = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    sessionStorage.setItem('surenCakeRequest', JSON.stringify({ fingerprint, key }));
    return key;
  }

  function readReferenceImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener('load', () => resolve(reader.result));
      reader.addEventListener('error', () => reject(new Error('Could not read the selected photo.')));
      reader.readAsDataURL(file);
    });
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    status.textContent = '';
    if (typeof getCustomer !== 'function' || !getCustomer()) {
      status.textContent = 'Please log in to send a cake request.';
      return;
    }
    if (!form.reportValidity()) return;

    submitButton.disabled = true;
    submitButton.textContent = 'Sending request…';
    const occasionEl = document.getElementById('cake-occasion');
    const occasionValue = occasionEl ? occasionEl.value : '';
    const descriptionValue = occasionValue ? 'Occasion: ' + occasionValue + '\n' + form.elements.description.value : form.elements.description.value;
    const payload = {
      action: 'custom_cake_request',
      description: descriptionValue,
      required_date: form.elements.required_date.value,
      address_id: Number(form.elements.address_id.value),
      payment_method: form.elements.payment_method.value,
    };

    try {
      const [referenceImage] = referenceImageInput.files;
      if (referenceImage && referenceImageSelected.checked) {
        payload.reference_image = await readReferenceImage(referenceImage);
      }
      const response = await customerFetch('/api/checkout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': await idempotencyKey(payload),
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        if (response.status === 401) {
          window.location.href = '/login';
          return;
        }
        throw new Error(data.error || 'Could not send your cake request.');
      }
      sessionStorage.removeItem('surenCakeRequest');
      window.location.href = `/track/${encodeURIComponent(data.order_number)}`;
    } catch (error) {
      status.textContent = error.message || 'Could not reach the bakery. Please try again.';
      submitButton.disabled = false;
      submitButton.innerHTML = 'Send cake request <span aria-hidden="true">→</span>';
    }
  });

  loadActiveOrder().then(hasActiveOrder => {
    if (!hasActiveOrder) loadAddresses();
  });
})();

/* ── THREE WAYS TO ORDER: tabs + Design Your Cake + Cakes Menu ──
   Frontend only. No backend change. Design Your Cake fills the existing
   WhatsApp Order form, which sends it through the existing flow. */
(() => {
  const notes = {
    whatsapp: 'Send a photo of the cake you want. We accept it on WhatsApp and deliver it.',
    diy: 'Build it yourself, step by step — occasion first, then size, flavour, colour, toppings and the name on top.',
    cakes: 'Ready-made cakes, 1 kg each. Tap + Add and they go straight into your cart.',
  };
  const tabs = Array.from(document.querySelectorAll('[data-cake-tab]'));
  const note = document.getElementById('cake-tab-note');
  function showTab(name, pushHash) {
    tabs.forEach(t => {
      const on = t.dataset.cakeTab === name;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    ['whatsapp', 'diy', 'cakes'].forEach(n => {
      const panel = document.getElementById('cake-panel-' + n);
      if (!panel) return;
      panel.hidden = n !== name;
      panel.classList.toggle('active', n === name);
    });
    if (note) note.textContent = notes[name] || '';
    if (pushHash) history.replaceState(null, '', '#' + name);
  }
  tabs.forEach(t => t.addEventListener('click', () => showTab(t.dataset.cakeTab, true)));
  const start = (location.hash || '').replace('#', '');
  if (['whatsapp', 'diy', 'cakes'].includes(start)) showTab(start, false);

  /* Design Your Cake: live preview + summary, then fill WhatsApp form */
  const diyForm = document.getElementById('cake-diy-form');
  if (diyForm) {
    const summary = document.getElementById('cake-diy-summary');
    const customColour = document.getElementById('cake-diy-custom-colour');
    const pick = name => {
      const el = diyForm.querySelector(`input[name="${name}"]:checked`);
      return el ? el.value : '';
    };
    const occasion = () => {
      const o = pick('diy_occasion');
      if (o === 'Other') {
        const other = (document.getElementById('cake-diy-occasion-other').value || '').trim();
        return other || 'Other occasion';
      }
      return o;
    };
    function update() {
      const colour = pick('diy_colour');
      const shape = pick('diy_shape');
      const size = pick('diy_size');
      const occ = occasion();
      const name = (document.getElementById('cake-diy-name').value || '').trim();
      const toppings = Array.from(diyForm.querySelectorAll('input[name="diy_topping"]:checked')).map(i => i.value);
      if (summary) {
        summary.textContent = 'Your design: ' + [occ + ' cake', colour, shape, size, toppings.length ? 'Toppings: ' + toppings.join(', ') : 'No toppings yet', name ? 'Name on cake: "' + name + '"' : ''].filter(Boolean).join(' — ') + '.';
      }
    }
    diyForm.addEventListener('input', update);
    diyForm.addEventListener('change', update);
    update();
    diyForm.addEventListener('submit', e => {
      e.preventDefault();
      if (!diyForm.reportValidity()) return;
      const colour = customColour && document.activeElement === customColour ? 'Custom colour ' + customColour.value : pick('diy_colour');
      const toppings = Array.from(diyForm.querySelectorAll('input[name="diy_topping"]:checked')).map(i => i.value);
      const flavour = document.getElementById('cake-diy-flavour').value;
      const name = (document.getElementById('cake-diy-name').value || '').trim();
      const message = (document.getElementById('cake-diy-message').value || '').trim();
      const allergies = (document.getElementById('cake-diy-allergies').value || '').trim();
      const budget = document.getElementById('cake-diy-budget').value;
      const special = (document.getElementById('cake-diy-special').value || '').trim();
      const lines = [
        'Design Your Cake',
        'Occasion: ' + occasion(),
        'Size: ' + pick('diy_size'),
        'Flavour: ' + (flavour || 'No preference'),
        'Colour: ' + colour,
        'Shape: ' + pick('diy_shape'),
        'Toppings: ' + (toppings.length ? toppings.join(', ') : 'None'),
        name ? 'Name on cake: "' + name + '"' : null,
        message ? 'Message on cake: "' + message + '"' : null,
        'Eggless: ' + pick('diy_eggless'),
        allergies ? 'Allergies: ' + allergies : null,
        budget ? 'Budget: ' + budget : null,
        'Delivery: ' + pick('diy_delivery'),
        special ? 'Special: ' + special : null,
      ].filter(Boolean);
      const desc = document.getElementById('cake-description');
      if (desc) desc.value = lines.join('\n');
      showTab('whatsapp', true);
      const status = document.getElementById('cake-form-status');
      if (status) status.textContent = 'Your design is filled in above — pick a date, address and payment, then send it.';
      document.getElementById('cake-request').scrollIntoView({ behavior: 'smooth' });
      const dateInput = document.getElementById('cake-date');
      if (dateInput) dateInput.focus({ preventScroll: true });
    });
  }

  /* Cakes Menu: same localStorage cart as the Menu page, no backend */
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-action="add-cake"]');
    if (!el) return;
    const id = parseInt(el.dataset.id, 10);
    const name = el.dataset.name;
    const price = parseFloat(el.dataset.price);
    const emoji = el.dataset.emoji || '🍰';
    let cart = [];
    try { cart = JSON.parse(localStorage.getItem('surenPastriesCart')) || []; } catch (err) { cart = []; }
    const existing = cart.find(i => i.id === id);
    if (existing) existing.qty++;
    else cart.push({ id, name, price, qty: 1, emoji });
    localStorage.setItem('surenPastriesCart', JSON.stringify(cart));
    localStorage.setItem('cartCount', cart.reduce((s, i) => s + i.qty, 0));
    const old = el.textContent;
    el.textContent = '✓ Added';
    el.style.background = '#4CAF50';
    setTimeout(() => { el.textContent = old; el.style.background = ''; }, 2000);
    if (typeof updateFC === 'function') updateFC();
  });
})();
