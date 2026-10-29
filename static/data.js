const $ = selector => document.querySelector(selector);
const dialog = $('#restore-dialog');
const form = $('#restore-form');
const submit = $('#restore-submit');
let previewReady = false;
let selectedScope = 'all';
let previewSerial = 0;
const scopeNames = {all:'Все данные', tutoring:'Репетиторство', school:'Школа'};
const replaceDescription = scope => scope === 'all'
  ? 'Все данные приложения и общая библиотека будут заменены содержимым архива.'
  : `Будут заменены только данные раздела «${scopeNames[scope]}». Другой режим и общая библиотека сохранятся.`;

function cookie(name) { return document.cookie.split('; ').find(item => item.startsWith(`${name}=`))?.split('=')[1] || ''; }
function error(message) { const el = $('#restore-error'); el.textContent = message || ''; el.hidden = !message; }
function toast(message, failed = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${failed ? ' error' : ''}`; setTimeout(() => el.className = 'toast', 5000); }
async function upload(path, fields) {
  const response = await fetch(path, {method:'POST', headers:{'X-CSRFToken':decodeURIComponent(cookie('csrftoken'))}, body:fields});
  let data; try { data = await response.json(); } catch { throw new Error('Сервер вернул некорректный ответ'); }
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}
function formData(confirm = false) {
  const values = new FormData();
  values.append('file', $('#restore-file').files[0]);
  values.append('scope', selectedScope);
  if (confirm) values.append('confirm', 'RESTORE');
  return values;
}
function count(map, keys) { return keys.reduce((sum, key) => sum + (map[key] || 0), 0); }
function summary(map) {
  if (selectedScope === 'school') return `Классы: ${count(map,['school.schoolclass'])} · ученики: ${count(map,['school.schoolstudent'])}\n`+
    `Уроки и серии: ${count(map,['school.schoollesson','school.schoolweeklyrule'])}\n`+
    `Подборки: ${count(map,['school.schoolworksheet'])} · задачи в подборках: ${count(map,['school.schoolworksheetitem'])}\n`+
    `Материалы: ${count(map,['materials.material'])} · рисунки: ${count(map,['assignments.taskfigure'])}`;
  if (selectedScope === 'tutoring') return `Ученики: ${count(map,['students.student'])} · предметы и темы: ${count(map,['students.subject','students.topic'])}\n`+
    `Расписание: ${count(map,['schedule.weeklyrule','schedule.lesson'])} · заметки: ${count(map,['schedule.lessoncomment'])}\n`+
    `Подборки: ${count(map,['assignments.worksheet'])} · задачи в подборках: ${count(map,['assignments.worksheetitem'])}\n`+
    `Материалы: ${count(map,['materials.material'])} · рисунки: ${count(map,['assignments.taskfigure'])}\n`+
    `Работы: ${count(map,['assignments.submission'])} · внесения: ${count(map,['finances.payment'])}`;
  return `Ученики: ${count(map,['students.student'])} · предметы и темы: ${count(map,['students.subject','students.topic'])}\n`+
    `Расписание: ${count(map,['schedule.weeklyrule','schedule.lesson'])} · заметки: ${count(map,['schedule.lessoncomment'])}\n`+
    `Школа: ${count(map,['school.schoolclass'])} классов, ${count(map,['school.schoolstudent'])} учеников, ${count(map,['school.schoollesson'])} уроков, ${count(map,['school.schoolworksheet'])} подборок\n`+
    `PDF-материалы: ${count(map,['materials.material'])} файлов\n`+
    `Задачи и подборки: ${count(map,['assignments.exercise','assignments.worksheet'])} · работы: ${count(map,['assignments.submission'])}\n`+
    `Внесения: ${count(map,['finances.payment'])}`;
}

document.querySelectorAll('[data-restore-scope]').forEach(button => button.addEventListener('click', () => {
  selectedScope = button.dataset.restoreScope;
  previewSerial++;
  form.reset(); previewReady = false; submit.disabled = true; $('#restore-preview').hidden = true; error('');
  $('#restore-title').textContent = `Восстановить: ${scopeNames[selectedScope].toLowerCase()}`;
  $('#restore-description').textContent = `${replaceDescription(selectedScope)} Перед заменой приложение сохранит резервную копию.`;
  submit.textContent = selectedScope === 'all' ? 'Заменить все данные' : `Заменить данные: ${scopeNames[selectedScope].toLowerCase()}`;
  dialog.showModal();
}));
document.querySelectorAll('.restore-close').forEach(button => button.addEventListener('click', () => dialog.close()));
$('#restore-file').addEventListener('change', async () => {
  const serial = ++previewSerial;
  previewReady = false; submit.disabled = true; $('#restore-preview').hidden = true; error('');
  if (!$('#restore-file').files.length) return;
  try {
    const data = await upload('/api/data/backup/preview', formData());
    if (serial !== previewSerial) return;
    const preview = $('#restore-preview');
    preview.textContent = `Архив создан: ${new Date(data.created_at).toLocaleString('ru-RU')}\n\nВ архиве:\n${summary(data.archive)}\n\nСейчас в этом разделе:\n${summary(data.current)}\n\n${replaceDescription(selectedScope)}`;
    preview.hidden = false; previewReady = true; submit.disabled = false;
  } catch (cause) { if (serial === previewSerial) error(cause.message); }
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!previewReady || !await window.AppDialogs.confirm(`${replaceDescription(selectedScope)} Перед восстановлением приложение создаст резервную копию.`, {title: `Восстановить: ${scopeNames[selectedScope].toLowerCase()}?`, confirmText: 'Восстановить', danger: false})) return;
  submit.disabled = true; error('');
  try {
    const result = await upload('/api/data/backup/restore', formData(true));
    dialog.close();
    toast(`Данные восстановлены. Копия прежних данных: ${result.recovery_file}`);
  } catch (cause) { error(cause.message); submit.disabled = false; }
});
