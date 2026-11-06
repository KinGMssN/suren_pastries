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

  async function loadAddresses() {
    if (typeof getCustomer !== 'function' || !getCustomer()) {
      addressSelect.innerHTML = '<option value="">Log in to load saved addresses</option>';
      addressSelect.disabled = true;
      addressNote.innerHTML = 'You’ll need an account and a saved address. <a href="/login">Log in</a> or <a href="/signup">create an account</a>.';
      return;
    }

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
        message.textContent =
          `You already have an active order (${data.active_order.order_number}). ` +
          'You can send another cake request after it is delivered or rejected.';
        const link = document.createElement('a');
        link.className = 'cake-button';
        link.href = '/track/' + encodeURIComponent(data.active_order.order_number);
        link.textContent = 'Track current order';
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

    try {
      const response = await customerFetch('/api/customer/addresses');
      const addresses = await response.json();
      if (!response.ok) throw new Error(addresses.error || 'Could not load saved addresses.');
      if (!addresses.length) {
        addressSelect.innerHTML = '<option value="">No saved addresses</option>';
        addressSelect.disabled = true;
        addressNote.innerHTML = 'Add a delivery address in <a href="/account">your account</a> before requesting a cake.';
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
      addressNote.textContent = 'Your request will be sent to this saved address.';
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
    const payload = {
      action: 'custom_cake_request',
      description: form.elements.description.value,
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
