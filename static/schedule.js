const $ = (selector) => document.querySelector(selector);
const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const statusNames = {planned: 'Запланировано', completed: 'Состоялось', cancelled: 'Не состоялось'};
const priorityNames = {none: 'Без приоритета', low: 'Низкий', medium: 'Средний', high: 'Высокий'};
const gridStart = 9 * 60;
const gridEnd = 22 * 60;
const pixelsPerMinute = 1.2;
let currentDate = new Date();
let lessons = [];
let students = [];
let editing = null;
let editingCommentId = null;

function localDate(iso) { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); }
function isoDate(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; }
function addDays(date, days) { const result = new Date(date); result.setDate(result.getDate() + days); return result; }
function monday(date) { return addDays(date, -(date.getDay() + 6) % 7); }
function fullDate(date) { return `${date.getDate()} ${months[date.getMonth()]}`; }
function timeMinutes(value) { const [hours, minutes] = value.split(':').map(Number); return hours * 60 + minutes; }
function timeLabel(total) { return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`; }
function timeAtPoint(clientY, grid, duration = 60) {
  const minutes = gridStart + Math.round((clientY - grid.getBoundingClientRect().top) / pixelsPerMinute / 15) * 15;
  return timeLabel(Math.min(Math.max(minutes, gridStart), gridEnd - Math.min(duration, gridEnd - gridStart)));
}
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])); }
function cookie(name) { return document.cookie.split('; ').find(item => item.startsWith(`${name}=`))?.split('=')[1] || ''; }
function toast(message, error = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${error ? ' error' : ''}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = 'toast', 3500); }
function errorIn(dialog, message) { const el = $(dialog); el.textContent = message; el.hidden = !message; }

async function api(path, method = 'GET', payload) {
  const options = {method, headers: {'Accept': 'application/json'}};
  if (payload !== undefined) { options.headers['Content-Type'] = 'application/json'; options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken')); options.body = JSON.stringify(payload); }
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('Не удалось прочитать ответ сервера'); }
  if (!response.ok) throw new Error(data.error || 'Не удалось сохранить данные');
  return data;
}

async function loadWeek() {
  try {
    const data = await api(`/api/schedule/?week=${isoDate(currentDate)}`);
    lessons = data.lessons;
    students = data.students;
    renderCalendar(data.start, data.end);
  } catch (error) { toast(error.message, true); }
}

function renderCalendar(startIso, endIso) {
  const start = localDate(startIso), end = localDate(endIso);
  $('#week-label').textContent = start.getMonth() === end.getMonth()
    ? `${start.getDate()}–${end.getDate()} ${months[end.getMonth()]} ${end.getFullYear()}`
    : `${fullDate(start)} – ${fullDate(end)} ${end.getFullYear()}`;
  const active = lessons.filter(item => item.status !== 'cancelled');
  $('#lesson-total').textContent = `${active.length} ${plural(active.length, ['занятие', 'занятия', 'занятий'])}`;
  const hours = active.reduce((sum, item) => sum + item.duration_min, 0) / 60;
  $('#hours-total').textContent = `${Number.isInteger(hours) ? hours : hours.toFixed(1).replace('.', ',')} ч`;
  const todayIso = isoDate(new Date());
  const timeAxis = `<div class="time-axis" aria-hidden="true"><div class="time-axis-heading">Время</div><div class="time-axis-body">${Array.from({length: 14}, (_, index) => `<span class="time-mark" style="top:${index * 60 * pixelsPerMinute}px">${timeLabel(gridStart + index * 60)}</span>`).join('')}</div></div>`;
  $('#calendar').innerHTML = timeAxis + Array.from({length: 7}, (_, index) => {
    const day = addDays(start, index), dayIso = isoDate(day);
    const items = lessons.filter(item => item.date === dayIso).sort((a, b) => a.time.localeCompare(b.time));
    const inGrid = items.filter(item => item.status !== 'cancelled' && timeMinutes(item.time) >= gridStart && timeMinutes(item.time) + item.duration_min <= gridEnd);
    const extra = items.filter(item => !inGrid.includes(item));
    const extraTitle = extra.every(item => item.status === 'cancelled') ? 'Отменённые' : extra.some(item => item.status === 'cancelled') ? 'Отменённые и вне сетки' : 'Вне 09:00–22:00';
    return `<section class="day-column${dayIso === todayIso ? ' is-today' : ''}" data-date="${dayIso}">
      <div class="day-heading"><div><span class="day-name">${weekdays[index]}</span><strong>${day.getDate()}</strong></div><button class="day-add" data-date="${dayIso}" type="button" aria-label="Добавить занятие ${fullDate(day)}">＋</button></div>
      <div class="day-lessons" aria-label="Время с 09:00 до 22:00">${inGrid.map(item => lessonCard(item, true)).join('')}</div>
      ${extra.length ? `<div class="day-extras"><div class="extras-title">${extraTitle}</div>${extra.map(item => lessonCard(item, false)).join('')}</div>` : ''}
    </section>`;
  }).join('');
  $('#calendar').querySelectorAll('.day-add').forEach(button => button.addEventListener('click', () => openNew(button.dataset.date)));
  $('#calendar').querySelectorAll('.day-lessons').forEach(grid => grid.addEventListener('click', event => {
    if (event.target === grid) openNew(grid.closest('.day-column').dataset.date, timeAtPoint(event.clientY, grid));
  }));
  $('#calendar').querySelectorAll('.lesson-card').forEach(card => {
    card.querySelector('.lesson-open').addEventListener('click', () => openEdit(card.dataset.id));
    card.querySelectorAll('.quick-status').forEach(button => button.addEventListener('click', () => setLessonStatus(card.dataset.id, button.dataset.status)));
    card.addEventListener('dragstart', event => { event.dataTransfer.setData('text/plain', card.dataset.id); event.dataTransfer.effectAllowed = 'move'; });
  });
  $('#calendar').querySelectorAll('.day-column').forEach(column => {
    column.addEventListener('dragover', event => { event.preventDefault(); column.classList.add('drop-target'); });
    column.addEventListener('dragleave', () => column.classList.remove('drop-target'));
    column.addEventListener('drop', async event => {
      event.preventDefault(); column.classList.remove('drop-target');
      const item = lessons.find(lesson => lesson.id === event.dataTransfer.getData('text/plain'));
      if (!item) return;
      const targetGrid = event.target.closest('.day-lessons');
      const newTime = targetGrid ? timeAtPoint(event.clientY, targetGrid, item.duration_min) : item.time;
      if (item.date === column.dataset.date && item.time === newTime) return;
      try {
        await api(`/api/schedule/lessons/${item.id}`, 'PUT', {student_id:item.student_id, subject_id:item.subject_id, date:column.dataset.date, time:newTime, duration_min:item.duration_min, status:item.status});
        currentDate = localDate(column.dataset.date); await loadWeek(); toast('Занятие перенесено');
      } catch (error) { toast(error.message, true); }
    });
  });
  const firstVisible = active.filter(item => timeMinutes(item.time) >= gridStart && timeMinutes(item.time) + item.duration_min <= gridEnd)
    .sort((a, b) => a.time.localeCompare(b.time))[0];
  $('.calendar-panel').scrollTop = firstVisible
    ? Math.max(0, (timeMinutes(firstVisible.time) - gridStart - 60) * pixelsPerMinute)
    : 0;
}

function plural(n, forms) { const x = n % 100, y = n % 10; return x >= 11 && x <= 14 ? forms[2] : y === 1 ? forms[0] : y >= 2 && y <= 4 ? forms[1] : forms[2]; }
function lessonCard(item, positioned) {
  const classes = `${positioned && item.duration_min < 30 ? ' tiny' : positioned && item.duration_min < 50 ? ' compact' : positioned && item.duration_min < 90 ? ' short-card' : ''}${positioned ? '' : ' extra-card'}`;
  const placement = positioned ? ` style="top:${(timeMinutes(item.time) - gridStart) * pixelsPerMinute + 3}px;height:${Math.max(14, item.duration_min * pixelsPerMinute - 6)}px"` : '';
  const quickActions = !positioned || item.duration_min >= 60;
  return `<div class="lesson-card status-${item.status}${classes}${quickActions ? ' has-quick-actions' : ''}" data-id="${item.id}" draggable="true"${placement}>
    <button class="lesson-open" type="button" aria-label="${escapeHtml(item.student_name)}, ${item.time}, ${statusNames[item.status]}">
      <span class="lesson-time">${item.time}<span>${item.duration_min} мин</span></span>
      <strong>${escapeHtml(item.student_name)}</strong><span class="lesson-meta">${escapeHtml(item.subject_name)} · ${item.grade} класс${item.comments.length ? ` · 💬 ${item.comments.length}` : ''}</span>
      ${item.recurring ? '<span class="repeat-mark" title="Еженедельно">↻</span>' : ''}
      ${item.status !== 'planned' ? `<span class="lesson-status">${statusNames[item.status]}</span>` : ''}
    </button>
    ${quickActions ? `<div class="lesson-quick-actions"><button type="button" class="quick-status quick-done" data-status="completed" aria-label="Занятие состоялось" aria-pressed="${item.status === 'completed'}" title="Состоялось">✓ Да</button><button type="button" class="quick-status quick-cancel" data-status="cancelled" aria-label="Занятие не состоялось" aria-pressed="${item.status === 'cancelled'}" title="Не состоялось">× Нет</button></div>` : ''}
  </div>`;
}

async function setLessonStatus(id, requestedStatus) {
  const item = lessons.find(lesson => lesson.id === id);
  if (!item) return;
  const status = item.status === requestedStatus ? 'planned' : requestedStatus;
  try {
    const updated = await api(`/api/schedule/lessons/${id}`, 'PATCH', {status});
    await loadWeek();
    toast(status === 'completed' ? `Занятие состоялось · ${Number(updated.charged_price_rub || 0).toLocaleString('ru-RU')} ₽ начислено`
      : status === 'cancelled' ? 'Занятие не состоялось · начисления нет' : 'Занятие снова запланировано');
  } catch (error) { toast(error.message, true); }
}

function fillStudents(select, chosen = '') {
  select.innerHTML = `<option value="">Выберите ученика</option>${students.map(student => `<option value="${student.id}"${student.id === chosen ? ' selected' : ''}>${escapeHtml(student.name)} · ${student.grade} класс</option>`).join('')}`;
}
function fillSubjects(studentSelect, subjectSelect, chosen = '') {
  const student = students.find(item => item.id === studentSelect.value);
  subjectSelect.innerHTML = `<option value="">Без предмета</option>${(student?.subjects || []).map(subject => `<option value="${subject.id}"${subject.id === chosen ? ' selected' : ''}>${escapeHtml(subject.name)}</option>`).join('')}`;
}
function openNew(day = isoDate(new Date()), time = '16:00') {
  if (!students.length) { toast('Сначала добавьте ученика в разделе «Ученики»', true); return; }
  editing = null; $('#lesson-dialog-title').textContent = 'Новое занятие'; $('#lesson-form').reset();
  fillStudents($('#lesson-student')); fillSubjects($('#lesson-student'), $('#lesson-subject'));
  $('#lesson-date').value = day; $('#lesson-time').value = time; $('#lesson-duration').value = '60';
  $('#repeat-field').hidden = false; $('#status-field').hidden = true; $('#series-actions').hidden = true; $('#delete-lesson').hidden = true;
  $('#outcome-actions').hidden = true;
  $('#lesson-assignments-link').hidden = true;
  $('#comments-section').hidden = true; resetCommentComposer();
  errorIn('#lesson-error', ''); $('#lesson-dialog').showModal();
}
function openEdit(id) {
  editing = lessons.find(item => item.id === id); if (!editing) return;
  $('#lesson-dialog-title').textContent = 'Изменить занятие';
  fillStudents($('#lesson-student'), editing.student_id); fillSubjects($('#lesson-student'), $('#lesson-subject'), editing.subject_id);
  $('#lesson-date').value = editing.date; $('#lesson-time').value = editing.time; $('#lesson-duration').value = editing.duration_min;
  $('#lesson-status').value = editing.status;
  $('#repeat-field').hidden = true; $('#status-field').hidden = false; $('#series-actions').hidden = !editing.recurring;
  $('#outcome-actions').hidden = false;
  $('#lesson-assignments-link').hidden = false;
  $('#lesson-assignments-link').href = `/assignments/?student=${editing.student_id}&lesson=${editing.id}`;
  $('#delete-lesson').hidden = editing.recurring;
  $('#comments-section').hidden = false; resetCommentComposer(); renderComments();
  errorIn('#lesson-error', ''); $('#lesson-dialog').showModal();
}
function payloadFromForm() {
  return {student_id:$('#lesson-student').value, subject_id:$('#lesson-subject').value, date:$('#lesson-date').value,
    time:$('#lesson-time').value, duration_min:Number($('#lesson-duration').value),
    ...(editing ? {status:$('#lesson-status').value} : {repeat_weekly:$('#lesson-repeat').checked})};
}

function resetCommentComposer() {
  editingCommentId = null;
  $('#comment-body').value = '';
  $('#comment-priority').value = 'none';
  $('#comment-due-date').value = '';
  $('#comment-save').textContent = 'Добавить комментарий';
  $('#comment-cancel-edit').hidden = true;
  errorIn('#comment-error', '');
}

function renderComments() {
  const comments = editing?.comments || [];
  $('#comments-count').textContent = `${comments.length} ${plural(comments.length, ['комментарий', 'комментария', 'комментариев'])}`;
  $('#comments-list').innerHTML = comments.length ? comments.map(comment => {
    const overdue = comment.due_date && comment.due_date < isoDate(new Date());
    const deadline = comment.due_date ? `<span class="comment-deadline${overdue ? ' is-overdue' : ''}">До ${localDate(comment.due_date).toLocaleDateString('ru-RU')}${overdue ? ' · просрочено' : ''}</span>` : '';
    return `<article class="comment-item" data-id="${comment.id}">
      <div class="comment-meta"><span class="comment-priority priority-${comment.priority}">${priorityNames[comment.priority]}</span>${deadline}</div>
      <p>${escapeHtml(comment.body).replace(/\n/g, '<br>')}</p>
      <div class="comment-item-actions"><button class="text-button comment-edit" type="button">Изменить</button><button class="text-button danger-text comment-delete" type="button">Удалить</button></div>
    </article>`;
  }).join('') : '<p class="comments-empty">Комментариев пока нет.</p>';
}

async function refreshComments() {
  await loadWeek();
  editing = lessons.find(item => item.id === editing?.id) || editing;
  renderComments();
}

async function saveComment() {
  if (!editing) return;
  errorIn('#comment-error', '');
  const payload = {body:$('#comment-body').value, priority:$('#comment-priority').value, due_date:$('#comment-due-date').value || null};
  try {
    const wasEditing = Boolean(editingCommentId);
    await api(wasEditing ? `/api/schedule/comments/${editingCommentId}` : `/api/schedule/lessons/${editing.id}/comments`, wasEditing ? 'PUT' : 'POST', payload);
    resetCommentComposer(); await refreshComments(); toast(wasEditing ? 'Комментарий обновлён' : 'Комментарий добавлен');
  } catch (error) { errorIn('#comment-error', error.message); }
}
async function saveLesson(event) {
  event.preventDefault(); errorIn('#lesson-error', '');
  try {
    await api(editing ? `/api/schedule/lessons/${editing.id}` : '/api/schedule/lessons', editing ? 'PUT' : 'POST', payloadFromForm());
    currentDate = localDate($('#lesson-date').value); $('#lesson-dialog').close(); await loadWeek(); toast(editing ? 'Занятие обновлено' : 'Занятие добавлено');
  } catch (error) { errorIn('#lesson-error', error.message); }
}
function openSeries() {
  if (!editing?.rule) return;
  const item = editing;
  $('#series-from').textContent = `Изменения вступят в силу с ${fullDate(localDate(item.source_date))}. Уже изменённые вручную занятия сохранятся.`;
  fillStudents($('#series-student'), item.rule.student_id); fillSubjects($('#series-student'), $('#series-subject'), item.rule.subject_id);
  $('#series-weekday').value = item.rule.weekday; $('#series-time').value = item.rule.time; $('#series-duration').value = item.rule.duration_min;
  errorIn('#series-error', ''); $('#lesson-dialog').close(); $('#series-dialog').showModal();
}
async function saveSeries(event) {
  event.preventDefault(); errorIn('#series-error', '');
  try {
    await api(`/api/schedule/rules/${editing.weekly_rule_id}`, 'PUT', {from_date:editing.source_date, student_id:$('#series-student').value,
      subject_id:$('#series-subject').value, weekday:Number($('#series-weekday').value), time:$('#series-time').value, duration_min:Number($('#series-duration').value)});
    $('#series-dialog').close(); await loadWeek(); toast('Будущие занятия обновлены');
  } catch (error) { errorIn('#series-error', error.message); }
}

$('#prev-week').addEventListener('click', () => { currentDate = addDays(currentDate, -7); loadWeek(); });
$('#next-week').addEventListener('click', () => { currentDate = addDays(currentDate, 7); loadWeek(); });
$('#today-week').addEventListener('click', () => { currentDate = new Date(); loadWeek(); });
$('#add-lesson').addEventListener('click', () => openNew());
$('#lesson-student').addEventListener('change', () => { fillSubjects($('#lesson-student'), $('#lesson-subject')); $('#lesson-duration').value = students.find(item => item.id === $('#lesson-student').value)?.duration_min || 60; });
$('#series-student').addEventListener('change', () => fillSubjects($('#series-student'), $('#series-subject')));
$('#lesson-form').addEventListener('submit', saveLesson);
$('#comment-save').addEventListener('click', saveComment);
$('#comment-cancel-edit').addEventListener('click', resetCommentComposer);
$('#comments-list').addEventListener('click', async event => {
  const item = event.target.closest('.comment-item');
  if (!item || !editing) return;
  const comment = editing.comments.find(entry => entry.id === item.dataset.id);
  if (!comment) return;
  if (event.target.closest('.comment-edit')) {
    editingCommentId = comment.id;
    $('#comment-body').value = comment.body;
    $('#comment-priority').value = comment.priority;
    $('#comment-due-date').value = comment.due_date || '';
    $('#comment-save').textContent = 'Сохранить комментарий';
    $('#comment-cancel-edit').hidden = false;
    errorIn('#comment-error', '');
    $('#comment-body').focus();
  } else if (event.target.closest('.comment-delete') && confirm('Удалить этот комментарий?')) {
    try {
      await api(`/api/schedule/comments/${comment.id}`, 'DELETE', {});
      if (editingCommentId === comment.id) resetCommentComposer();
      await refreshComments(); toast('Комментарий удалён');
    } catch (error) { errorIn('#comment-error', error.message); }
  }
});
$('#outcome-completed').addEventListener('click', () => { $('#lesson-status').value = 'completed'; $('#lesson-form').requestSubmit(); });
$('#outcome-cancelled').addEventListener('click', () => { $('#lesson-status').value = 'cancelled'; $('#lesson-form').requestSubmit(); });
$('#series-form').addEventListener('submit', saveSeries);
document.querySelectorAll('.dialog-close').forEach(button => button.addEventListener('click', () => $('#lesson-dialog').close()));
document.querySelectorAll('.series-close').forEach(button => button.addEventListener('click', () => $('#series-dialog').close()));
$('#edit-series').addEventListener('click', openSeries);
$('#end-series').addEventListener('click', async () => {
  if (!editing || !confirm('Завершить эту серию с выбранного занятия? Будущие занятия серии исчезнут из расписания.')) return;
  try { await api(`/api/schedule/rules/${editing.weekly_rule_id}`, 'DELETE', {from_date:editing.source_date}); $('#lesson-dialog').close(); await loadWeek(); toast('Серия завершена'); }
  catch (error) { errorIn('#lesson-error', error.message); }
});
$('#delete-lesson').addEventListener('click', async () => {
  if (!editing || !confirm('Удалить это занятие?')) return;
  try { await api(`/api/schedule/lessons/${editing.id}`, 'DELETE', {}); $('#lesson-dialog').close(); await loadWeek(); toast('Занятие удалено'); }
  catch (error) { errorIn('#lesson-error', error.message); }
});
loadWeek();
