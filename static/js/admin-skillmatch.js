/* Admin-only enhancements. Native forms and the chart remain server-rendered. */
(() => {
  document.querySelectorAll('.sm-avatar img').forEach(photo => {
    const showInitials = () => photo.remove();
    photo.addEventListener('error', showInitials);
    if (photo.complete && !photo.naturalWidth) showInitials();
  });
  const toggle = document.querySelector('.sm-menu-toggle');
  const sidebar = document.querySelector('.sm-sidebar');

  function closeNavigation() {
    document.body.classList.remove('sm-navigation-open');
    toggle?.setAttribute('aria-expanded', 'false');
  }
  toggle?.addEventListener('click', () => {
    const open = document.body.classList.toggle('sm-navigation-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', event => {
    if (sidebar && !sidebar.contains(event.target) && !toggle?.contains(event.target)) closeNavigation();
    document.querySelectorAll('.sm-account-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      const search = document.getElementById('sm-admin-search');
      if (search) {
        event.preventDefault();
        search.focus();
      }
    }
    if (event.key === 'Escape') {
      if (document.body.classList.contains('sm-navigation-open')) toggle?.focus();
      closeNavigation();
      document.querySelectorAll('.sm-account-menu[open]').forEach(menu => {
        menu.open = false;
        menu.querySelector('summary').focus();
      });
    }
  });
  document.querySelectorAll('.sm-period-form').forEach(form => {
    form.querySelector('.sm-period-submit').hidden = true;
    form.querySelector('select').addEventListener('change', () => form.requestSubmit());
  });
})();
