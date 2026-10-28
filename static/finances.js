const $ = selector => document.querySelector(selector);
const rub = value => `${Number(value || 0).toLocaleString('ru-RU')} ₽`;
const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
let mode = 'month';
let selectedRange = null;
let students = [];
let payments = [];
let editingPayment = null;
let openingStudent = null;

function isoDate(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; }
function localDate(value) { const [y,m,d] = value.split('-').map(Number); return new Date(y,m-1,d); }
function dateLabel(value) { const date = localDate(value); return `${date.getDate()} ${months[date.getMonth()]}`; }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;'}[char])); }
function cookie(name) { return document.cookie.split('; ').find(item => item.startsWith(`${name}=`))?.split('=')[1] || ''; }
function toast(message, error = false) { const el = $('#toast'); el.textContent = message; el.className = `toast show${error ? ' error' : ''}`; clearTimeout(toast.timer); toast.timer = setTimeout(() => el.className = 'toast', 3500); }
function setError(selector, message) { const el = $(selector); el.textContent = message; el.hidden = !message; }
function plural(n, forms) { const x=n%100,y=n%10; return x>=11&&x<=14?forms[2]:y===1?forms[0]:y>=2&&y<=4?forms[1]:forms[2]; }

async function api(path, method = 'GET', payload) {
  const options = {method, headers: {'Accept':'application/json'}};
  if (payload !== undefined) { options.headers['Content-Type']='application/json'; options.headers['X-CSRFToken']=decodeURIComponent(cookie('csrftoken')); options.body=JSON.stringify(payload); }
  const response = await fetch(path, options);
  let data; try { data = await response.json(); } catch { throw new Error('Не удалось прочитать ответ сервера'); }
  if (!response.ok) throw new Error(data.error || 'Не удалось сохранить данные');
  return data;
}

function rangeFor(period) {
  const today = new Date();
  if (period === 'week') {
    const monday = new Date(today); monday.setDate(today.getDate() - (today.getDay() + 6) % 7);
    const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
    return {start:isoDate(monday), end:isoDate(sunday)};
  }
  return {start:isoDate(new Date(today.getFullYear(),today.getMonth(),1)),end:isoDate(new Date(today.getFullYear(),today.getMonth()+1,0))};
}

async function loadDashboard() {
  if (!selectedRange) selectedRange = rangeFor(mode);
  try {
    const data = await api(`/api/finances/?start=${selectedRange.start}&end=${selectedRange.end}`);
    students = data.students; payments = data.payments;
    render(data);
  } catch (error) { toast(error.message, true); }
}

function render(data) {
  $('#period-label').textContent = `${dateLabel(data.start)} — ${dateLabel(data.end)} ${localDate(data.end).getFullYear()}`;
  $('#received-value').textContent = rub(data.summary.received_rub);
  $('#received-detail').textContent = `${data.summary.payment_count} ${plural(data.summary.payment_count,['внесение','внесения','внесений'])}`;
  $('#earned-value').textContent = rub(data.summary.earned_rub);
  $('#earned-detail').textContent = `${data.summary.completed_count} ${plural(data.summary.completed_count,['проведённое занятие','проведённых занятия','проведённых занятий'])}`;
  $('#forecast-value').textContent = rub(data.summary.forecast_rub);
  $('#forecast-detail').textContent = `Проведено: ${data.summary.completed_count} · запланировано: ${data.summary.planned_count}`;
  $('#student-balances').innerHTML = students.length ? students.map(studentCard).join('') : '<div class="finance-empty">Сначала добавьте учеников в разделе «Ученики».</div>';
  $('#payments-count').textContent = payments.length;
  $('#payment-list').innerHTML = payments.length ? payments.map(paymentRow).join('') : '<div class="finance-empty">За выбранный период внесений пока нет.</div>';
  document.querySelectorAll('.balance-pay').forEach(button => button.addEventListener('click', () => openPayment(null, button.dataset.student)));
  document.querySelectorAll('.balance-opening').forEach(button => button.addEventListener('click', () => openOpening(button.dataset.student)));
  document.querySelectorAll('.edit-payment').forEach(button => button.addEventListener('click', () => openPayment(button.dataset.id)));
}

function studentCard(item) {
  let remaining;
  if (item.balance_state === 'no_price') remaining = 'Стоимость занятия не задана';
  else if (item.balance_rub < 0) remaining = `Долг ${rub(-item.balance_rub)} · 0 занятий`;
  else remaining = `Хватит на ${item.remaining_lessons} ${plural(item.remaining_lessons,['занятие','занятия','занятий'])}`;
  return `<article class="balance-card ${item.balance_state}">
    <div class="balance-head"><div><strong>${escapeHtml(item.name)}</strong><small>${item.grade} класс${item.status === 'paused' ? ' · на паузе' : ''}</small></div><span class="count-pill">${item.price_rub ? `${rub(item.price_rub)} / урок` : 'Цена не задана'}</span></div>
    <span class="balance-amount">${rub(item.balance_rub)}</span><div class="balance-remaining">${remaining}</div>
    <div class="balance-meta">Внесено: ${rub(item.paid_rub)} · Начислено: ${rub(item.charged_rub)}</div>
    <div class="balance-actions"><button class="text-button balance-pay" data-student="${item.id}" type="button">＋ Внести деньги</button><button class="text-button balance-opening" data-student="${item.id}" type="button">Начальный остаток</button></div>
  </article>`;
}

function paymentRow(item) {
  return `<div class="payment-row"><span class="payment-date">${dateLabel(item.paid_on)}</span><strong>${escapeHtml(item.student_name)} · ${item.grade} класс</strong><span class="payment-note" title="${escapeHtml(item.note)}">${escapeHtml(item.note) || '—'}</span><span class="payment-amount">+ ${rub(item.amount_rub)}</span><button class="text-button edit-payment" data-id="${item.id}" type="button">Изменить</button></div>`;
}

function fillStudentOptions(chosen = '') {
  $('#payment-student').innerHTML = `<option value="">Выберите ученика</option>${students.map(item => `<option value="${item.id}"${item.id === chosen ? ' selected' : ''}>${escapeHtml(item.name)} · ${item.grade} класс</option>`).join('')}`;
}

function openPayment(id = null, studentId = '') {
  if (!students.length) { toast('Сначала добавьте ученика', true); return; }
  editingPayment = payments.find(item => item.id === id) || null;
  $('#payment-dialog-title').textContent = editingPayment ? 'Изменить внесение' : 'Добавить внесение';
  $('#payment-form').reset(); fillStudentOptions(editingPayment?.student_id || studentId);
  $('#payment-amount').value = editingPayment?.amount_rub || '';
  $('#payment-date').value = editingPayment?.paid_on || isoDate(new Date());
  $('#payment-note').value = editingPayment?.note || '';
  $('#delete-payment').hidden = !editingPayment;
  setError('#payment-error',''); $('#payment-dialog').showModal();
}

async function savePayment(event) {
  event.preventDefault(); setError('#payment-error','');
  const payload = {student_id:$('#payment-student').value,paid_on:$('#payment-date').value,amount_rub:Number($('#payment-amount').value),note:$('#payment-note').value};
  try {
    await api(editingPayment ? `/api/finances/payments/${editingPayment.id}` : '/api/finances/payments', editingPayment ? 'PUT' : 'POST', payload);
    $('#payment-dialog').close(); await loadDashboard(); toast('Внесение сохранено');
  } catch (error) { setError('#payment-error',error.message); }
}

function openOpening(studentId) {
  openingStudent = students.find(item => item.id === studentId); if (!openingStudent) return;
  $('#opening-student-name').textContent = `${openingStudent.name} · ${openingStudent.grade} класс`;
  $('#opening-amount').value = openingStudent.opening_balance_rub;
  setError('#opening-error',''); $('#opening-dialog').showModal();
}

async function saveOpening(event) {
  event.preventDefault(); setError('#opening-error','');
  try {
    await api(`/api/finances/students/${openingStudent.id}/opening-balance`, 'PUT', {opening_balance_rub:Number($('#opening-amount').value)});
    $('#opening-dialog').close(); await loadDashboard(); toast('Начальный остаток сохранён');
  } catch (error) { setError('#opening-error',error.message); }
}

document.querySelectorAll('.period-tab').forEach(button => button.addEventListener('click', () => {
  mode = button.dataset.mode;
  document.querySelectorAll('.period-tab').forEach(tab => tab.classList.toggle('active', tab === button));
  $('#custom-dates').hidden = mode !== 'custom';
  if (mode === 'custom') {
    $('#period-start').value = selectedRange?.start || rangeFor('month').start;
    $('#period-end').value = selectedRange?.end || rangeFor('month').end;
  } else { selectedRange = rangeFor(mode); loadDashboard(); }
}));
$('#apply-period').addEventListener('click', () => {
  const start=$('#period-start').value,end=$('#period-end').value;
  if (!start || !end || end < start) { toast('Проверьте даты периода',true); return; }
  selectedRange={start,end}; loadDashboard();
});
$('#add-payment').addEventListener('click', () => openPayment());
$('#payment-form').addEventListener('submit',savePayment);
$('#opening-form').addEventListener('submit',saveOpening);
document.querySelectorAll('.payment-close').forEach(button => button.addEventListener('click', () => $('#payment-dialog').close()));
document.querySelectorAll('.opening-close').forEach(button => button.addEventListener('click', () => $('#opening-dialog').close()));
$('#delete-payment').addEventListener('click', async () => {
  if (!editingPayment || !confirm('Удалить это внесение? Баланс ученика будет пересчитан.')) return;
  try { await api(`/api/finances/payments/${editingPayment.id}`,'DELETE',{}); $('#payment-dialog').close(); await loadDashboard(); toast('Внесение удалено'); }
  catch (error) { setError('#payment-error',error.message); }
});
$('#finance-export-csv').addEventListener('click', event => {
  event.currentTarget.href = `/api/finances/export/csv?start=${selectedRange.start}&end=${selectedRange.end}`;
});
const importDialog = $('#finance-import-dialog');
const importSubmit = $('#finance-import-submit');
let importReady = false;
async function uploadFinances(dryRun) {
  const fields = new FormData();
  fields.append('file', $('#finance-import-file').files[0]);
  if (!dryRun) fields.append('confirm', 'IMPORT');
  const response = await fetch(`/api/finances/import${dryRun ? '?dry_run=1' : ''}`, {
    method:'POST', headers:{'X-CSRFToken':decodeURIComponent(cookie('csrftoken'))}, body:fields
  });
  let data; try { data = await response.json(); } catch { throw new Error('Сервер вернул некорректный ответ'); }
  if (!response.ok) throw new Error(data.error || `Ошибка ${response.status}`);
  return data;
}
$('#finance-import-open').addEventListener('click', () => {
  $('#finance-import-form').reset(); importReady = false; importSubmit.disabled = true;
  $('#finance-import-preview').hidden = true; setError('#finance-import-error',''); importDialog.showModal();
});
document.querySelectorAll('.finance-import-close').forEach(button => button.addEventListener('click', () => importDialog.close()));
$('#finance-import-file').addEventListener('change', async () => {
  importReady = false; importSubmit.disabled = true; $('#finance-import-preview').hidden = true;
  setError('#finance-import-error','');
  if (!$('#finance-import-file').files.length) return;
  try {
    const data = await uploadFinances(true);
    const preview = $('#finance-import-preview');
    preview.textContent = `Новых внесений: ${data.payments_new}\nИзменятся внесения: ${data.payments_updated}\nИзменятся цены и начальные остатки: ${data.students_updated}\nИзменятся начисления за занятия: ${data.lessons_updated}\n\nВ файле: получено ${rub(data.received_rub)}, начислено ${rub(data.charged_rub)}.`+
      (data.missing_students.length ? `\nОтсутствуют ученики: ${data.missing_students.length}.` : '')+
      (data.missing_lessons.length ? `\nОтсутствуют занятия: ${data.missing_lessons.length}.` : '')+
      (data.conflicts.length ? `\nКонфликты: ${data.conflicts.join('; ')}` : '')+
      (!data.can_import ? '\nДля переноса на другое устройство используйте полную резервную копию.' : '');
    preview.hidden = false; importReady = data.can_import; importSubmit.disabled = !importReady;
  } catch (cause) { setError('#finance-import-error',cause.message); }
});
$('#finance-import-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!importReady) return;
  importSubmit.disabled = true; setError('#finance-import-error','');
  try { await uploadFinances(false); importDialog.close(); await loadDashboard(); toast('Финансовые данные загружены'); }
  catch (cause) { setError('#finance-import-error',cause.message); importSubmit.disabled = false; }
});
selectedRange = rangeFor('month');
loadDashboard();
