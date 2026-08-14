// Runs before admin.js. Since there's no server session render anymore,
// every admin page has to check auth itself via the API.
(async function guard() {
  try {
    const res = await fetch(window.API_BASE + '/api/auth/me', { credentials: 'include' });
    const data = await res.json();
    if (!data.authenticated) {
      window.location.href = 'login.html';
      return;
    }
    const nameEl = document.getElementById('sb-username');
    if (nameEl) nameEl.textContent = data.username;
  } catch (err) {
    window.location.href = 'login.html';
  }
})();

document.addEventListener('DOMContentLoaded', () => {
  const logoutLink = document.getElementById('logout-link');
  if (logoutLink) {
    logoutLink.addEventListener('click', async (e) => {
      e.preventDefault();
      try {
        await fetch(window.API_BASE + '/api/auth/logout', { method: 'POST', credentials: 'include' });
      } catch (err) { /* ignore, redirect anyway */ }
      window.location.href = 'login.html';
    });
  }
});
