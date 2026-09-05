// Shared "add to cart" logic used on the landing page and the menu page.
// Cart is kept in localStorage so it persists across pages without a login.

function addCart(el, id, name, price, emoji) {
  let cart = JSON.parse(localStorage.getItem('surenPastriesCart')) || [];
  let existing = cart.find(i => i.id === id);
  if (existing) { existing.qty++; }
  else { cart.push({ id: id, name: name, price: price, qty: 1, emoji: emoji }); }
  localStorage.setItem('surenPastriesCart', JSON.stringify(cart));

  let cartCount = cart.reduce((s, i) => s + i.qty, 0);
  localStorage.setItem('cartCount', cartCount);
  const cc = document.getElementById('ccount');
  if (cc) cc.textContent = cartCount;

  if (el) {
    const btn = el;
    const oldText = btn.textContent;
    btn.textContent = '✓ Added';
    btn.style.background = '#4CAF50';
    btn.style.borderColor = '#4CAF50';
    btn.style.color = '#fff';
    setTimeout(() => {
      btn.textContent = oldText;
      btn.style.background = '';
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 2000);
  }
  if (typeof updateFC === 'function') updateFC();
}

function updateFC() {
  let c = parseInt(localStorage.getItem('cartCount') || 0);
  const fc = document.getElementById('nav-cart'), fb = document.getElementById('ccount');
  if (fc && fb) {
    if (c > 0) { fc.style.display = 'flex'; fb.textContent = c; }
    else { fc.style.display = 'none'; }
  }
}

// base64-encode small objects for safe embedding in data-* attributes
function encodeObj(obj) {
  return btoa(encodeURIComponent(JSON.stringify(obj)));
}
function decodeObj(str) {
  return JSON.parse(decodeURIComponent(atob(str)));
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action="add-cart"]');
  if (!el) return;
  addCart(el, parseInt(el.dataset.id, 10), el.dataset.name, parseFloat(el.dataset.price), el.dataset.emoji);
});