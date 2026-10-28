const $ = selector => document.querySelector(selector);
const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const statusNames = {planned: 'Запланировано', completed: 'Проведено', cancelled: 'Отменено'};
const gridStart = 9 * 60, gridEnd = 22 * 60, pixelsPerMinute = 1.2;
const state = {date: new Date(), start: '', end: '', lessons: [], classes: [], filter: new URLSearchParams(location.search).get('class') || '', editing: null};
const lessonDialog = $('#school-lesson-dialog'), seriesDialog = $('#school-series-dialog');

function esc(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])); }
function cookie(name) { return document.cookie.split('; ').find(part => part.startsWith(`${name}=`))?.split('=')[1] || ''; }
function localDate(iso) { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); }
function isoDate(value) { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`; }
function addDays(value, count) { const result = new Date(value); result.setDate(result.getDate() + count); return result; }
function monday(value) { return addDays(value, -(value.getDay() + 6) % 7); }
function minutes(value) { const [hours, rest] = value.split(':').map(Number); return hours * 60 + rest; }
function timeLabel(total) { return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`; }
function timeAtPoint(clientY, grid, duration = 45) { const value = gridStart + Math.round((clientY - grid.getBoundingClientRect().top) / pixelsPerMinute / 15) * 15; return timeLabel(Math.min(Math.max(value, gridStart), gridEnd - Math.min(duration, gridEnd - gridStart))); }
function plural(n, forms) { const x = n % 100, y = n % 10; return x >= 11 && x <= 14 ? forms[2] : y === 1 ? forms[0] : y >= 2 && y <= 4 ? forms[1] : forms[2]; }
function toast(message, failed = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${failed ? ' error' : ''}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = 'toast', 3800); }
function formError(selector, message) { const el = $(selector); el.textContent = message; el.hidden = !message; }
async function api(path, method = 'GET', payload) {
  const options = {method, headers: {'Accept': 'application/json'}};
  if (payload !== undefined) { options.headers['Content-Type'] = 'application/json'; options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken')); options.body = JSON.stringify(payload); }
  if (method === 'DELETE') options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
  const response = await fetch(path, options);
  let data; try { data = await response.json(); } catch { throw new Error('Не удалось прочитать ответ сервера'); }
  if (!response.ok) throw new Error(data.error || 'Не удалось сохранить урок');
  return data;
}
function classOptions(selected) { return state.classes.map(item => `<option value="${item.id}"${item.id === selected ? ' selected' : ''}>${esc(item.name)} · ${esc(item.subject)}</option>`).join(''); }

async function loadWeek() {
  try {
    const data = await api(`/api/school/schedule?week=${isoDate(state.date)}`);
    state.start = data.start; state.end = data.end; state.lessons = data.lessons; state.classes = data.classes;
    if (state.filter && !state.classes.some(item => item.id === state.filter)) state.filter = '';
    $('#school-class-filter').innerHTML = '<option value="">Все классы</option>' + classOptions(state.filter);
    $('#school-class-filter').value = state.filter;
    renderCalendar();
  } catch (error) { toast(error.message, true); }
}
function card(item, positioned) {
  const durationClass = positioned && item.duration_min < 30 ? ' tiny' : positioned && item.duration_min < 50 ? ' compact' : positioned && item.duration_min < 90 ? ' short-card' : '';
  const placement = positioned ? ` style="top:${(minutes(item.time) - gridStart) * pixelsPerMinute + 3}px;height:${Math.max(14, item.duration_min * pixelsPerMinute - 6)}px"` : '';
  const quick = !positioned || item.duration_min >= 60;
  return `<div class="lesson-card status-${item.status}${durationClass}${positioned ? '' : ' extra-card'}${quick ? ' has-quick-actions' : ''}" data-id="${item.id}" draggable="true"${placement}><button class="lesson-open" type="button" aria-label="${esc(item.class_name)}, ${item.time}, ${statusNames[item.status]}"><span class="lesson-time">${item.time}<span>${item.duration_min} мин</span></span><strong>${esc(item.class_name)}</strong><span class="lesson-meta">${esc(item.subject)}${item.topic ? ` · ${esc(item.topic)}` : ''}</span>${item.recurring ? '<span class="repeat-mark" title="Еженедельно">↻</span>' : ''}${item.status !== 'planned' ? `<span class="lesson-status">${statusNames[item.status]}</span>` : ''}</button>${quick ? `<div class="lesson-quick-actions"><button type="button" class="quick-status quick-done" data-status="completed" aria-pressed="${item.status === 'completed'}" title="Проведено">✓ Да</button><button type="button" class="quick-status quick-cancel" data-status="cancelled" aria-pressed="${item.status === 'cancelled'}" title="Отменено">× Нет</button></div>` : ''}</div>`;
}
function renderCalendar() {
  const start = localDate(state.start), end = localDate(state.end);
  $('#week-label').textContent = start.getMonth() === end.getMonth() ? `${start.getDate()}–${end.getDate()} ${months[end.getMonth()]} ${end.getFullYear()}` : `${start.getDate()} ${months[start.getMonth()]} – ${end.getDate()} ${months[end.getMonth()]} ${end.getFullYear()}`;
  const visible = state.filter ? state.lessons.filter(item => item.class_id === state.filter) : state.lessons;
  const active = visible.filter(item => item.status !== 'cancelled');
  $('#lesson-total').textContent = `${active.length} ${plural(active.length, ['урок', 'урока', 'уроков'])}`;
  const hours = active.reduce((sum, item) => sum + item.duration_min, 0) / 60;
  $('#hours-total').textContent = `${Number.isInteger(hours) ? hours : hours.toFixed(1).replace('.', ',')} ч`;
  const axis = `<div class="time-axis" aria-hidden="true"><div class="time-axis-heading">Время</div><div class="time-axis-body">${Array.from({length: 14}, (_, i) => `<span class="time-mark" style="top:${i * 60 * pixelsPerMinute}px">${timeLabel(gridStart + i * 60)}</span>`).join('')}</div></div>`;
  const today = isoDate(new Date());
  $('#school-calendar').innerHTML = axis + Array.from({length: 7}, (_, i) => {
    const day = addDays(start, i), dayIso = isoDate(day);
    const items = visible.filter(item => item.date === dayIso).sort((a, b) => a.time.localeCompare(b.time));
    const inGrid = items.filter(item => item.status !== 'cancelled' && minutes(item.time) >= gridStart && minutes(item.time) + item.duration_min <= gridEnd);
    const extra = items.filter(item => !inGrid.includes(item));
    return `<section class="day-column${dayIso === today ? ' is-today' : ''}" data-date="${dayIso}"><div class="day-heading"><div><span class="day-name">${weekdays[i]}</span><strong>${day.getDate()}</strong></div><button class="day-add" type="button" data-date="${dayIso}" aria-label="Добавить урок ${day.getDate()} ${months[day.getMonth()]}">＋</button></div><div class="day-lessons" aria-label="Время с 09:00 до 22:00">${inGrid.map(item => card(item, true)).join('')}</div>${extra.length ? `<div class="day-extras"><div class="extras-title">Отменённые и вне сетки</div>${extra.map(item => card(item, false)).join('')}</div>` : ''}</section>`;
  }).join('');
  $('#school-calendar').querySelectorAll('.day-add').forEach(button => button.addEventListener('click', () => openNew(button.dataset.date)));
  $('#school-calendar').querySelectorAll('.day-lessons').forEach(grid => grid.addEventListener('click', event => { if (event.target === grid) openNew(grid.closest('.day-column').dataset.date, timeAtPoint(event.clientY, grid)); }));
  $('#school-calendar').querySelectorAll('.lesson-card').forEach(node => {
    node.querySelector('.lesson-open').addEventListener('click', () => openEdit(node.dataset.id));
    node.querySelectorAll('.quick-status').forEach(button => button.addEventListener('click', () => setStatus(node.dataset.id, button.dataset.status)));
    node.addEventListener('dragstart', event => { event.dataTransfer.setData('text/plain', node.dataset.id); event.dataTransfer.effectAllowed = 'move'; });
  });
  $('#school-calendar').querySelectorAll('.day-column').forEach(column => {
    column.addEventListener('dragover', event => { event.preventDefault(); column.classList.add('drop-target'); });
    column.addEventListener('dragleave', () => column.classList.remove('drop-target'));
    column.addEventListener('drop', async event => {
      event.preventDefault(); column.classList.remove('drop-target');
      const item = state.lessons.find(lesson => lesson.id === event.dataTransfer.getData('text/plain'));
      if (!item) return;
      const grid = event.target.closest('.day-lessons');
      const time = grid ? timeAtPoint(event.clientY, grid, item.duration_min) : item.time;
      if (item.date === column.dataset.date && item.time === time) return;
      try { await api(`/api/school/schedule/lessons/${item.id}`, 'PUT', {class_id: item.class_id, date: column.dataset.date, time, duration_min: item.duration_min, topic: item.topic, comment: item.comment, status: item.status}); state.date = localDate(column.dataset.date); await loadWeek(); toast('Урок перенесён'); }
      catch (error) { toast(error.message, true); }
    });
  });
  const first = active.filter(item => minutes(item.time) >= gridStart && minutes(item.time) + item.duration_min <= gridEnd).sort((a,b) => a.time.localeCompare(b.time))[0];
  $('.calendar-panel').scrollTop = first ? Math.max(0, (minutes(first.time) - gridStart - 60) * pixelsPerMinute) : 0;
}
function openNew(date = isoDate(new Date()), time = '09:00') {
  if (!state.classes.length) { toast('Сначала создайте класс в разделе «Классы»', true); return; }
  state.editing = null; $('#school-lesson-title').textContent = 'Новый урок'; formError('#school-lesson-error', '');
  $('#school-lesson-class').innerHTML = classOptions(state.filter || state.classes[0].id);
  $('#school-lesson-date').value = date; $('#school-lesson-time').value = time; $('#school-lesson-duration').value = 45;
  $('#school-lesson-topic').value = ''; $('#school-lesson-comment').value = ''; $('#school-lesson-status').value = 'planned'; $('#school-lesson-repeat').checked = false;
  $('#school-status-field').hidden = true; $('#school-repeat-field').hidden = false; $('#school-delete-lesson').hidden = true; $('#school-series-actions').hidden = true;
  lessonDialog.showModal();
}
function openEdit(id) {
  const item = state.lessons.find(lesson => lesson.id === id); if (!item) return;
  state.editing = item; $('#school-lesson-title').textContent = 'Изменить урок'; formError('#school-lesson-error', '');
  $('#school-lesson-class').innerHTML = classOptions(item.class_id); $('#school-lesson-date').value = item.date; $('#school-lesson-time').value = item.time; $('#school-lesson-duration').value = item.duration_min;
  $('#school-lesson-topic').value = item.topic; $('#school-lesson-comment').value = item.comment; $('#school-lesson-status').value = item.status;
  $('#school-status-field').hidden = false; $('#school-repeat-field').hidden = true; $('#school-delete-lesson').hidden = false; $('#school-series-actions').hidden = !item.recurring;
  lessonDialog.showModal();
}
function lessonPayload() { return {class_id: $('#school-lesson-class').value, date: $('#school-lesson-date').value, time: $('#school-lesson-time').value, duration_min: Number($('#school-lesson-duration').value), topic: $('#school-lesson-topic').value, comment: $('#school-lesson-comment').value, status: state.editing ? $('#school-lesson-status').value : 'planned', repeat_weekly: state.editing ? false : $('#school-lesson-repeat').checked}; }
async function setStatus(id, status) {
  try { await api(`/api/school/schedule/lessons/${id}`, 'PATCH', {status}); await loadWeek(); toast(status === 'completed' ? 'Урок отмечен проведённым' : 'Урок отменён'); }
  catch (error) { toast(error.message, true); }
}
async function saveLesson(event) {
  event.preventDefault(); const button = $('#school-lesson-form [type="submit"]'); button.disabled = true; formError('#school-lesson-error', '');
  try { await api(state.editing ? `/api/school/schedule/lessons/${state.editing.id}` : '/api/school/schedule/lessons', state.editing ? 'PUT' : 'POST', lessonPayload()); state.date = localDate($('#school-lesson-date').value); lessonDialog.close(); await loadWeek(); toast('Урок сохранён'); }
  catch (error) { formError('#school-lesson-error', error.message); }
  finally { button.disabled = false; }
}
function openSeries() {
  const item = state.editing; if (!item?.rule) return;
  $('#school-series-class').innerHTML = classOptions(item.rule.class_id);
  $('#school-series-weekday').value = item.rule.weekday; $('#school-series-time').value = item.rule.time; $('#school-series-duration').value = item.rule.duration_min; $('#school-series-topic').value = item.rule.topic;
  $('#school-series-from').textContent = `Изменения начнутся с ${localDate(item.source_date || item.date).toLocaleDateString('ru-RU')}. Уже изменённые вручную уроки сохранятся отдельно.`;
  formError('#school-series-error', ''); lessonDialog.close(); seriesDialog.showModal();
}
async function saveSeries(event) {
  event.preventDefault(); const item = state.editing, button = $('#school-series-form [type="submit"]'); button.disabled = true; formError('#school-series-error', '');
  try { await api(`/api/school/schedule/rules/${item.weekly_rule_id}`, 'PUT', {from_date: item.source_date || item.date, class_id: $('#school-series-class').value, weekday: Number($('#school-series-weekday').value), time: $('#school-series-time').value, duration_min: Number($('#school-series-duration').value), topic: $('#school-series-topic').value}); seriesDialog.close(); await loadWeek(); toast('Серия изменена'); }
  catch (error) { formError('#school-series-error', error.message); }
  finally { button.disabled = false; }
}
$('#prev-week').addEventListener('click', () => { state.date = addDays(state.date, -7); loadWeek(); });
$('#next-week').addEventListener('click', () => { state.date = addDays(state.date, 7); loadWeek(); });
$('#today-week').addEventListener('click', () => { state.date = new Date(); loadWeek(); });
$('#school-class-filter').addEventListener('change', event => { state.filter = event.target.value; renderCalendar(); });
$('#add-school-lesson').addEventListener('click', () => openNew());
document.querySelectorAll('.lesson-close').forEach(button => button.addEventListener('click', () => lessonDialog.close()));
document.querySelectorAll('.series-close').forEach(button => button.addEventListener('click', () => seriesDialog.close()));
lessonDialog.addEventListener('click', event => { if (event.target === lessonDialog) lessonDialog.close(); });
seriesDialog.addEventListener('click', event => { if (event.target === seriesDialog) seriesDialog.close(); });
$('#school-lesson-form').addEventListener('submit', saveLesson);
$('#school-series-form').addEventListener('submit', saveSeries);
$('#school-edit-series').addEventListener('click', openSeries);
$('#school-end-series').addEventListener('click', async () => {
  const item = state.editing; if (!item || !window.confirm('Завершить еженедельную серию начиная с этого урока?')) return;
  try { await api(`/api/school/schedule/rules/${item.weekly_rule_id}`, 'DELETE', {from_date: item.source_date || item.date}); lessonDialog.close(); await loadWeek(); toast('Серия завершена'); }
  catch (error) { formError('#school-lesson-error', error.message); }
});
$('#school-delete-lesson').addEventListener('click', async () => {
  const item = state.editing; if (!item || !window.confirm('Удалить этот урок?')) return;
  try { await api(`/api/school/schedule/lessons/${item.id}`, 'DELETE'); lessonDialog.close(); await loadWeek(); toast('Урок удалён'); }
  catch (error) { formError('#school-lesson-error', error.message); }
});
loadWeek();
