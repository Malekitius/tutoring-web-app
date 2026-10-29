const state = { students: [], current: null, query: "", editor: null };
const listEl = document.querySelector("#student-list");
const detailEl = document.querySelector("#detail-panel");
const loadMaterials = window.MaterialsPanel.attach(detailEl, "student");
const countEl = document.querySelector("#student-count");
const dialog = document.querySelector("#editor-dialog");
const form = document.querySelector("#editor-form");
const fieldsEl = document.querySelector("#dialog-fields");
const errorEl = document.querySelector("#form-error");
const toastEl = document.querySelector("#toast");
let toastTimer;

const masteryLabels = ["Не начали", "Нужна помощь", "Закрепляем", "Уверенно"];
const subjectIcons = JSON.parse(document.querySelector("#subject-icons-data").textContent);
const subjectIconById = Object.fromEntries(subjectIcons.map(icon => [icon.id, icon]));
const notePriorities = { none: "Без приоритета", low: "Низкий", medium: "Средний", high: "Высокий" };

function defaultSubjectIconId(name) {
  const normalized = name.trim().toLocaleLowerCase("ru");
  return subjectIcons.find(icon => icon.names.includes(normalized))?.id || "general";
}

function subjectIconId(subject) {
  return subjectIconById[subject.icon] ? subject.icon : defaultSubjectIconId(subject.name);
}

function formatDate(iso) {
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}.${month}.${year}`;
}

function esc(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map(part => part[0]?.toUpperCase() || "").join("");
}

function rubles(value) {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}

function message(text, error = false) {
  clearTimeout(toastTimer);
  toastEl.textContent = text;
  toastEl.className = "toast show" + (error ? " error" : "");
  toastTimer = setTimeout(() => toastEl.className = "toast", 3500);
}

async function api(path, options = {}) {
  const csrfToken = document.cookie.split("; ").find(part => part.startsWith("csrftoken="))?.split("=")[1];
  const response = await fetch(path, {
    ...options,
    headers: options.body
      ? { "Content-Type": "application/json", "X-CSRFToken": csrfToken || "" }
      : (options.method === "DELETE" ? { "X-CSRFToken": csrfToken || "" } : undefined)
  });
  let data;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.error || `Ошибка ${response.status}`);
  return data;
}

async function loadStudents(preferredId) {
  state.students = await api("/api/students");
  countEl.textContent = state.students.length;
  const saved = preferredId || state.current?.id || localStorage.getItem("selectedStudent");
  const nextId = state.students.some(student => student.id === saved) ? saved : state.students[0]?.id;
  state.current = nextId ? await api(`/api/students/${nextId}`) : null;
  if (nextId) localStorage.setItem("selectedStudent", nextId);
  else localStorage.removeItem("selectedStudent");
  render();
  if (nextId) loadMaterials(nextId);
}

async function loadCurrent() {
  if (!state.current) return;
  state.current = await api(`/api/students/${state.current.id}`);
  await loadStudents(state.current.id);
}

function renderList() {
  const query = state.query.trim().toLocaleLowerCase("ru");
  const visible = state.students.filter(student =>
    student.name.toLocaleLowerCase("ru").includes(query) || `${student.grade} класс`.includes(query)
  );
  if (!visible.length) {
    listEl.innerHTML = state.students.length
      ? `<div class="list-empty">По вашему запросу никого не найдено.</div>`
      : `<div class="list-empty"><span class="empty-symbol">∑</span>Здесь появятся ваши ученики.<br>Добавьте первую карточку.</div>`;
    return;
  }
  listEl.innerHTML = visible.map(student => `
    <button class="student-row ${student.id === state.current?.id ? "selected" : ""}"
      type="button" data-student-id="${esc(student.id)}" aria-current="${student.id === state.current?.id}">
      <span class="avatar">${esc(initials(student.name))}</span>
      <span class="student-row-body"><strong>${esc(student.name)}</strong>
        <small>${student.grade} класс · ${student.subject_count} предм. ${student.status === "paused" ? "· пауза" : ""}</small>
      </span><span class="row-chevron" aria-hidden="true">›</span>
    </button>`).join("");
}

function renderSubjects(student) {
  if (!student.subjects.length) {
    return `<div class="section-empty">Добавьте предмет и отметьте темы, которые изучаете.</div>`;
  }
  return `<div class="subject-list">${student.subjects.map(subject => `
    <article class="subject-card">
      <div class="subject-head">
        <div>
          <div class="subject-name"><span class="subject-icon" aria-hidden="true">${esc(subjectIconById[subjectIconId(subject)].symbol)}</span>${esc(subject.name)}</div>
          <div class="subject-meta">Уровень: ${esc(subject.level)} · ${subject.topics.length} тем</div>
          ${subject.goal ? `<p class="subject-goal">${esc(subject.goal)}</p>` : ""}
        </div>
        <div class="subject-actions">
          <button class="text-button" type="button" data-action="edit-subject" data-id="${esc(subject.id)}">Изменить</button>
          <button class="text-button" type="button" data-action="delete-subject" data-id="${esc(subject.id)}" aria-label="Удалить ${esc(subject.name)}">×</button>
        </div>
      </div>
      <div class="topic-list">
        ${subject.topics.length ? subject.topics.map(topic => `
          <div class="topic-row" title="${esc(topic.notes || "")}">
            <span class="topic-dot m${topic.mastery}" aria-hidden="true"></span>
            <span class="topic-title">${esc(topic.title)}</span>
            <span class="topic-level">${masteryLabels[topic.mastery]}</span>
            <button type="button" data-action="edit-topic" data-id="${esc(topic.id)}" aria-label="Изменить тему ${esc(topic.title)}">⋯</button>
          </div>`).join("") : `<div class="topic-empty">Пока нет тем. Добавьте первую, чтобы видеть прогресс.</div>`}
        <button class="mini-add" type="button" data-action="add-topic" data-id="${esc(subject.id)}">＋ Добавить тему</button>
      </div>
    </article>`).join("")}</div>`;
}

function renderNotes(notes) {
  if (!notes.length) return `<div class="section-empty">Заметок пока нет. Добавьте наблюдение или оставьте комментарий в занятии.</div>`;
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return `<div class="student-notes-list">${notes.map(note => {
    const source = note.lesson_date
      ? `Занятие ${formatDate(note.lesson_date)}${note.lesson_time ? ` · ${note.lesson_time}` : ""}`
      : `Добавлено ${new Date(note.created_at).toLocaleDateString("ru-RU")}`;
    const overdue = note.due_date && note.due_date < today;
    return `<article class="student-note">
      <div class="student-note-top"><span class="student-note-priority priority-${note.priority}">${notePriorities[note.priority]}</span>
        ${note.due_date ? `<span class="student-note-deadline${overdue ? " is-overdue" : ""}">До ${formatDate(note.due_date)}${overdue ? " · просрочено" : ""}</span>` : ""}
      </div>
      <p>${esc(note.body)}</p>
      <div class="student-note-bottom"><span>${source}</span><div><button class="text-button" type="button" data-action="edit-note" data-id="${esc(note.id)}">Изменить</button><button class="text-button danger-text" type="button" data-action="delete-note" data-id="${esc(note.id)}">Удалить</button></div></div>
    </article>`;
  }).join("")}</div>`;
}

function renderDetail() {
  const student = state.current;
  if (!student) {
    detailEl.innerHTML = `<div class="detail-empty">
      <div class="empty-illustration" aria-hidden="true">∑</div>
      <h2>Начните с первого ученика</h2>
      <p>Запишите цель, предметы и темы. К карточке можно добавить расписание, материалы и задания.</p>
      <button class="button button-primary" type="button" data-action="add-student">＋ Добавить ученика</button>
    </div>`;
    return;
  }
  const topicCount = student.subjects.reduce((sum, subject) => sum + subject.topics.length, 0);
  const confident = student.subjects.reduce((sum, subject) => sum + subject.topics.filter(topic => topic.mastery === 3).length, 0);
  detailEl.innerHTML = `
    <div class="detail-top">
      <div class="detail-intro">
        <div class="detail-avatar" aria-hidden="true">${esc(initials(student.name))}</div>
        <div><h2>${esc(student.name)}</h2>
          <div class="meta-line"><span>${student.grade} класс</span><span>•</span>
            <span class="status ${student.status}">${student.status === "active" ? "Занимается" : "На паузе"}</span>
          </div>
        </div>
      </div>
      <div class="detail-actions"><button class="button button-soft" type="button" data-action="ask-assistant">Спросить помощника</button><a class="button button-soft" href="/assignments/?student=${esc(student.id)}">Задания ученика</a><button class="button button-soft" type="button" data-action="edit-student">Редактировать</button></div>
    </div>
    <div class="section-title"><h3>Цель обучения</h3></div>
    <div class="goal-banner ${student.goal ? "" : "empty"}">${student.goal ? esc(student.goal) : "Например: укрепить школьную базу, подготовиться к контрольным или олимпиаде."}</div>
    <div class="stats-row">
      <div class="stat"><strong>${student.subjects.length}</strong><small>Предметов</small></div>
      <div class="stat"><strong>${topicCount}</strong><small>Тем в работе</small></div>
      <div class="stat"><strong>${confident}</strong><small>Освоено уверенно</small></div>
    </div>
    <div class="section-title"><h3>Предметы и темы</h3><button class="text-button" type="button" data-action="add-subject">＋ Добавить предмет</button></div>
    ${renderSubjects(student)}
    <div class="section-title"><h3>Занятия и ставка</h3><span>Стоимость применяется к новым занятиям</span></div>
    <div class="stats-row">
      <div class="stat"><strong>${student.duration_min} мин</strong><small>Длительность занятия</small></div>
      <div class="stat"><strong>${rubles(student.price_rub)}</strong><small>Стоимость занятия</small></div>
    </div>
    <div class="section-title"><h3>Заметки</h3><button class="text-button" type="button" data-action="add-note">＋ Добавить заметку</button></div>
    <p class="notes-order-hint">Сначала высокий приоритет, затем средний, низкий и без приоритета. Внутри уровня — по ближайшему дедлайну; без дедлайна — сначала новые.</p>
    ${renderNotes(student.notes)}
    <section class="materials-panel" data-materials-panel></section>
    <div class="foot-actions"><button class="text-button" type="button" data-action="delete-student">Удалить карточку ученика</button></div>`;
}

function render() { renderList(); renderDetail(); }

function field(label, name, value, type = "text", extra = "") {
  return `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
}

function area(label, name, value, placeholder = "") {
  return `<label class="field"><span>${label}</span><textarea name="${name}" placeholder="${esc(placeholder)}">${esc(value)}</textarea></label>`;
}

function select(label, name, choices, selected) {
  return `<label class="field"><span>${label}</span><select name="${name}">
    ${choices.map(([value, text]) => `<option value="${esc(value)}" ${String(value) === String(selected) ? "selected" : ""}>${esc(text)}</option>`).join("")}
  </select></label>`;
}

function openEditor(type, item = null, parentId = null) {
  state.editor = { type, item, parentId };
  errorEl.hidden = true;
  const editing = Boolean(item);
  let title = "";
  let markup = "";
  if (type === "student") {
    const data = item || { name: "", grade: 5, status: "active", goal: "", price_rub: 0, duration_min: 60 };
    title = editing ? "Изменить ученика" : "Новый ученик";
    markup = field("Имя и фамилия", "name", data.name, "text", "required maxlength=120 autofocus")
      + `<div class="field-row">${select("Класс", "grade", Array.from({ length: 11 }, (_, index) => [index + 1, `${index + 1} класс`]), data.grade)}
        ${select("Статус", "status", [["active", "Занимается"], ["paused", "На паузе"]], data.status)}</div>`
      + area("Общая цель", "goal", data.goal, "Например: уверенно решать задачи по школьной программе")
      + `<div class="field-row">${field("Стоимость, ₽", "price_rub", data.price_rub, "number", "min=0 max=1000000")}
        ${field("Длительность, мин", "duration_min", data.duration_min, "number", "min=15 max=240")}</div>`;
  } else if (type === "subject") {
    const data = item || { name: "", level: "базовый", goal: "" };
    state.editor.iconTouched = Boolean(item?.icon);
    const selectedIcon = subjectIconId(data);
    title = editing ? "Изменить предмет" : "Добавить предмет";
    markup = field("Предмет", "name", data.name, "text", 'list="subject-suggestions" required maxlength="80" placeholder="Например, алгебра" autofocus')
      + `<datalist id="subject-suggestions"><option value="Математика"><option value="Алгебра"><option value="Геометрия"><option value="Физика"><option value="Химия"></datalist>`
      + `<fieldset class="subject-icon-picker"><legend>Иконка предмета</legend><div class="subject-icon-options">${subjectIcons.map(icon => `
          <label class="subject-icon-option"><input type="radio" name="icon" value="${esc(icon.id)}" ${icon.id === selectedIcon ? "checked" : ""}>
            <span class="subject-icon-choice"><b aria-hidden="true">${esc(icon.symbol)}</b><small>${esc(icon.label)}</small></span>
          </label>`).join("")}</div></fieldset>`
      + select("Текущий уровень", "level", [["начальный", "Начальный"], ["базовый", "Базовый"], ["уверенный", "Уверенный"], ["продвинутый", "Продвинутый"]], data.level)
      + area("Цель по предмету", "goal", data.goal, "Например: научиться самостоятельно решать текстовые задачи");
  } else if (type === "topic") {
    const data = item || { title: "", mastery: 0, notes: "" };
    title = editing ? "Изменить тему" : "Добавить тему";
    markup = field("Название темы", "title", data.title, "text", "required maxlength=160 autofocus")
      + select("Освоение", "mastery", masteryLabels.map((label, index) => [index, label]), data.mastery)
      + area("Комментарий", "notes", data.notes, "Какие ошибки остаются, что повторить…");
    if (editing) markup += `<button class="text-button" type="button" data-action="delete-topic-in-dialog">Удалить тему</button>`;
  } else if (type === "note") {
    const data = item || { body: "", priority: "none", due_date: "" };
    title = editing ? "Изменить заметку" : "Новая заметка";
    markup = `<label class="field"><span>Заметка</span><textarea name="body" required maxlength="5000" autofocus placeholder="Наблюдение, задача или напоминание">${esc(data.body)}</textarea></label>`
      + `<div class="field-row">${select("Приоритет", "priority", [["none", "Без приоритета"], ["low", "Низкий"], ["medium", "Средний"], ["high", "Высокий"]], data.priority)}
        ${field("Дедлайн", "due_date", data.due_date || "", "date")}</div>`;
  }
  document.querySelector("#dialog-title").textContent = title;
  fieldsEl.innerHTML = markup;
  dialog.showModal();
  fieldsEl.querySelector("[autofocus], input, select")?.focus();
}

function closeEditor() { dialog.close(); state.editor = null; }

async function saveEditor(event) {
  event.preventDefault();
  const { type, item, parentId } = state.editor;
  const values = Object.fromEntries(new FormData(form));
  if (type === "student") {
    values.grade = Number(values.grade);
    values.price_rub = Number(values.price_rub);
    values.duration_min = Number(values.duration_min);
  }
  if (type === "topic") values.mastery = Number(values.mastery);
  const path = type === "student"
    ? (item ? `/api/students/${item.id}` : "/api/students")
    : type === "subject"
      ? (item ? `/api/subjects/${item.id}` : `/api/students/${parentId}/subjects`)
      : type === "topic"
        ? (item ? `/api/topics/${item.id}` : `/api/subjects/${parentId}/topics`)
        : (item ? `/api/notes/${item.id}` : `/api/students/${parentId}/notes`);
  const saveButton = document.querySelector("#save-dialog");
  saveButton.disabled = true;
  errorEl.hidden = true;
  try {
    const saved = await api(path, { method: item ? "PUT" : "POST", body: JSON.stringify(values) });
    closeEditor();
    await loadStudents(type === "student" ? saved.id : state.current?.id);
    message("Сохранено");
  } catch (error) {
    errorEl.textContent = error.message;
    errorEl.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
}

async function deleteEntity(type, id) {
  const phrases = {
    student: `Карточка «${state.current?.name || 'ученика'}» и связанные предметы, занятия, материалы, задания и финансовые записи будут удалены.`,
    subject: "Удалить предмет вместе со всеми его темами?",
    topic: "Удалить эту тему?",
    note: "Удалить эту заметку? Она исчезнет и из занятия, если была добавлена там."
  };
  if (!await window.AppDialogs.confirm(phrases[type], {title: type === 'student' ? 'Удалить ученика?' : 'Удалить запись?'})) return;
  try {
    await api(`/api/${type === "student" ? "students" : type === "subject" ? "subjects" : type === "topic" ? "topics" : "notes"}/${id}`, { method: "DELETE" });
    if (type === "student") state.current = null;
    if (dialog.open) closeEditor();
    await loadStudents();
    message("Удалено");
  } catch (error) { message(error.message, true); }
}

document.querySelector("#add-student").addEventListener("click", () => openEditor("student"));
document.querySelector("#search").addEventListener("input", event => { state.query = event.target.value; renderList(); });
document.querySelector("#close-dialog").addEventListener("click", closeEditor);
document.querySelector("#cancel-dialog").addEventListener("click", closeEditor);
dialog.addEventListener("click", event => { if (event.target === dialog) closeEditor(); });
form.addEventListener("submit", saveEditor);
listEl.addEventListener("click", async event => {
  const button = event.target.closest("[data-student-id]");
  if (!button) return;
  try {
    state.current = await api(`/api/students/${button.dataset.studentId}`);
    localStorage.setItem("selectedStudent", state.current.id);
    render();
  } catch (error) { message(error.message, true); }
});
detailEl.addEventListener("click", event => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const { action, id } = button.dataset;
  const student = state.current;
  if (action === "add-student") return openEditor("student");
  if (action === "ask-assistant") return window.dispatchEvent(new CustomEvent("assistant:open", { detail: { studentName: student.name } }));
  if (action === "edit-student") return openEditor("student", student);
  if (action === "delete-student") return deleteEntity("student", student.id);
  if (action === "add-note") return openEditor("note", null, student.id);
  const note = student.notes.find(item => item.id === id);
  if (action === "edit-note") return openEditor("note", note);
  if (action === "delete-note") return deleteEntity("note", id);
  if (action === "add-subject") return openEditor("subject", null, student.id);
  const subject = student.subjects.find(item => item.id === id);
  if (action === "edit-subject") return openEditor("subject", subject);
  if (action === "delete-subject") return deleteEntity("subject", id);
  if (action === "add-topic") return openEditor("topic", null, id);
  const topic = student.subjects.flatMap(item => item.topics).find(item => item.id === id);
  if (action === "edit-topic") return openEditor("topic", topic);
});
fieldsEl.addEventListener("click", event => {
  if (event.target.dataset.action === "delete-topic-in-dialog") deleteEntity("topic", state.editor.item.id);
});
fieldsEl.addEventListener("input", event => {
  if (state.editor?.type !== "subject") return;
  if (event.target.name === "icon") state.editor.iconTouched = true;
  if (event.target.name === "name" && !state.editor.iconTouched) {
    const icon = fieldsEl.querySelector(`input[name="icon"][value="${defaultSubjectIconId(event.target.value)}"]`);
    if (icon) icon.checked = true;
  }
});
dialog.addEventListener("close", () => { state.editor = null; });

loadStudents().catch(error => {
  detailEl.innerHTML = `<div class="detail-empty"><h2>Не удалось загрузить данные</h2><p>${esc(error.message)}</p></div>`;
  message(error.message, true);
});
