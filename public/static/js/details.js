if (typeof updateFC === 'function') updateFC();

function escapeHTML(value) {
  const entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(value ?? '').replace(/[&<>"']/g, char => entities[char]);
}

async function loadTeam() {
  const grid = document.getElementById('team-grid');
  if (!grid) return;
  try {
    const res = await fetch('/api/team');
    if (!res.ok) throw new Error(`Team request failed (${res.status})`);
    const team = await res.json();
    if (!Array.isArray(team)) throw new Error('Invalid team response');
    if (!team.length) {
      grid.textContent = 'Team profiles will be shared soon.';
      return;
    }
    grid.innerHTML = team.map(m => {
      const photo = typeof m.photo === 'string'
        && /^data:image\/(?:png|jpe?g);base64,[A-Za-z0-9+/]+={0,2}$/.test(m.photo)
        ? m.photo
        : '';
      return `
        <div class="team-card">
          <div class="team-avatar" ${photo ? 'style="padding:0;overflow:hidden;background:none"' : ''}>${photo ? `<img src="${escapeHTML(photo)}" width="96" height="96" loading="lazy" alt="${escapeHTML(m.name)}" style="width:100%;height:100%;object-fit:cover;border-radius:50%"/>` : escapeHTML(m.avatar || '👤')}</div>
          <div class="team-name">${escapeHTML(m.name)}</div>
          <div class="team-role">${escapeHTML(m.role)}</div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.error('Unable to load public team profiles.', err);
    grid.textContent = 'Team profiles could not be loaded. Please try again later.';
  }
}
loadTeam();
