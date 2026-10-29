(() => {
  let dialog;
  let notice;
  let noticeTimer;

  function confirm(message, options = {}) {
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'app-confirm';
      dialog.setAttribute('aria-labelledby', 'app-confirm-title');
      dialog.setAttribute('aria-describedby', 'app-confirm-message');
      dialog.innerHTML = `<div class="app-confirm-card">
        <span class="app-confirm-icon" aria-hidden="true">!</span>
        <span class="app-confirm-eyebrow">ПОДТВЕРЖДЕНИЕ</span>
        <h2 id="app-confirm-title"></h2>
        <p id="app-confirm-message"></p>
        <form method="dialog" class="app-confirm-actions">
          <button class="button button-secondary" value="cancel" type="submit">Отмена</button>
          <button class="button button-danger" value="confirm" type="submit" data-confirm-action></button>
        </form>
      </div>`;
      dialog.addEventListener('click', event => {
        if (event.target === dialog) dialog.close('cancel');
      });
      document.body.append(dialog);
    }
    if (dialog.open) return Promise.resolve(false);
    const previousFocus = document.activeElement;
    dialog.classList.toggle('is-neutral', options.danger === false);
    dialog.querySelector('#app-confirm-title').textContent = options.title || 'Подтвердите действие';
    dialog.querySelector('#app-confirm-message').textContent = message;
    dialog.querySelector('[data-confirm-action]').textContent = options.confirmText || 'Удалить';
    dialog.returnValue = 'cancel';
    return new Promise(resolve => {
      dialog.addEventListener('close', () => {
        previousFocus?.focus?.();
        resolve(dialog.returnValue === 'confirm');
      }, {once: true});
      dialog.showModal();
      dialog.querySelector('[value="cancel"]').focus();
    });
  }

  function notify(message, error = false) {
    if (!notice) {
      notice = document.createElement('div');
      notice.className = 'app-notice';
      document.body.append(notice);
    }
    clearTimeout(noticeTimer);
    notice.textContent = message;
    notice.className = `app-notice is-visible${error ? ' is-error' : ''}`;
    notice.setAttribute('role', error ? 'alert' : 'status');
    noticeTimer = setTimeout(() => notice.classList.remove('is-visible'), 4500);
  }

  window.AppDialogs = {confirm, notify};
})();
