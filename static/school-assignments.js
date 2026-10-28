(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const root = document.querySelector('#school-worksheet-list');
  const cookie = () => decodeURIComponent(document.cookie.split('; ').find(part => part.startsWith('csrftoken='))?.split('=')[1] || '');
  async function load() {
    try {
      const target = new URLSearchParams(location.search).get('class');
      const response = await fetch(`/api/school/worksheets${target ? `?class_id=${encodeURIComponent(target)}` : ''}`);
      const items = await response.json();
      if (!response.ok) throw new Error(items.error || 'Не удалось загрузить подборки');
      root.innerHTML = items.length ? items.map(item => `<article class="school-worksheet-card"><div><strong>${esc(item.title)}</strong><small>${esc(item.class_name)} · ${item.kind === 'homework' ? 'Домашняя работа' : 'На уроке'} · ${item.item_count} задач</small></div><div><a class="button button-soft" href="/api/school/worksheets/${esc(item.id)}/pdf">↓ PDF</a><a class="button button-soft" href="/api/school/worksheets/${esc(item.id)}/pdf?solutions=1">↓ С решениями</a><button class="text-button danger-text" type="button" data-delete="${esc(item.id)}">Удалить</button></div></article>`).join('') : '<p class="section-empty">Подборок пока нет. Создайте задачи ниже и сохраните их для урока или домашней работы.</p>';
    } catch (error) { root.textContent = error.message; }
  }
  root.addEventListener('click', async event => {
    const button = event.target.closest('[data-delete]');
    if (!button || !confirm('Удалить подборку класса? Задачи в библиотеке останутся.')) return;
    try {
      const response = await fetch(`/api/school/worksheets/${button.dataset.delete}`, {method: 'DELETE', headers: {'X-CSRFToken': cookie()}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Не удалось удалить подборку');
      load();
    } catch (error) { alert(error.message); }
  });
  document.querySelector('#generator-section').hidden = false;
  window.addEventListener('school:worksheets-changed', load);
  load();
})();
