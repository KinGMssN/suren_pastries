(() => {
  const form = document.getElementById('cake-request-form');
  if (!form) return;

  const addressSelect = document.getElementById('cake-address');
  const addressNote = document.getElementById('cake-address-note');
  const status = document.getElementById('cake-form-status');
  const submitButton = document.getElementById('cake-submit');
  const dateInput = document.getElementById('cake-date');
  const today = new Date();
  dateInput.min = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, '0'),
    String(today.getDate()).padStart(2, '0'),
  ].join('-');

  async function loadAddresses() {
    if (typeof getCustomer !== 'function' || !getCustomer()) {
      addressSelect.innerHTML = '<option value="">Log in to load saved addresses</option>';
      addressSelect.disabled = true;
      addressNote.innerHTML = 'You’ll need an account and a saved address. <a href="/login">Log in</a> or <a href="/signup">create an account</a>.';
      return;
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

  function idempotencyKey(payload) {
    const fingerprint = JSON.stringify(payload);
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
      design: form.elements.design.value,
      flavour: form.elements.flavour.value,
      size: form.elements.size.value,
      cake_message: form.elements.cake_message.value,
      required_date: form.elements.required_date.value,
      address_id: Number(form.elements.address_id.value),
      payment_method: form.elements.payment_method.value,
    };

    try {
      const response = await customerFetch('/api/checkout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey(payload),
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

  loadAddresses();
})();
