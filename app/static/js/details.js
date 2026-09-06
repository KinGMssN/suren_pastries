if (typeof updateFC === 'function') updateFC();

async function loadTeam() {
  const grid = document.getElementById('team-grid');
  try {
    const res = await fetch('/api/team');
    const team = await res.json();
    if (!team.length) return;
    grid.innerHTML = team.map(m => `
      <div class="team-card">
        <div class="team-avatar" ${m.photo ? 'style="padding:0;overflow:hidden;background:none"' : ''}>${m.photo ? `<img src="${m.photo}" alt="${m.name}" style="width:100%;height:100%;object-fit:cover;border-radius:50%"/>` : m.avatar}</div>
        <div class="team-name">${m.name}</div>
        <div class="team-role">${m.role || ''}</div>
      </div>
    `).join('');
  } catch (err) { /* keep fallback empty grid */ }
}
loadTeam();
