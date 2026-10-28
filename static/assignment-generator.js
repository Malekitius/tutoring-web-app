(() => {
const $ = selector => document.querySelector(selector);
const schoolMode = document.body.dataset.mode === 'school';
const state = {drafts: [], targetId: null, meta: null, pendingGeneration: null, generating: false};
const difficultyNames = {1: 'Базовая', 2: 'Средняя', 3: 'Повышенная', 4: 'Олимпиадная'};

function esc(value = '') { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])); }
function cookie(name) { return document.cookie.split('; ').find(part => part.startsWith(`${name}=`))?.split('=')[1] || ''; }
function showError(selector, message) { const el = $(selector); el.textContent = message || ''; el.hidden = !message; }
async function api(path, method = 'GET', payload) {
  const options = {method, headers: {'Accept': 'application/json'}};
  if (payload !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('Сервер вернул некорректный ответ'); }
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}
function busy(form, value) { form.querySelector('button[type="submit"]').disabled = value; }
function targetSelect() { return $('#generate-form').elements[schoolMode ? 'class_id' : 'student_id']; }
function selectedMaterials() {
  return [...document.querySelectorAll('#generator-material-list [data-material-row]')]
    .filter(row => row.querySelector('input[type="checkbox"]').checked)
    .map(row => ({id: row.dataset.materialRow, pages: row.querySelector('input[type="text"]').value.trim()}));
}
async function loadMaterials() {
  const id = targetSelect().value;
  const list = $('#generator-material-list');
  list.textContent = 'Загружаю материалы…';
  if (!id) { list.textContent = 'Сначала выберите карточку.'; return; }
  try {
    const items = await api(`/api/materials/?${schoolMode ? 'class_id' : 'student_id'}=${encodeURIComponent(id)}`);
    if (targetSelect().value !== id) return;
    list.innerHTML = items.length ? items.map(item => `<div class="generator-material-row" data-material-row="${esc(item.id)}"><input type="checkbox" aria-label="Выбрать ${esc(item.title)}"><span><button class="generator-material-open" type="button" data-material-open="${esc(item.url)}" data-material-title="${esc(item.title)}" data-page-count="${item.page_count}">▤ ${esc(item.title)} · открыть PDF</button><small>${item.page_count} стр. · ${item.text_page_count ? 'текст найден' : 'скан'}</small></span><input type="text" aria-label="Страницы материала ${esc(item.title)}" placeholder="Страницы" maxlength="100"></div>`).join('') : `<p>Материалов пока нет. Загрузите PDF в карточку ${schoolMode ? 'класса' : 'ученика'}.</p>`;
  } catch (error) { list.textContent = error.message; }
}
$('#generator-material-list').addEventListener('click', event => {
  const button = event.target.closest('[data-material-open]');
  const row = event.target.closest('[data-material-row]');
  if (!row) return;
  if (button) {
    const firstPage = /^\s*(\d+)/.exec(row.querySelector('input[type="text"]').value)?.[1] || 1;
    window.MaterialsViewer.open(button.dataset.materialOpen, button.dataset.materialTitle, firstPage, button.dataset.pageCount);
  } else if (!event.target.closest('input')) {
    const checkbox = row.querySelector('input[type="checkbox"]');
    checkbox.checked = !checkbox.checked;
    row.classList.toggle('selected', checkbox.checked);
  }
});
$('#generator-material-list').addEventListener('change', event => {
  if (event.target.type === 'checkbox') event.target.closest('[data-material-row]').classList.toggle('selected', event.target.checked);
});

function syncMode() {
  const source = $('#generate-form').elements.mode.value === 'source';
  document.querySelector('.generator-mode').dataset.mode = source ? 'source' : 'generated';
  document.querySelectorAll('[data-generated-only]').forEach(group => {
    group.hidden = source;
    group.querySelectorAll('input,textarea,select').forEach(input => { input.disabled = source; });
  });
  document.querySelectorAll('[data-source-only]').forEach(group => {
    group.hidden = !source;
    group.querySelectorAll('input,textarea,select').forEach(input => { input.disabled = !source; });
  });
  $('#generate-form button[type="submit"]').textContent = source ? 'Перенести задачи в черновик' : 'Создать черновик';
  showError('#generate-error', '');
}
$('#generate-form').addEventListener('change', event => { if (event.target.name === 'mode') syncMode(); });
function renderMath(root) {
  if (typeof window.renderMathInElement === 'function') window.renderMathInElement(root, {
    delimiters: [
      {left: '$$', right: '$$', display: true},
      {left: '\\[', right: '\\]', display: true},
      {left: '\\(', right: '\\)', display: false},
      {left: '$', right: '$', display: false},
    ], throwOnError: false, trust: false, strict: 'ignore'
  });
}

function renderDrafts() {
  const root = $('#draft-list');
  root.innerHTML = state.drafts.map((item, index) => `<article class="assistant-draft" data-index="${index}">
    <div class="assistant-draft-head"><strong>Задача ${index + 1} · ${esc(difficultyNames[item.difficulty])}</strong><button class="text-button" type="button" data-remove="${index}">Убрать</button></div>
    ${item.source_refs?.length ? `<p class="draft-source">Материалы: ${item.source_refs.map(ref => `${esc(ref.title)} · стр. ${ref.pages.join(', ')}`).join('; ')}</p>` : ''}
    <label class="field"><span>Название</span><input name="title" value="${esc(item.title)}" maxlength="160" required></label>
    <div class="assistant-draft-rendered" data-part="prompt">
      <div class="assistant-draft-part-head"><span>Условие</span><button class="text-button" type="button" data-edit="prompt">Изменить условие</button></div>
      <div class="assistant-draft-preview" data-preview="prompt">${esc(item.prompt)}</div>
      <div class="assistant-draft-editor" hidden><label class="field"><span>LaTeX-код условия</span><textarea name="prompt" maxlength="10000" required>${esc(item.prompt)}</textarea></label><div class="assistant-draft-actions"><button class="button button-primary" type="button" data-save-edit="prompt">Сохранить</button><button class="button button-secondary" type="button" data-cancel-edit="prompt">Отмена</button></div></div>
    </div>
    <div class="assistant-draft-rendered" data-part="answer">
      <div class="assistant-draft-part-head"><span>Решение и ответ</span><button class="text-button" type="button" data-edit="answer">Изменить решение</button></div>
      <div class="assistant-draft-preview" data-preview="answer">${esc(item.answer)}</div>
      <div class="assistant-draft-editor" hidden><label class="field"><span>LaTeX-код решения</span><textarea name="answer" maxlength="10000">${esc(item.answer)}</textarea></label><div class="assistant-draft-actions"><button class="button button-primary" type="button" data-save-edit="answer">Сохранить</button><button class="button button-secondary" type="button" data-cancel-edit="answer">Отмена</button></div></div>
    </div>
  </article>`).join('');
  root.querySelectorAll('.assistant-draft-preview').forEach(renderMath);
  $('#draft-section').hidden = !state.drafts.length && !state.pendingGeneration;
  syncEditState();
}

$('#draft-list').addEventListener('input', event => {
  const article = event.target.closest('.assistant-draft');
  if (!article || event.target.name !== 'title') return;
  const index = Number(article.dataset.index);
  state.drafts[index].title = event.target.value;
});

function syncEditState() {
  const editing = Boolean($('#draft-list .assistant-draft-editor:not([hidden])'));
  $('#accept-form button[type="submit"]').disabled = editing || state.generating;
  $('#draft-edit-hint').hidden = !editing;
}

function closeEditor(part) {
  part.querySelector('.assistant-draft-editor').hidden = true;
  part.querySelector('.assistant-draft-preview').hidden = false;
  part.querySelector('[data-edit]').hidden = false;
  syncEditState();
}

$('#draft-list').addEventListener('click', event => {
  const button = event.target.closest('[data-remove]');
  if (button) {
    state.drafts.splice(Number(button.dataset.remove), 1);
    renderDrafts();
    return;
  }
  const edit = event.target.closest('[data-edit]');
  const save = event.target.closest('[data-save-edit]');
  const cancel = event.target.closest('[data-cancel-edit]');
  const action = edit || save || cancel;
  if (!action) return;
  const part = action.closest('.assistant-draft-rendered');
  const article = action.closest('.assistant-draft');
  const field = part.dataset.part;
  const textarea = part.querySelector('textarea');
  if (edit) {
    textarea.value = state.drafts[Number(article.dataset.index)][field];
    part.querySelector('.assistant-draft-preview').hidden = true;
    edit.hidden = true;
    part.querySelector('.assistant-draft-editor').hidden = false;
    syncEditState();
    textarea.focus();
  } else if (save) {
    if (field === 'prompt' && !textarea.value.trim()) {
      textarea.setCustomValidity('Введите условие задачи.');
      textarea.reportValidity();
      return;
    }
    textarea.setCustomValidity('');
    const value = textarea.value;
    state.drafts[Number(article.dataset.index)][field] = value;
    const preview = part.querySelector('.assistant-draft-preview');
    preview.textContent = value;
    renderMath(preview);
    closeEditor(part);
  } else {
    textarea.setCustomValidity('');
    textarea.value = state.drafts[Number(article.dataset.index)][field];
    closeEditor(part);
  }
});

$('#draft-list').addEventListener('input', event => {
  if (event.target.name === 'prompt') event.target.setCustomValidity('');
});

function difficultyCounts(form) {
  return Object.fromEntries([1, 2, 3, 4].map(level => [String(level), Number(form.elements[`count_${level}`].value)]));
}

function updateTotal() {
  const total = Object.values(difficultyCounts($('#generate-form'))).reduce((sum, count) => sum + count, 0);
  $('#generator-total').textContent = `Всего: ${total} ${total === 1 ? 'задача' : total >= 2 && total <= 4 ? 'задачи' : 'задач'}`;
}
$('#generate-form').addEventListener('input', event => { if (event.target.name?.startsWith('count_')) updateTotal(); });

async function runGeneration() {
  const form = $('#generate-form');
  const pending = state.pendingGeneration;
  if (!pending || state.generating) return;
  if (form.elements.mode.value !== pending.payload.mode) {
    showError('#draft-generation-error', 'Верните прежний режим или начните новый черновик.');
    return;
  }
  if (targetSelect().value !== state.targetId) {
    showError('#draft-generation-error', 'Верните исходную карточку или начните новый черновик.');
    return;
  }
  if (pending.payload.mode === 'source') {
    const materials = selectedMaterials();
    if (!materials.length || materials.some(item => !item.pages)) {
      showError('#draft-generation-error', 'Выберите PDF и укажите страницы, затем продолжите.');
      return;
    }
    pending.payload.materials = materials;
    pending.payload.source_task_hint = form.elements.source_task_hint.value;
  }
  state.generating = true;
  busy(form, true);
  form.querySelectorAll('input[name="mode"]').forEach(input => { input.disabled = true; });
  form.setAttribute('aria-busy', 'true');
  $('#generate-loading').hidden = false;
  $('#draft-progress').hidden = false;
  $('#generate-resume').hidden = true;
  showError('#generate-error', '');
  showError('#draft-generation-error', '');
  $('#draft-list').inert = true;
  syncEditState();
  renderDrafts();
  $('#draft-section').scrollIntoView({behavior: 'smooth', block: 'start'});
  try {
    while (pending.nextIndex < pending.plan.length) {
      const level = pending.plan[pending.nextIndex];
      const progress = pending.payload.mode === 'source'
        ? `Переношу задачу ${pending.nextIndex + 1} из ${pending.plan.length}`
        : `Создаю задачу ${pending.nextIndex + 1} из ${pending.plan.length} · ${difficultyNames[level].toLowerCase()}`;
      $('#generate-loading-text').textContent = progress;
      $('#draft-progress-text').textContent = progress;
      const result = await api('/api/assistant/generate', 'POST', {
        ...pending.payload, ...(pending.payload.mode === 'generated' ? {difficulty: level} : {}),
        count: 1, source_index: pending.nextIndex + 1,
        existing_tasks: state.drafts.map(item => item.prompt.slice(0, 500)),
      });
      if (!Array.isArray(result.exercises) || result.exercises.length !== 1 || result[schoolMode ? 'class_id' : 'student_id'] !== state.targetId) {
        throw new Error('Сервер вернул неверное количество задач.');
      }
      state.drafts.push({...result.exercises[0], source_refs: result.source_refs || []});
      pending.nextIndex++;
      $('#accept-form').hidden = false;
      renderDrafts();
    }
    state.pendingGeneration = null;
    $('#draft-heading').textContent = `Черновик задач · ${state.drafts.length}`;
  } catch (error) {
    const message = `Создано ${pending.nextIndex} из ${pending.plan.length}. ${error.message}`;
    showError('#draft-generation-error', message);
    $('#generate-resume').hidden = false;
  } finally {
    $('#generate-loading').hidden = true;
    $('#draft-progress').hidden = true;
    $('#draft-list').inert = false;
    form.removeAttribute('aria-busy');
    state.generating = false;
    form.querySelectorAll('input[name="mode"]').forEach(input => { input.disabled = false; });
    busy(form, false);
    syncEditState();
  }
}

$('#generate-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const source = form.elements.mode.value === 'source';
  const counts = source ? null : difficultyCounts(form);
  const total = source ? Number(form.elements.source_count.value) : Object.values(counts).reduce((sum, count) => sum + count, 0);
  if (!Number.isInteger(total) || total < 1 || total > 20 || (counts && !Object.values(counts).every(Number.isInteger))) {
    showError('#generate-error', 'Выберите от 1 до 20 задач.'); return;
  }
  const materials = source ? selectedMaterials() : [];
  if (source && (!materials.length || materials.some(item => !item.pages))) {
    showError('#generate-error', 'Выберите PDF и укажите страницы с задачами.'); return;
  }
  const payload = Object.fromEntries(new FormData(form).entries());
  for (const level of [1, 2, 3, 4]) delete payload[`count_${level}`];
  delete payload.source_count;
  payload.materials = materials;
  state.drafts = [];
  state.targetId = payload[schoolMode ? 'class_id' : 'student_id'];
  state.meta = payload;
  state.pendingGeneration = {
    payload,
    plan: source ? Array(total).fill('source') : [1, 2, 3, 4].flatMap(level => Array(counts[String(level)]).fill(level)),
    nextIndex: 0,
  };
  $('#accept-form [name="title"]').value = `${payload.topic} · ${payload.subject}`;
  $('#accept-form').hidden = true;
  $('#draft-heading').textContent = 'Черновик задач';
  $('#accept-success').hidden = true;
  renderDrafts();
  await runGeneration();
});

$('#generate-resume').addEventListener('click', runGeneration);

$('#accept-form [name="destination"]').addEventListener('change', event => {
  const libraryOnly = event.target.value === 'library';
  $('#worksheet-title-field').hidden = libraryOnly;
  $('#accept-form [name="title"]').required = !libraryOnly;
});
$('#accept-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!state.drafts.length || !state.targetId || state.generating) return;
  if ($('#draft-list .assistant-draft-editor:not([hidden])')) {
    showError('#accept-error', 'Сначала сохраните изменения условия или решения.');
    return;
  }
  showError('#accept-error', '');
  busy(form, true);
  try {
    const result = await api('/api/assistant/accept', 'POST', {
      [schoolMode ? 'class_id' : 'student_id']: state.targetId,
      ...(schoolMode ? {grade: Number($('#generate-form').elements.grade.value)} : {}),
      destination: form.elements.destination.value,
      title: form.elements.title.value, exercises: state.drafts,
    });
    state.drafts = [];
    state.pendingGeneration = null;
    $('#draft-list').innerHTML = '';
    $('#accept-form').hidden = true;
    $('#generate-resume').hidden = true;
    showError('#draft-generation-error', '');
    const success = $('#accept-success');
    success.innerHTML = `Сохранено задач: ${result.exercise_ids.length}. <a href="${schoolMode ? `/school/assignments/?class=${esc(state.targetId)}` : result.worksheet ? `/assignments/?student=${esc(state.targetId)}&tab=${esc(result.worksheet.kind)}&worksheet=${esc(result.worksheet.id)}` : '/assignments/'}">Открыть задания</a>`;
    success.hidden = false;
    $('#draft-heading').textContent = 'Задачи сохранены';
    if (schoolMode) window.dispatchEvent(new Event('school:worksheets-changed'));
  } catch (error) { showError('#accept-error', error.message); }
  finally { busy(form, false); syncEditState(); }
});

async function init() {
  try {
    const form = $('#generate-form');
    syncMode();
    form.querySelector('.school-target').hidden = !schoolMode;
    form.querySelector('.tutor-target').hidden = schoolMode;
    form.elements.student_id.disabled = schoolMode;
    form.elements.class_id.disabled = !schoolMode;
    form.elements.student_id.required = !schoolMode;
    form.elements.class_id.required = schoolMode;
    const targets = await api(schoolMode ? '/api/school/classes' : '/api/students');
    const select = targetSelect();
    select.innerHTML = targets.map(item => `<option value="${esc(item.id)}">${esc(item.name)}${schoolMode ? ` · ${esc(item.subject)}` : ` · ${item.grade} класс`}</option>`).join('');
    const wanted = new URLSearchParams(location.search).get(schoolMode ? 'class' : 'student');
    if (targets.some(item => item.id === wanted)) select.value = wanted;
    if (!targets.length) {
      showError('#generate-error', `Сначала добавьте ${schoolMode ? 'класс' : 'ученика'}.`);
      $('#generate-form button[type="submit"]').disabled = true;
    }
    if (schoolMode) {
      const syncClass = () => {
        const item = targets.find(row => row.id === select.value);
        if (item) {
          form.elements.subject.value = item.subject;
          const grade = /^\s*(\d{1,2})/.exec(item.name)?.[1];
          if (grade && Number(grade) <= 11) form.elements.grade.value = grade;
        }
      };
      select.addEventListener('change', syncClass);
      syncClass();
    }
    select.addEventListener('change', loadMaterials);
    await loadMaterials();
  } catch (error) { showError('#generate-error', error.message); }
}
init();
})();
