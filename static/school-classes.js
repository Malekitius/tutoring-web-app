const $ = selector => document.querySelector(selector);
const groups = [
  ['support', 'Нужна поддержка'],
  ['mastering', 'Осваивает программу'],
  ['advanced', 'Готов к углублению'],
];
const state = {classes: [], current: null, query: '', group: 'all', editor: null};
const dialog = $('#school-dialog');
const loadMaterials = window.MaterialsPanel.attach($('#class-detail'), 'school_class');

function esc(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])); }
function cookie(name) { return document.cookie.split('; ').find(part => part.startsWith(`${name}=`))?.split('=')[1] || ''; }
function toast(message, failed = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${failed ? ' error' : ''}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = 'toast', 3800); }
function setError(message) { const el = $('#school-error'); el.textContent = message; el.hidden = !message; }
async function api(path, method = 'GET', payload) {
  const options = {method, headers: {'Accept': 'application/json'}};
  if (payload !== undefined) { options.headers['Content-Type'] = 'application/json'; options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken')); options.body = JSON.stringify(payload); }
  if (method === 'DELETE') options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
  const response = await fetch(path, options);
  let data; try { data = await response.json(); } catch { throw new Error('Не удалось прочитать ответ сервера'); }
  if (!response.ok) throw new Error(data.error || 'Не удалось сохранить данные');
  return data;
}
function field(label, name, value, type = 'text', extra = '') { return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`; }
function optionField(label, name, options, value) { return `<label class="field"><span>${label}</span><select name="${name}">${options.map(([key, title]) => `<option value="${esc(key)}"${key === value ? ' selected' : ''}>${esc(title)}</option>`).join('')}</select></label>`; }
function dateLabel(value) { return value ? new Date(`${value}T00:00:00`).toLocaleDateString('ru-RU') : 'Дата рождения не указана'; }

async function loadClasses(preferred = state.current?.id || localStorage.getItem('selectedSchoolClass')) {
  state.classes = await api('/api/school/classes');
  const selected = state.classes.find(item => item.id === preferred) || state.classes[0];
  state.current = selected ? await api(`/api/school/classes/${selected.id}`) : null;
  if (state.current) localStorage.setItem('selectedSchoolClass', state.current.id);
  else localStorage.removeItem('selectedSchoolClass');
  render();
}
function renderList() {
  $('#class-count').textContent = state.classes.length;
  const query = state.query.trim().toLocaleLowerCase('ru');
  const visible = state.classes.filter(item => `${item.name} ${item.subject} ${item.level}`.toLocaleLowerCase('ru').includes(query));
  $('#class-list').innerHTML = visible.length ? visible.map(item => `<button class="student-row${item.id === state.current?.id ? ' selected' : ''}" type="button" data-class-id="${item.id}" aria-current="${item.id === state.current?.id}"><span class="avatar">${esc(item.name.slice(0, 2).toUpperCase())}</span><span class="student-row-body"><strong>${esc(item.name)}</strong><small>${esc(item.subject)} · ${item.student_count} учеников</small></span><span class="row-chevron" aria-hidden="true">›</span></button>`).join('') : `<div class="list-empty">${state.classes.length ? 'Классы не найдены.' : '<span class="empty-symbol">▦</span>Создайте первый класс.'}</div>`;
}
function renderDetail() {
  const item = state.current;
  if (!item) {
    $('#class-detail').innerHTML = '<div class="detail-empty"><div class="empty-illustration" aria-hidden="true">▦</div><h2>Создайте первый класс</h2><p>Укажите предмет и уровень, затем добавьте учеников и распределите их по трём группам.</p><button class="button button-primary" type="button" data-action="add-class">＋ Создать класс</button></div>';
    return;
  }
  const counts = Object.fromEntries(groups.map(([key]) => [key, item.students.filter(student => student.group === key).length]));
  const visibleGroups = state.group === 'all' ? groups : groups.filter(([key]) => key === state.group);
  $('#class-detail').innerHTML = `<div class="detail-top"><div class="detail-intro"><div class="detail-avatar" aria-hidden="true">${esc(item.name.slice(0, 2).toUpperCase())}</div><div><h2>${esc(item.name)}</h2><div class="meta-line"><span>${esc(item.subject)}</span><span>•</span><span class="school-level">${esc(item.level)}</span></div></div></div><div class="school-detail-actions"><a class="button button-soft" href="/school/schedule/?class=${item.id}">Расписание</a><a class="button button-soft" href="/school/assignments/?class=${item.id}">Создать задания</a><button class="button button-soft" type="button" data-action="edit-class">Редактировать</button></div></div>
    <div class="school-stat-line">${groups.map(([key, label]) => `<div class="stat"><strong>${counts[key]}</strong><small>${label}</small></div>`).join('')}</div>
    <div class="section-title"><h3>Ученики класса</h3><button class="text-button" type="button" data-action="add-student">＋ Добавить ученика</button></div>
    <div class="school-filter" role="group" aria-label="Фильтр по группе"><button type="button" data-group="all" class="${state.group === 'all' ? 'active' : ''}">Все · ${item.students.length}</button>${groups.map(([key, label]) => `<button type="button" data-group="${key}" class="${state.group === key ? 'active' : ''}">${label} · ${counts[key]}</button>`).join('')}</div>
    <div class="school-roster">${visibleGroups.map(([key, label]) => { const students = item.students.filter(student => student.group === key); return `<section class="school-group"><div class="school-group-heading"><h4>${label}</h4><span>${students.length}</span></div>${students.length ? students.map(student => `<article class="school-student"><div class="school-student-main"><strong>${esc(student.name)}</strong><small>${esc(dateLabel(student.birth_date))}</small>${student.comment ? `<p>${esc(student.comment)}</p>` : ''}</div><div class="school-student-actions"><button class="text-button" type="button" data-action="edit-student" data-id="${student.id}">Изменить</button><button class="text-button danger-text" type="button" data-action="delete-student" data-id="${student.id}">Удалить</button></div></article>`).join('') : '<div class="school-empty-group">Пока никого нет</div>'}</section>`; }).join('')}</div>
    <section class="materials-panel" data-materials-panel></section>
    <div class="foot-actions"><button class="text-button danger-text" type="button" data-action="delete-class">Удалить класс</button></div>`;
  loadMaterials(item.id);
}
function render() { renderList(); renderDetail(); }
function openEditor(type, item = null) {
  state.editor = {type, item}; setError('');
  $('#school-dialog-title').textContent = type === 'class' ? (item ? 'Изменить класс' : 'Новый класс') : (item ? 'Изменить ученика' : 'Новый ученик');
  $('#school-fields').innerHTML = type === 'class'
    ? field('Название класса', 'name', item?.name || '', 'text', 'required maxlength="80" placeholder="Например, 8А" autofocus') + field('Предмет', 'subject', item?.subject || '', 'text', 'required maxlength="80" list="school-subjects" placeholder="Например, математика"') + '<datalist id="school-subjects"><option value="Математика"><option value="Алгебра"><option value="Геометрия"><option value="Физика"><option value="Химия"></datalist>' + field('Уровень', 'level', item?.level || 'Базовый', 'text', 'required maxlength="80" list="school-levels"') + '<datalist id="school-levels"><option value="Базовый"><option value="Углублённый"><option value="Профильный"></datalist>'
    : field('Имя и фамилия', 'name', item?.name || '', 'text', 'required maxlength="120" autofocus') + optionField('Группа', 'group', groups, item?.group || 'mastering') + field('Дата рождения', 'birth_date', item?.birth_date || '', 'date') + `<label class="field"><span>Комментарий</span><textarea name="comment" maxlength="5000" placeholder="Наблюдения об ученике">${esc(item?.comment || '')}</textarea></label>`;
  dialog.showModal(); $('#school-fields [autofocus]')?.focus();
}
async function saveEditor(event) {
  event.preventDefault();
  const {type, item} = state.editor;
  const values = Object.fromEntries(new FormData($('#school-form')));
  const path = type === 'class' ? (item ? `/api/school/classes/${item.id}` : '/api/school/classes') : (item ? `/api/school/students/${item.id}` : `/api/school/classes/${state.current.id}/students`);
  const save = $('#school-form [type="submit"]'); save.disabled = true; setError('');
  try {
    const result = await api(path, item ? 'PUT' : 'POST', values);
    dialog.close(); await loadClasses(type === 'class' ? result.id : state.current.id); toast('Сохранено');
  } catch (error) { setError(error.message); }
  finally { save.disabled = false; }
}
async function remove(type, id) {
  if (!await window.AppDialogs.confirm(type === 'class' ? 'Вместе с классом будут удалены его ученики, уроки, материалы и подборки.' : 'Ученик будет удалён только из этого класса.',
    {title: type === 'class' ? 'Удалить класс?' : 'Удалить ученика класса?'})) return;
  try {
    await api(type === 'class' ? `/api/school/classes/${id}` : `/api/school/students/${id}`, 'DELETE');
    await loadClasses(type === 'class' ? null : state.current.id); toast('Удалено');
  } catch (error) { toast(error.message, true); }
}
$('#add-class').addEventListener('click', () => openEditor('class'));
$('#class-search').addEventListener('input', event => { state.query = event.target.value; renderList(); });
$('#class-list').addEventListener('click', async event => {
  const button = event.target.closest('[data-class-id]'); if (!button) return;
  try { state.current = await api(`/api/school/classes/${button.dataset.classId}`); state.group = 'all'; localStorage.setItem('selectedSchoolClass', state.current.id); render(); }
  catch (error) { toast(error.message, true); }
});
$('#class-detail').addEventListener('click', event => {
  const filter = event.target.closest('[data-group]'); if (filter) { state.group = filter.dataset.group; renderDetail(); return; }
  const button = event.target.closest('[data-action]'); if (!button) return;
  const action = button.dataset.action, current = state.current;
  if (action === 'add-class') openEditor('class');
  if (action === 'edit-class') openEditor('class', current);
  if (action === 'delete-class') remove('class', current.id);
  if (action === 'add-student') openEditor('student');
  if (action === 'edit-student') openEditor('student', current.students.find(item => item.id === button.dataset.id));
  if (action === 'delete-student') remove('student', button.dataset.id);
});
document.querySelectorAll('.school-close').forEach(button => button.addEventListener('click', () => dialog.close()));
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
$('#school-form').addEventListener('submit', saveEditor);
loadClasses().catch(error => toast(error.message, true));
