(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const kinds = {textbook: 'Учебник', workbook: 'Задачник', other: 'Другой материал'};
  const cookie = () => decodeURIComponent(document.cookie.split('; ').find(part => part.startsWith('csrftoken='))?.split('=')[1] || '');

  window.MaterialsViewer = {
    open(url, title, page = 1, pageCount = 1) {
      const target = new URL(url, location.origin);
      if (target.origin !== location.origin || !/^\/api\/materials\/[0-9a-f-]+\/file$/.test(target.pathname)) return;
      let dialog = document.querySelector('#material-viewer');
      if (!dialog) {
        dialog = document.createElement('dialog');
        dialog.id = 'material-viewer';
        dialog.className = 'material-viewer';
        dialog.innerHTML = '<div class="material-viewer-head"><h2></h2><div><a class="button button-soft" download>↓ Скачать</a><button class="icon-button" type="button" aria-label="Закрыть PDF">×</button></div></div><div class="material-viewer-controls"><button type="button" data-page-step="-1" aria-label="Предыдущая страница">‹</button><label>Страница <input type="number" min="1" aria-label="Номер страницы"></label><span data-page-count></span><button type="button" data-page-step="1" aria-label="Следующая страница">›</button></div><div class="material-viewer-body"><img alt="Страница PDF"></div>';
        dialog.querySelector('.material-viewer-head button').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => { dialog.querySelector('img').removeAttribute('src'); });
        dialog.querySelectorAll('[data-page-step]').forEach(button => button.addEventListener('click', () => {
          dialog.setPage(Number(dialog.dataset.page) + Number(button.dataset.pageStep));
        }));
        dialog.querySelector('input').addEventListener('change', event => dialog.setPage(Number(event.target.value)));
        dialog.setPage = value => {
          const total = Number(dialog.dataset.total);
          const next = Math.max(1, Math.min(total, Number.isFinite(value) ? Math.round(value) : 1));
          dialog.dataset.page = String(next);
          dialog.querySelector('input').value = String(next);
          dialog.querySelector('[data-page-count]').textContent = `из ${total}`;
          dialog.querySelector('[data-page-step="-1"]').disabled = next === 1;
          dialog.querySelector('[data-page-step="1"]').disabled = next === total;
          dialog.querySelector('img').src = dialog.dataset.path.replace(/\/file$/, `/page/${next}.png`);
          dialog.querySelector('.material-viewer-body').scrollTop = 0;
        };
        document.body.append(dialog);
      }
      dialog.querySelector('h2').textContent = title;
      dialog.querySelector('a').href = target.pathname;
      dialog.dataset.path = target.pathname;
      dialog.dataset.total = String(Math.max(1, Number(pageCount) || 1));
      dialog.setPage(Number(page) || 1);
      if (!dialog.open) dialog.showModal();
    },
  };

  window.MaterialsPanel = {
    attach(root, ownerType) {
      let ownerId = null;
      let serial = 0;
      const key = ownerType === 'student' ? 'student_id' : 'class_id';
      const panel = () => root.querySelector('[data-materials-panel]');

      function draw(items) {
        const target = panel();
        if (!target) return;
        target.innerHTML = `<div class="materials-head"><div><h3>Материалы</h3><p>PDF учебников, задачников и других источников для работы с помощником.</p></div><span class="count-pill">${items.length}</span></div>
          <div class="materials-list">${items.length ? items.map(item => `<article class="material-card"><span class="material-icon" aria-hidden="true">▤</span><div class="material-info"><button type="button" class="material-open" data-material-open="${esc(item.url)}" data-material-title="${esc(item.title)}" data-page-count="${item.page_count}">${esc(item.title)}</button><small>${esc(kinds[item.kind])} · ${item.page_count} стр. · ${item.text_page_count ? `текст на ${item.text_page_count} стр.` : 'скан без текста'}</small></div><button type="button" class="text-button danger-text" data-material-delete="${esc(item.id)}" aria-label="Удалить ${esc(item.title)}">Удалить</button></article>`).join('') : '<p class="section-empty">Пока нет материалов.</p>'}</div>
          <form class="material-upload" data-material-form><div class="material-form-grid"><label class="field"><span>Название</span><input name="title" maxlength="160" required placeholder="Например, Алгебра 8 класс"></label><label class="field"><span>Тип</span><select name="kind"><option value="textbook">Учебник</option><option value="workbook">Задачник</option><option value="other">Другой материал</option></select></label></div><label class="field"><span>PDF · до 30 МБ</span><input name="file" type="file" accept=".pdf,application/pdf" required></label><div class="material-upload-actions"><button type="submit" class="button button-soft">↑ Загрузить PDF</button><span data-material-status role="status"></span></div></form>`;
      }

      async function load(id) {
        ownerId = id;
        const current = ++serial;
        if (!id || !panel()) return;
        panel().innerHTML = '<div class="section-empty">Загружаю материалы…</div>';
        try {
          const response = await fetch(`/api/materials/?${key}=${encodeURIComponent(id)}`);
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Не удалось загрузить материалы');
          if (current === serial && ownerId === id) draw(data);
        } catch (error) {
          if (current === serial && panel()) panel().textContent = error.message;
        }
      }

      root.addEventListener('submit', async event => {
        const form = event.target.closest('[data-material-form]');
        if (!form) return;
        event.preventDefault();
        const id = ownerId;
        const status = form.querySelector('[data-material-status]');
        const button = form.querySelector('[type="submit"]');
        button.disabled = true;
        status.textContent = 'Обрабатываю PDF…';
        try {
          const data = new FormData(form);
          data.append(key, id);
          const response = await fetch('/api/materials/', {method: 'POST', headers: {'X-CSRFToken': cookie()}, body: data});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Не удалось загрузить PDF');
          if (ownerId === id) await load(id);
        } catch (error) { status.textContent = error.message; button.disabled = false; }
      });

      root.addEventListener('click', async event => {
        const opener = event.target.closest('[data-material-open]');
        if (opener) {
          window.MaterialsViewer.open(opener.dataset.materialOpen, opener.dataset.materialTitle, 1, opener.dataset.pageCount);
          return;
        }
        const button = event.target.closest('[data-material-delete]');
        if (!button) return;
        if (!window.confirm('Удалить этот PDF из карточки?')) return;
        const id = ownerId;
        button.disabled = true;
        try {
          const response = await fetch(`/api/materials/${button.dataset.materialDelete}`, {method: 'DELETE', headers: {'X-CSRFToken': cookie()}});
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Не удалось удалить материал');
          if (ownerId === id) await load(id);
        } catch (error) { alert(error.message); button.disabled = false; }
      });
      return load;
    },
  };
})();
