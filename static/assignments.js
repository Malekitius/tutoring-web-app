const $ = selector => document.querySelector(selector);
const state = {data: {students: [], lessons: [], worksheets: [], exercise_count: 0}, library: {items: [], total: 0, page: 1, page_size: 40, facets: {topics: [], subtopics: []}}, tab: 'lesson', selected: null, worksheet: null, editing: null};
const statusNames = {draft: 'Черновик', assigned: 'Задано', submitted: 'На проверке', reviewed: 'Проверено', revision: 'На доработке'};
const kindNames = {lesson: 'На уроке', homework: 'Домашнее задание'};
const params = new URLSearchParams(location.search);
let toastTimer;
let filterInitialized = false;
let libraryRequest = 0;
let searchTimer;
let pickerTimer;
let pickerRequest = 0;
const picker = {items: [], total: 0, page: 1, page_size: 40, selected: new Map()};
const difficultyNames = {1: 'базовая', 2: 'средняя', 3: 'повышенная', 4: 'олимпиадная'};
function taskCount(n) { const word = n % 10 === 1 && n % 100 !== 11 ? 'задача' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'задачи' : 'задач'; return `${n} ${word}`; }

function esc(value = '') { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])); }
function fmtDate(value) { if (!value) return ''; const [y,m,d] = value.slice(0,10).split('-'); return `${d}.${m}.${y}`; }
function cookie(name) { return document.cookie.split('; ').find(part => part.startsWith(`${name}=`))?.split('=')[1] || ''; }
function showError(selector, error) { const el = $(selector); el.textContent = error || ''; el.hidden = !error; }
function toast(text, error = false) { const el = $('#toast'); clearTimeout(toastTimer); el.textContent = text; el.className = `toast show${error ? ' error' : ''}`; toastTimer = setTimeout(() => el.className = 'toast', 3500); }
function formObject(form) { return Object.fromEntries(new FormData(form).entries()); }
function renderMath(root) {
  if (!root || typeof window.renderMathInElement !== 'function') return;
  window.renderMathInElement(root, {
    delimiters: [{left: '$', right: '$', display: false}],
    throwOnError: false,
    trust: false,
    strict: 'ignore',
  });
}
function figureMarkup(figures) { return (figures || []).length ? `<div class="task-figures">${figures.map((figure, index) => `<figure><img src="${esc(figure.url)}" alt="Рисунок ${index + 1} из ${esc(figure.source_title)}, страница ${figure.source_page}" loading="lazy"><figcaption>${esc(figure.source_title)} · стр. ${figure.source_page}</figcaption></figure>`).join('')}</div>` : ''; }
function updateMathPreview(form) {
  const preview = form.querySelector('.math-preview');
  for (const [field, selector, empty] of [
    ['prompt', '.preview-prompt', 'Условие пока не заполнено'],
    ['answer', '.preview-answer', 'Решение пока не добавлено'],
  ]) {
    const target = preview.querySelector(selector);
    target.innerHTML = esc(form.elements[field].value || empty);
    renderMath(target);
  }
}
function checkedGrades(container) { return [...document.querySelectorAll(`${container} input:checked`)].map(input => Number(input.value)); }
function setGrades(container, grades) { document.querySelectorAll(`${container} input`).forEach(input => { input.checked = (grades || []).includes(Number(input.value)); }); }
function gradeText(grades) { return `${(grades || []).join(', ')} кл.`; }
const filterKeys = ['subject', 'topic', 'subtopic', 'grade', 'difficulty'];
const filterDefaults = {subject: 'Все предметы', topic: 'Все темы', subtopic: 'Все подтемы', grade: 'Все классы', difficulty: 'Любая'};
function filterValues(scope, key) { return [...document.querySelectorAll(`#${scope}-${key} input:checked`)].map(input => input.value); }
function clearFilter(scope, key) { document.querySelectorAll(`#${scope}-${key} input`).forEach(input => { input.checked = false; }); }
function renderFilter(scope, key, values) {
  const root = $(`#${scope}-${key}`);
  const selected = new Set(filterValues(scope, key));
  const labels = key === 'difficulty' ? difficultyNames : {};
  root.querySelector('.multi-filter-options').innerHTML = values.map(value => {
    const label = labels[value] || (key === 'grade' ? `${value} класс` : value);
    return `<label><input type="checkbox" value="${esc(value)}" aria-label="${esc(label)}" ${selected.has(String(value)) ? 'checked' : ''}><span>${esc(label)}</span></label>`;
  }).join('');
  updateFilterSummary(scope, key);
}
function updateFilterSummary(scope, key) {
  const values = filterValues(scope, key);
  const labels = values.map(value => key === 'difficulty' ? difficultyNames[value] : key === 'grade' ? `${value} класс` : value);
  $(`#${scope}-${key} summary`).textContent = labels.length ? labels.join(', ') : filterDefaults[key];
}
function filterParams(scope, page, pageSize) {
  const query = new URLSearchParams({page, page_size: pageSize});
  for (const key of filterKeys) for (const value of filterValues(scope, key)) query.append(key, value);
  const value = $(`#${scope}-query`).value.trim(); if (value) query.set('q', value);
  return query;
}
function libraryParams() { return filterParams('library', state.library.page, 40); }
document.addEventListener('click', event => { for (const details of document.querySelectorAll('.multi-filter details[open]')) if (!details.contains(event.target)) details.open = false; });
async function loadLibrary(preferredId = state.selected) {
  const request = ++libraryRequest;
  const data = await api(`/api/assignments/exercises?${libraryParams()}`);
  if (request !== libraryRequest) return;
  state.library = data;
  renderFilter('library', 'subject', data.facets.subjects);
  $('#subject-suggestions').innerHTML = [...new Set(['Математика', 'Алгебра', 'Геометрия', 'Физика', 'Химия', ...data.facets.subjects])].map(subject => `<option value="${esc(subject)}"></option>`).join('');
  renderFilter('library', 'topic', data.facets.topics);
  renderFilter('library', 'subtopic', data.facets.subtopics);
  const records = visibleRecords();
  await choose(records.some(item => item.id === preferredId) ? preferredId : records[0]?.id || null);
}

async function api(path, method = 'GET', payload) {
  const options = {method, headers: {'Accept': 'application/json'}};
  if (payload !== undefined) {
    options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
    if (payload instanceof FormData) options.body = payload;
    else { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(payload); }
  } else if (method !== 'GET') options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('Сервер вернул некорректный ответ'); }
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}

function syncFilters() {
  const select = $('#filter-student'), saved = filterInitialized ? select.value : (params.get('student') || '');
  select.innerHTML = `<option value="">Все ученики</option>` + state.data.students.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  select.value = state.data.students.some(s => s.id === saved) ? saved : '';
  filterInitialized = true;
}

function visibleRecords() {
  const query = $('#filter-query').value.trim().toLocaleLowerCase('ru');
  if (state.tab === 'library') return state.library.items;
  return state.data.worksheets.filter(item => item.kind === state.tab && (!$('#filter-student').value || item.student_id === $('#filter-student').value) && `${item.title} ${item.student_name} ${item.instructions}`.toLocaleLowerCase('ru').includes(query));
}

function renderList() {
  const records = visibleRecords();
  $('#lesson-count').textContent = state.data.worksheets.filter(item => item.kind === 'lesson').length;
  $('#homework-count').textContent = state.data.worksheets.filter(item => item.kind === 'homework').length;
  $('#library-count').textContent = state.data.exercise_count;
  $('#new-main').textContent = state.tab === 'library' ? '＋ Новая задача' : '＋ Новая подборка';
  $('#library-pager').hidden = state.tab !== 'library' || state.library.total <= state.library.page_size;
  $('#library-prev').disabled = state.library.page <= 1;
  $('#library-next').disabled = state.library.page * state.library.page_size >= state.library.total;
  $('#library-page-label').textContent = `${state.library.page} / ${Math.max(1, Math.ceil(state.library.total / state.library.page_size))}`;
  if (!records.length) {
    $('#assign-list').innerHTML = `<div class="assign-empty-list">${state.tab === 'library' ? 'Задачи не найдены. Измените фильтры или добавьте новую.' : 'Подборок пока нет. Создайте первую.'}</div>`;
    return;
  }
  $('#assign-list').innerHTML = records.map(item => state.tab === 'library'
    ? `<button class="assign-row ${state.selected === item.id ? 'selected' : ''}" data-id="${esc(item.id)}" type="button"><span class="assign-row-icon">∑</span><span class="assign-row-main"><strong>${esc(item.title)}</strong><small>${esc(item.subject)} · ${gradeText(item.grades)} · сложность ${difficultyNames[item.difficulty]}</small><small>${esc([item.topic, item.subtopic].filter(Boolean).join(' / '))}</small></span><span class="row-chevron">›</span></button>`
    : `<button class="assign-row ${state.selected === item.id ? 'selected' : ''}" data-id="${esc(item.id)}" type="button"><span class="assign-row-icon ${item.kind}">${item.kind === 'lesson' ? '▤' : '⌂'}</span><span class="assign-row-main"><strong>${esc(item.title)}</strong><small>${esc(item.student_name)} · ${taskCount(item.item_count)} · ${statusNames[item.status]}</small>${item.due_date ? `<small>Сдать до ${fmtDate(item.due_date)}</small>` : ''}</span><span class="row-chevron">›</span></button>`).join('');
}

function renderExercise(item) {
  $('#assign-detail').innerHTML = `<div class="assign-detail-head"><div><div class="eyebrow">БИБЛИОТЕКА · ${esc(item.subject)} · ${gradeText(item.grades).toUpperCase()} · СЛОЖНОСТЬ ${difficultyNames[item.difficulty].toUpperCase()}</div><h2>${esc(item.title)}</h2>${item.topic || item.subtopic ? `<p>${esc([item.topic, item.subtopic].filter(Boolean).join(' / '))}</p>` : ''}</div><button class="button button-soft" data-action="edit-exercise" type="button">Изменить</button></div>
    <div class="assign-detail-body"><div class="assign-section-title">Условие</div><div class="assign-copy">${esc(item.prompt)}</div>${figureMarkup(item.figures)}<div class="assign-section-title">Решение для преподавателя</div><div class="assign-copy solution">${item.answer ? esc(item.answer) : 'Решение пока не добавлено.'}</div><p class="assign-help">Добавьте задачу из библиотеки в подборку на урок или в домашнюю работу. В подборке сохранится её отдельная копия.</p></div>
    <div class="assign-detail-footer"><button class="text-button danger-text" data-action="delete-exercise" type="button">Удалить из библиотеки</button></div>`;
  renderMath($('#assign-detail'));
}

function renderWorksheet(item) {
  const isHomework = item.kind === 'homework';
  $('#assign-detail').innerHTML = `<div class="assign-detail-head"><div><div class="eyebrow">${kindNames[item.kind]} · ${esc(item.student_name)}</div><h2>${esc(item.title)}</h2><p>${item.lesson_date ? `Занятие ${fmtDate(item.lesson_date)}` : 'Без привязки к занятию'}${item.due_date ? ` · Сдать до ${fmtDate(item.due_date)}` : ''}</p></div><button class="button button-soft" data-action="edit-worksheet" type="button">Изменить</button></div>
    <div class="assign-detail-body">
      <div class="assign-status-bar"><span class="assign-status ${item.status}">${statusNames[item.status]}</span><div><button class="text-button" data-action="toggle-assigned" type="button">${item.status === 'draft' ? 'Отметить как заданное' : 'Вернуть в черновик'}</button></div></div>
      ${item.instructions ? `<div class="assign-section-title">Инструкция</div><div class="assign-copy">${esc(item.instructions)}</div>` : ''}
      <div class="assign-section-heading"><div><div class="assign-section-title">Задачи</div><small>${item.items.length} в подборке</small></div><button class="button button-soft" data-action="add-item" type="button">＋ Добавить задачи</button></div>
      ${item.items.length ? `<div class="pdf-actions"><a class="button button-secondary" href="/api/assignments/worksheets/${esc(item.id)}/pdf">↓ PDF для ученика</a><a class="button button-soft" href="/api/assignments/worksheets/${esc(item.id)}/pdf?solutions=1">↓ PDF с решениями</a></div>` : ''}
      ${item.items.length ? `<div class="assign-items">${item.items.map((task, index) => `<article class="assign-item" data-id="${esc(task.id)}"><div class="assign-item-top"><span class="assign-number">${index + 1}</span><strong>${esc(task.title)}</strong><button class="text-button" data-action="edit-item" type="button">Изменить</button><button class="text-button danger-text" data-action="delete-item" type="button">Удалить</button></div><div class="assign-copy">${esc(task.prompt)}</div>${figureMarkup(task.figures)}${task.source_ref ? `<p class="assign-help">Источник: ${esc(task.source_ref)}</p>` : ''}<details><summary>Решение для преподавателя</summary><div class="assign-copy solution">${task.answer ? esc(task.answer) : 'Решение пока не добавлено.'}</div></details></article>`).join('')}</div>` : `<div class="assign-blank">Задач пока нет. Добавьте новую или возьмите готовую из библиотеки.</div>`}
      ${isHomework ? `<div class="assign-section-heading"><div><div class="assign-section-title">Работы ученика</div><small>Фото и PDF остаются на этом компьютере</small></div><button class="button button-soft" data-action="upload" type="button">＋ Загрузить работу</button></div>
        ${item.submissions.length ? `<div class="assign-uploads">${item.submissions.map((file, index) => `<div class="assign-upload" data-id="${esc(file.id)}"><span class="assign-upload-icon">↧</span><span><a href="${esc(file.url)}">${esc(file.original_name)}</a><small>Версия ${index + 1} · ${new Date(file.created_at).toLocaleString('ru-RU')}${file.note ? ` · ${esc(file.note)}` : ''}</small></span><button class="text-button danger-text" data-action="delete-upload" type="button">Удалить</button></div>`).join('')}</div>` : `<div class="assign-blank">Работа ещё не загружена.</div>`}
        <div class="assign-section-title review-title">Проверка</div><label class="field"><span>Разбор и рекомендации</span><textarea id="review-feedback" maxlength="5000" placeholder="Что получилось, где ошибка, что исправить">${esc(item.feedback)}</textarea></label><div class="review-actions"><button class="button button-soft" data-action="review" data-status="reviewed" type="button">✓ Проверено</button><button class="button button-secondary" data-action="review" data-status="revision" type="button">Вернуть на доработку</button></div>` : ''}
    </div><div class="assign-detail-footer"><button class="text-button danger-text" data-action="delete-worksheet" type="button">Удалить подборку</button></div>`;
  renderMath($('#assign-detail'));
}

async function choose(id) {
  state.selected = id;
  renderList();
  if (!id) { $('#assign-detail').innerHTML = state.tab === 'library'
    ? `<div class="assign-detail-empty"><span>∑</span><h2>Библиотека задач</h2><p>Создайте задачу или загрузите библиотеку из JSON либо ZIP. Здесь появятся условие, рисунки, решение и классификация задачи.</p></div>`
    : `<div class="assign-detail-empty"><span>◇</span><h2>Создайте первую подборку</h2><p>Соберите задачи для занятия или домашней работы. Готовые задачи можно повторно использовать из библиотеки.</p></div>`; return; }
  try {
    if (state.tab === 'library') {
      const item = state.library.items.find(entry => entry.id === id);
      if (item) renderExercise(item);
    } else { state.worksheet = await api(`/api/assignments/worksheets/${id}`); renderWorksheet(state.worksheet); }
  } catch (error) { toast(error.message, true); }
}

async function reload(preferredId = state.selected) {
  state.data = await api('/api/assignments/overview');
  syncFilters();
  if (state.tab === 'library') { await loadLibrary(preferredId); return; }
  const records = visibleRecords();
  await choose(records.some(item => item.id === preferredId) ? preferredId : records[0]?.id || null);
}

async function switchTab(tab, preferredId = null) {
  state.tab = tab;
  document.querySelectorAll('.assign-tab').forEach(button => { const active = button.dataset.tab === tab; button.classList.toggle('active', active); button.setAttribute('aria-selected', String(active)); });
  $('#assign-layout').hidden = tab === 'generator';
  $('#generator-section').hidden = tab !== 'generator';
  $('#new-main').hidden = tab === 'generator';
  if (tab === 'generator') { $('#library-actions').hidden = true; return; }
  syncFilters();
  $('#worksheet-filters').hidden = tab === 'library';
  $('#library-filters').hidden = tab !== 'library';
  $('#library-actions').hidden = tab !== 'library';
  if (tab === 'library') { state.library.page = 1; await loadLibrary(preferredId); return; }
  await choose(visibleRecords().some(item => item.id === preferredId) ? preferredId : visibleRecords()[0]?.id || null);
}

function lessonOptions(studentId, selected = '') {
  const lessons = state.data.lessons.filter(item => item.student_id === studentId);
  const select = $('#worksheet-form [name="lesson_id"]');
  select.innerHTML = `<option value="">Без привязки к занятию</option>` + lessons.map(item => `<option value="${esc(item.id)}">${fmtDate(item.date)} · ${esc(item.time)}</option>`).join('');
  select.value = selected || '';
}

function showWorksheetDialog(item = null) {
  state.editing = item;
  const form = $('#worksheet-form'); form.reset();
  $('#worksheet-title').textContent = item ? 'Изменить подборку' : 'Новая подборка';
  form.elements.student_id.innerHTML = state.data.students.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('');
  form.elements.kind.value = item?.kind || state.tab;
  form.elements.student_id.value = item?.student_id || $('#filter-student').value || params.get('student') || state.data.students[0]?.id || '';
  form.elements.title.value = item?.title || '';
  form.elements.instructions.value = item?.instructions || '';
  form.elements.due_date.value = item?.due_date || '';
  lessonOptions(form.elements.student_id.value, item?.lesson_id || params.get('lesson'));
  $('#worksheet-dialog .due-field').hidden = form.elements.kind.value !== 'homework';
  showError('#worksheet-error', '');
  $('#worksheet-dialog').showModal();
}

function showExerciseDialog(item = null) {
  state.editing = item;
  const form = $('#exercise-form'); form.reset();
  $('#exercise-title').textContent = item ? 'Изменить задачу' : 'Новая задача';
  form.elements.title.value = item?.title || '';
  form.elements.prompt.value = item?.prompt || '';
  form.elements.answer.value = item?.answer || '';
  form.elements.subject.value = item?.subject || 'Математика';
  setGrades('#exercise-grades', item?.grades || [5]);
  form.elements.topic.value = item?.topic || '';
  form.elements.subtopic.value = item?.subtopic || '';
  form.elements.difficulty.value = item?.difficulty || 2;
  updateMathPreview(form);
  showError('#exercise-error', ''); $('#exercise-dialog').showModal();
}

function pickerParams() {
  return filterParams('picker', picker.page, picker.page_size);
}
function renderPicker() {
  const existing = new Set(state.worksheet.items.map(item => item.source_id));
  $('#picker-list').innerHTML = picker.items.length ? picker.items.map(item => {
    const added = existing.has(item.id);
    return `<label class="picker-row ${added ? 'already-added' : ''}"><input type="checkbox" value="${esc(item.id)}" ${picker.selected.has(item.id) ? 'checked' : ''} ${added ? 'disabled' : ''}><span><strong>${esc(item.title)}</strong><small>${esc(item.subject)} · ${gradeText(item.grades)} · ${difficultyNames[item.difficulty]}${item.topic ? ` · ${esc(item.topic)}` : ''}${item.subtopic ? ` / ${esc(item.subtopic)}` : ''}</small><span class="picker-prompt">${esc(item.prompt)}</span>${added ? '<small>Уже в подборке</small>' : ''}</span></label>`;
  }).join('') : '<div class="assign-empty-list">Задачи не найдены. Измените фильтры или создайте новую.</div>';
  renderMath($('#picker-list'));
  $('#picker-page-label').textContent = `${picker.page} / ${Math.max(1, Math.ceil(picker.total / picker.page_size))} · ${taskCount(picker.total)}`;
  $('#picker-prev').disabled = picker.page <= 1;
  $('#picker-next').disabled = picker.page * picker.page_size >= picker.total;
  $('#picker-select-page').disabled = !picker.items.some(item => !existing.has(item.id) && !picker.selected.has(item.id));
  $('#picker-count').textContent = `Выбрано: ${picker.selected.size}`;
  $('#picker-add').disabled = !picker.selected.size;
  const n = picker.selected.size;
  const accusative = n % 10 === 1 && n % 100 !== 11 ? 'задачу' : taskCount(n).split(' ')[1];
  $('#picker-add').textContent = n ? `Добавить ${n} ${accusative}` : 'Добавить выбранные';
}
async function loadPicker() {
  const request = ++pickerRequest;
  const data = await api(`/api/assignments/exercises?${pickerParams()}`);
  if (request !== pickerRequest || !$('#picker-dialog').open) return;
  Object.assign(picker, data);
  renderFilter('picker', 'subject', data.facets.subjects);
  renderFilter('picker', 'topic', data.facets.topics);
  renderFilter('picker', 'subtopic', data.facets.subtopics);
  renderPicker();
}
async function showPicker() {
  picker.selected.clear(); picker.page = 1;
  for (const key of filterKeys) { clearFilter('picker', key); updateFilterSummary('picker', key); }
  $('#picker-query').value = '';
  const grade = $(`#picker-grade input[value="${state.worksheet.grade}"]`);
  if (grade) { grade.checked = true; updateFilterSummary('picker', 'grade'); }
  showError('#picker-error', '');
  $('#picker-dialog').showModal();
  try { await loadPicker(); } catch (error) { showError('#picker-error', error.message); }
}

function showItemDialog(item = null) {
  state.editing = item;
  const form = $('#item-form'); form.reset();
  $('#item-title').textContent = item ? 'Изменить задачу' : 'Добавить задачу';
  form.elements.title.value = item?.title || '';
  form.elements.prompt.value = item?.prompt || '';
  form.elements.answer.value = item?.answer || '';
  $('#save-library-field').hidden = Boolean(item);
  $('#library-meta').hidden = true;
  $('#item-fields').querySelectorAll('[required]').forEach(input => input.disabled = false);
  setGrades('#item-grades', [state.data.students.find(s => s.id === state.worksheet?.student_id)?.grade || 5]);
  $('#item-fields').hidden = false;
  updateMathPreview(form);
  showError('#item-error', ''); $('#item-dialog').showModal();
}

async function handleDetailClick(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  const worksheet = state.worksheet;
  try {
    if (action === 'edit-exercise') showExerciseDialog(state.library.items.find(item => item.id === state.selected));
    else if (action === 'delete-exercise') {
      if (!await window.AppDialogs.confirm('Уже добавленные копии останутся в подборках.', {title: 'Удалить задачу из библиотеки?'})) return;
      await api(`/api/assignments/exercises/${state.selected}`, 'DELETE'); await reload(null); toast('Задача удалена');
    } else if (action === 'edit-worksheet') showWorksheetDialog(worksheet);
    else if (action === 'delete-worksheet') {
      if (!await window.AppDialogs.confirm('Задачи в подборке и загруженные работы будут удалены вместе с ней.', {title: 'Удалить подборку?'})) return;
      await api(`/api/assignments/worksheets/${state.selected}`, 'DELETE'); await reload(null); toast('Подборка удалена');
    } else if (action === 'add-item') showPicker();
    else if (action === 'edit-item') showItemDialog(worksheet.items.find(item => item.id === button.closest('.assign-item').dataset.id));
    else if (action === 'delete-item') {
      if (!await window.AppDialogs.confirm('Задача будет удалена из этой подборки.', {title: 'Удалить задачу?'})) return;
      await api(`/api/assignments/items/${button.closest('.assign-item').dataset.id}`, 'DELETE'); await reload(); toast('Задача удалена из подборки');
    } else if (action === 'toggle-assigned') {
      await api(`/api/assignments/worksheets/${worksheet.id}`, 'PATCH', {status: worksheet.status === 'draft' ? 'assigned' : 'draft'}); await reload();
    } else if (action === 'upload') { $('#upload-form').reset(); showError('#upload-error', ''); $('#upload-dialog').showModal(); }
    else if (action === 'delete-upload') {
      if (!await window.AppDialogs.confirm('Загруженная работа будет удалена.', {title: 'Удалить файл?'})) return;
      await api(`/api/assignments/submissions/${button.closest('.assign-upload').dataset.id}`, 'DELETE'); await reload(); toast('Файл удалён');
    } else if (action === 'review') {
      await api(`/api/assignments/worksheets/${worksheet.id}`, 'PATCH', {status: button.dataset.status, feedback: $('#review-feedback').value}); await reload(); toast('Результат проверки сохранён');
    }
  } catch (error) { toast(error.message, true); }
}

$('#new-main').addEventListener('click', () => {
  if (state.tab === 'library') showExerciseDialog();
  else if (state.data.students.length) showWorksheetDialog();
  else toast('Сначала добавьте ученика в разделе «Ученики»', true);
});
document.querySelectorAll('.assign-tab').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
$('#filter-student').addEventListener('change', () => choose(visibleRecords()[0]?.id || null));
$('#filter-query').addEventListener('input', () => choose(visibleRecords()[0]?.id || null));
for (const scope of ['library', 'picker']) {
  renderFilter(scope, 'grade', Array.from({length: 11}, (_, index) => index + 1));
  renderFilter(scope, 'difficulty', [1, 2, 3, 4]);
}
for (const container of ['#exercise-grades', '#item-grades']) $(container).innerHTML = Array.from({length: 11}, (_, index) => `<label><input type="checkbox" value="${index + 1}"><span>${index + 1}</span></label>`).join('');
$('#library-filters').addEventListener('change', event => {
  const root = event.target.closest('.multi-filter details'); if (!root) return;
  const key = root.id.slice('library-'.length);
  if (key === 'subject') { clearFilter('library', 'topic'); clearFilter('library', 'subtopic'); }
  if (key === 'topic') clearFilter('library', 'subtopic');
  for (const affected of key === 'subject' ? ['subject', 'topic', 'subtopic'] : key === 'topic' ? ['topic', 'subtopic'] : [key]) updateFilterSummary('library', affected);
  state.library.page = 1; loadLibrary(null).catch(error => toast(error.message, true));
});
$('#library-query').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.library.page = 1; loadLibrary(null).catch(error => toast(error.message, true)); }, 250); });
$('#library-reset').addEventListener('click', () => { for (const key of filterKeys) { clearFilter('library', key); updateFilterSummary('library', key); } $('#library-query').value = ''; state.library.page = 1; loadLibrary(null).catch(error => toast(error.message, true)); });
$('#library-prev').addEventListener('click', () => { state.library.page--; loadLibrary(null).catch(error => toast(error.message, true)); });
$('#library-next').addEventListener('click', () => { state.library.page++; loadLibrary(null).catch(error => toast(error.message, true)); });
$('#assign-list').addEventListener('click', event => { const row = event.target.closest('[data-id]'); if (row) choose(row.dataset.id); });
$('#assign-detail').addEventListener('click', handleDetailClick);
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('#worksheet-form [name="student_id"]').addEventListener('change', event => lessonOptions(event.target.value));
$('#worksheet-form [name="kind"]').addEventListener('change', event => { $('#worksheet-dialog .due-field').hidden = event.target.value !== 'homework'; if (event.target.value !== 'homework') $('#worksheet-form [name="due_date"]').value = ''; });
$('#item-form [name="save_library"]').addEventListener('change', event => { $('#library-meta').hidden = !event.target.checked; });
for (const selector of ['#exercise-form', '#item-form']) $(selector).addEventListener('input', event => {
  if (event.target.name === 'prompt' || event.target.name === 'answer') updateMathPreview(event.currentTarget);
});
$('.picker-filters').addEventListener('change', event => {
  const root = event.target.closest('.multi-filter details'); if (!root) return;
  const key = root.id.slice('picker-'.length);
  if (key === 'subject') { clearFilter('picker', 'topic'); clearFilter('picker', 'subtopic'); }
  if (key === 'topic') clearFilter('picker', 'subtopic');
  for (const affected of key === 'subject' ? ['subject', 'topic', 'subtopic'] : key === 'topic' ? ['topic', 'subtopic'] : [key]) updateFilterSummary('picker', affected);
  picker.page = 1; loadPicker().catch(error => showError('#picker-error', error.message));
});
$('#picker-query').addEventListener('input', () => { clearTimeout(pickerTimer); pickerTimer = setTimeout(() => { picker.page = 1; loadPicker().catch(error => showError('#picker-error', error.message)); }, 250); });
$('#picker-prev').addEventListener('click', () => { picker.page--; loadPicker().catch(error => showError('#picker-error', error.message)); });
$('#picker-next').addEventListener('click', () => { picker.page++; loadPicker().catch(error => showError('#picker-error', error.message)); });
$('#picker-list').addEventListener('change', event => {
  const input = event.target.closest('input[type="checkbox"]'); if (!input) return;
  const item = picker.items.find(entry => entry.id === input.value);
  if (input.checked && item) {
    if (picker.selected.size >= 100) { input.checked = false; showError('#picker-error', 'За один раз можно добавить до 100 задач'); return; }
    picker.selected.set(item.id, item);
  }
  else picker.selected.delete(input.value);
  renderPicker();
});
$('#picker-select-page').addEventListener('click', () => { const existing = new Set(state.worksheet.items.map(item => item.source_id)); for (const item of picker.items) if (!existing.has(item.id) && picker.selected.size < 100) picker.selected.set(item.id, item); renderPicker(); });
$('#picker-clear').addEventListener('click', () => { picker.selected.clear(); renderPicker(); });
$('#picker-new').addEventListener('click', () => { $('#picker-dialog').close(); showItemDialog(); });
$('#picker-add').addEventListener('click', async () => {
  const button = $('#picker-add'); button.disabled = true;
  try {
    const result = await api(`/api/assignments/worksheets/${state.worksheet.id}/items/batch`, 'POST', {exercise_ids: [...picker.selected.keys()]});
    $('#picker-dialog').close(); await reload(); toast(`Добавлено задач: ${result.items.length}`);
  } catch (error) { showError('#picker-error', error.message); button.disabled = false; }
});
$('#import-open').addEventListener('click', () => { $('#import-form').reset(); $('#import-preview').hidden = true; $('#import-submit').disabled = true; showError('#import-error', ''); $('#import-dialog').showModal(); });
$('#import-form [name="file"]').addEventListener('change', async event => {
  $('#import-submit').disabled = true; $('#import-preview').hidden = true; showError('#import-error', '');
  const file = event.target.files[0]; if (!file) return;
  try { const data = new FormData(); data.append('file', file); const preview = await api('/api/assignments/library/import?dry_run=1', 'POST', data); $('#import-preview').textContent = `Всего ${preview.total} задач: новых ${preview.created}, обновятся ${preview.updated}, без изменений ${preview.unchanged}.`; $('#import-preview').hidden = false; $('#import-submit').disabled = false; }
  catch (error) { showError('#import-error', error.message); }
});
$('#import-form').addEventListener('submit', async event => { event.preventDefault(); const file = event.currentTarget.elements.file.files[0]; if (!file) return; try { const data = new FormData(); data.append('file', file); const result = await api('/api/assignments/library/import', 'POST', data); $('#import-dialog').close(); state.library.page = 1; await reload(null); toast(`Импорт: ${result.created} новых, ${result.updated} обновлено`); } catch (error) { showError('#import-error', error.message); } });

$('#worksheet-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget;
  const payload = formObject(form); payload.lesson_id ||= null; payload.due_date = payload.kind === 'homework' ? (payload.due_date || null) : null;
  try {
    const item = await api(state.editing ? `/api/assignments/worksheets/${state.editing.id}` : '/api/assignments/worksheets', state.editing ? 'PUT' : 'POST', payload);
    $('#worksheet-dialog').close(); await switchTab(item.kind); $('#filter-student').value = item.student_id; await reload(item.id); toast('Подборка сохранена');
  } catch (error) { showError('#worksheet-error', error.message); }
});

$('#exercise-form').addEventListener('submit', async event => {
  event.preventDefault(); const payload = formObject(event.currentTarget); payload.grades = checkedGrades('#exercise-grades');
  try {
    const item = await api(state.editing ? `/api/assignments/exercises/${state.editing.id}` : '/api/assignments/exercises', state.editing ? 'PUT' : 'POST', payload);
    $('#exercise-dialog').close(); await reload(item.id); toast('Задача сохранена');
  } catch (error) { showError('#exercise-error', error.message); }
});

$('#item-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, payload = formObject(form);
  try {
    if (state.editing) await api(`/api/assignments/items/${state.editing.id}`, 'PUT', {title: payload.title, prompt: payload.prompt, answer: payload.answer});
    else {
        if (form.elements.save_library.checked) {
          const exercise = await api('/api/assignments/exercises', 'POST', {title: payload.title, prompt: payload.prompt, answer: payload.answer, subject: payload.library_subject, grades: checkedGrades('#item-grades'), topic: payload.library_topic, subtopic: payload.library_subtopic, difficulty: payload.library_difficulty});
          await api(`/api/assignments/worksheets/${state.worksheet.id}/items`, 'POST', {source_id: exercise.id});
        } else {
          await api(`/api/assignments/worksheets/${state.worksheet.id}/items`, 'POST', {title: payload.title, prompt: payload.prompt, answer: payload.answer});
        }
    }
    $('#item-dialog').close(); await reload(); toast('Задача сохранена');
  } catch (error) { showError('#item-error', error.message); }
});

$('#upload-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget;
  const files = [...form.elements.file.files], note = form.elements.note.value;
  try {
    for (const file of files) { const payload = new FormData(); payload.append('file', file); payload.append('note', note); await api(`/api/assignments/worksheets/${state.worksheet.id}/submissions`, 'POST', payload); }
    $('#upload-dialog').close(); await reload(); toast('Работа загружена');
  } catch (error) { showError('#upload-error', error.message); await reload(); }
});

(async () => {
  try {
    await reload(null);
    if (params.get('lesson')) {
      const selected = state.data.worksheets.find(w => w.lesson_id === params.get('lesson'));
      await switchTab(selected?.kind || 'lesson', selected?.id);
    } else if (['lesson', 'homework', 'library', 'generator'].includes(params.get('tab'))) await switchTab(params.get('tab'), params.get('worksheet'));
  } catch (error) { toast(error.message, true); }
})();
