(function () {
  const notice = document.getElementById('cookie-notice');
  if (!notice) return;
  if (localStorage.getItem('surenCookieNoticeSeen') !== '1') notice.hidden = false;
  document.addEventListener('click', (event) => {
    if (!event.target.closest('[data-action="dismiss-cookies"]')) return;
    localStorage.setItem('surenCookieNoticeSeen', '1');
    notice.hidden = true;
  });
})();