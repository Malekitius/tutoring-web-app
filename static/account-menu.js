(() => {
  const menu = document.querySelector('.account-menu');
  if (!menu) return;

  document.addEventListener('click', event => {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (menu.open && event.key === 'Escape') {
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });
  menu.querySelector('[data-open-assistant]').addEventListener('click', () => {
    menu.open = false;
    window.dispatchEvent(new Event('assistant:open'));
  });
})();
