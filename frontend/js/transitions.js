document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('a').forEach(a => {
    const h = a.getAttribute('href');
    if (h && h.endsWith('.html') && a.target !== '_blank') {
      a.addEventListener('click', e => {
        e.preventDefault();
        document.body.classList.add('fade-out');
        setTimeout(() => window.location.href = h, 250);
      });
    }
  });
});
window.addEventListener('pageshow', e => {
  if (e.persisted) document.body.classList.remove('fade-out');
});
