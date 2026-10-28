const $ = selector => document.querySelector(selector);
const dialog = $('#restore-dialog');
const form = $('#restore-form');
const submit = $('#restore-submit');
let previewReady = false;

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
  if (confirm) values.append('confirm', 'RESTORE');
  return values;
}
function count(map, keys) { return keys.reduce((sum, key) => sum + (map[key] || 0), 0); }
function summary(map) {
  return `Ученики: ${count(map,['students.student'])} · предметы и темы: ${count(map,['students.subject','students.topic'])}\n`+
    `Расписание: ${count(map,['schedule.weeklyrule','schedule.lesson'])} · заметки: ${count(map,['schedule.lessoncomment'])}\n`+
    `Школа: ${count(map,['school.schoolclass'])} классов, ${count(map,['school.schoolstudent'])} учеников, ${count(map,['school.schoollesson'])} уроков\n`+
    `Задачи и подборки: ${count(map,['assignments.exercise','assignments.worksheet'])} · работы: ${count(map,['assignments.submission'])}\n`+
    `Внесения: ${count(map,['finances.payment'])}`;
}

$('#restore-open').addEventListener('click', () => { form.reset(); previewReady = false; submit.disabled = true; $('#restore-preview').hidden = true; error(''); dialog.showModal(); });
document.querySelectorAll('.restore-close').forEach(button => button.addEventListener('click', () => dialog.close()));
$('#restore-file').addEventListener('change', async () => {
  previewReady = false; submit.disabled = true; $('#restore-preview').hidden = true; error('');
  if (!$('#restore-file').files.length) return;
  try {
    const data = await upload('/api/data/backup/preview', formData());
    const preview = $('#restore-preview');
    preview.textContent = `Архив создан: ${new Date(data.created_at).toLocaleString('ru-RU')}\n\nВ архиве:\n${summary(data.archive)}\n\nСейчас в приложении:\n${summary(data.current)}\n\nТекущие данные будут заменены целиком.`;
    preview.hidden = false; previewReady = true; submit.disabled = false;
  } catch (cause) { error(cause.message); }
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!previewReady || !window.confirm('Заменить все текущие данные содержимым архива?')) return;
  submit.disabled = true; error('');
  try {
    const result = await upload('/api/data/backup/restore', formData(true));
    dialog.close();
    toast(`Данные восстановлены. Копия прежних данных: ${result.recovery_file}`);
  } catch (cause) { error(cause.message); submit.disabled = false; }
});
