(() => {
  const $ = selector => document.querySelector(selector);
  const panel = $('#helper-panel');
  const toggle = $('#helper-toggle');
  const form = $('#helper-form');
  const cookie = name => document.cookie.split('; ').find(part => part.startsWith(`${name}=`))?.split('=')[1] || '';

  async function api(path, method = 'GET', payload) {
    const options = {method, headers: {'Accept': 'application/json'}};
    if (payload !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'));
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) {
      if (data.error?.includes('Подключите ChatGPT заново')) window.dispatchEvent(new Event('assistant:connection-expired'));
      throw new Error(data.error || `Ошибка ${response.status}`);
    }
    return data;
  }

  function appendInline(parent, source) {
    const token = /(`[^`\n]+`|\$\$[\s\S]+?\$\$|\$[^$\n]+\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_)/g;
    let start = 0;
    for (const match of source.matchAll(token)) {
      parent.append(document.createTextNode(source.slice(start, match.index)));
      const value = match[0];
      if (value.startsWith('`')) {
        const code = document.createElement('code');
        code.textContent = value.slice(1, -1);
        parent.append(code);
      } else if (value.startsWith('$') || value.startsWith('\\(') || value.startsWith('\\[')) {
        parent.append(document.createTextNode(value));
      } else if (value.startsWith('[')) {
        const parts = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(value);
        const link = document.createElement('a');
        link.textContent = parts[1];
        link.href = parts[2];
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        parent.append(link);
      } else {
        const strong = value.startsWith('**') || value.startsWith('__');
        const element = document.createElement(strong ? 'strong' : 'em');
        element.textContent = value.slice(strong ? 2 : 1, strong ? -2 : -1);
        parent.append(element);
      }
      start = match.index + value.length;
    }
    parent.append(document.createTextNode(source.slice(start)));
  }

  function renderAnswer(root, answer) {
    root.replaceChildren();
    const lines = String(answer ?? '').replace(/\r\n?/g, '\n').split('\n');
    for (let index = 0; index < lines.length;) {
      const line = lines[index];
      if (!line.trim()) { index++; continue; }
      if (/^\s*```/.test(line)) {
        const code = [];
        index++;
        while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
        if (index < lines.length) index++;
        const pre = document.createElement('pre');
        const inner = document.createElement('code');
        inner.textContent = code.join('\n');
        pre.append(inner);
        root.append(pre);
        continue;
      }
      if (/^\s*(?:\$\$|\\\[)/.test(line)) {
        const closing = /^\s*\\\[/.test(line) ? '\\]' : '$$';
        const math = [line];
        index++;
        if (!line.slice(line.indexOf(closing) + closing.length).includes(closing)) {
          while (index < lines.length) {
            const next = lines[index++];
            math.push(next);
            if (next.includes(closing)) break;
          }
        }
        const block = document.createElement('div');
        block.className = 'helper-math-block';
        block.textContent = math.join('\n');
        root.append(block);
        continue;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      if (heading) {
        const element = document.createElement(`h${Math.min(heading[1].length + 2, 6)}`);
        appendInline(element, heading[2]);
        root.append(element);
        index++;
        continue;
      }
      const list = /^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/.exec(line);
      if (list) {
        const ordered = Boolean(list[2]);
        const element = document.createElement(ordered ? 'ol' : 'ul');
        while (index < lines.length) {
          const item = /^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/.exec(lines[index]);
          if (!item || Boolean(item[2]) !== ordered) break;
          const li = document.createElement('li');
          appendInline(li, item[3]);
          element.append(li);
          index++;
        }
        root.append(element);
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = document.createElement('blockquote');
        while (index < lines.length && /^>\s?/.test(lines[index])) {
          if (quote.childNodes.length) quote.append(document.createElement('br'));
          appendInline(quote, lines[index++].replace(/^>\s?/, ''));
        }
        root.append(quote);
        continue;
      }
      const paragraph = document.createElement('p');
      while (index < lines.length && lines[index].trim() && !/^\s*```|^\s*(?:\$\$|\\\[)|^#{1,4}\s|^\s*(?:[-*+]|\d+\.)\s|^>\s?/.test(lines[index])) {
        if (paragraph.childNodes.length) paragraph.append(document.createElement('br'));
        appendInline(paragraph, lines[index++]);
      }
      if (!paragraph.childNodes.length) appendInline(paragraph, lines[index++]);
      root.append(paragraph);
    }
    if (typeof window.renderMathInElement === 'function') window.renderMathInElement(root, {
      delimiters: [
        {left: '$$', right: '$$', display: true},
        {left: '\\[', right: '\\]', display: true},
        {left: '\\(', right: '\\)', display: false},
        {left: '$', right: '$', display: false},
      ],
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      throwOnError: false, trust: false, strict: 'ignore',
    });
  }

  function show(open) {
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Скрыть помощника' : 'Открыть помощника');
    if (open) form.elements.question.focus();
  }

  toggle.addEventListener('click', () => show(panel.hidden));
  $('#helper-close').addEventListener('click', () => show(false));
  window.addEventListener('assistant:open', event => {
    if (event.detail?.studentName) form.elements.question.value = `Что важно учесть на следующем занятии для ученика «${event.detail.studentName}»?`;
    show(true);
  });
  window.addEventListener('assistant:connection-expired', () => {
    $('#helper-status').textContent = 'Сессия ChatGPT истекла. Подключите ChatGPT заново.';
    $('#helper-connect').hidden = false;
    $('#helper-disconnect').hidden = true;
    show(true);
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) show(false); });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    $('#helper-error').hidden = true;
    $('#helper-answer').hidden = true;
    $('#helper-loading').hidden = false;
    panel.setAttribute('aria-busy', 'true');
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      const result = await api('/api/assistant/ask', 'POST', Object.fromEntries(new FormData(form).entries()));
      renderAnswer($('#helper-answer'), result.answer);
      $('#helper-answer').hidden = false;
    } catch (error) {
      $('#helper-error').textContent = error.message;
      $('#helper-error').hidden = false;
    } finally {
      $('#helper-loading').hidden = true;
      panel.removeAttribute('aria-busy');
      button.disabled = false;
    }
  });

  $('#helper-connect').addEventListener('click', async () => {
    try {
      const result = await api('/api/assistant/auth/start', 'POST', {return_to: location.pathname});
      location.href = result.url;
    } catch (error) { $('#helper-status').textContent = error.message; }
  });
  $('#helper-disconnect').addEventListener('click', async () => {
    try {
      const result = await api('/api/assistant/auth/disconnect', 'POST', {});
      $('#helper-status').textContent = result.revoked ? 'ChatGPT отключён' : 'Отключено локально; проверьте доступ в настройках ChatGPT';
      $('#helper-connect').hidden = false;
      $('#helper-disconnect').hidden = true;
    } catch (error) { $('#helper-status').textContent = error.message; }
  });

  async function init() {
    try {
      const status = await api('/api/assistant/status');
      const params = new URLSearchParams(location.search);
      $('#helper-status').textContent = status.message;
      $('#helper-connect').hidden = status.ready;
      $('#helper-disconnect').hidden = status.mode !== 'chatgpt_plan';
      if (params.has('auth_error') || params.has('connected')) {
        if (params.has('auth_error')) $('#helper-status').textContent = params.get('auth_error');
        show(true);
        history.replaceState(null, '', location.pathname);
      }
    } catch (error) { $('#helper-status').textContent = error.message; }
  }
  init();
})();
