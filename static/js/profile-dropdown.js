(() => {
  document.querySelectorAll('[data-profile-dropdown]').forEach(dropdown => {
    const trigger = dropdown.querySelector('summary');
    const panel = dropdown.querySelector('.profile-menu');
    const items = [...panel.querySelectorAll('a[href], button[type="submit"]')];
    const position = () => {
      if (!dropdown.open) return;
      panel.style.transform = '';
      const bounds = panel.getBoundingClientRect();
      const shift = Math.max(0, 12 - bounds.left) - Math.max(0, bounds.right - innerWidth + 12);
      if (shift) panel.style.transform = `translateX(${shift}px)`;
      panel.style.setProperty('--profile-menu-top', `${Math.max(0, bounds.top)}px`);
    };
    const close = (returnFocus = false) => {
      dropdown.open = false;
      trigger.setAttribute('aria-expanded', 'false');
      if (returnFocus) trigger.focus();
    };
    dropdown.addEventListener('toggle', () => {
      trigger.setAttribute('aria-expanded', String(dropdown.open));
      position();
    });
    document.addEventListener('click', event => {
      if (!dropdown.contains(event.target)) close();
    });
    document.addEventListener('focusin', event => {
      if (!dropdown.contains(event.target)) close();
    });
    dropdown.addEventListener('keydown', event => {
      if (event.key === 'Escape' && dropdown.open) {
        event.preventDefault();
        close(true);
        return;
      }
      const current = items.indexOf(document.activeElement);
      let next;
      if (event.key === 'ArrowDown') next = current < 0 ? 0 : (current + 1) % items.length;
      if (event.key === 'ArrowUp') next = current < 0 ? items.length - 1 : (current - 1 + items.length) % items.length;
      if (dropdown.open && event.key === 'Home') next = 0;
      if (dropdown.open && event.key === 'End') next = items.length - 1;
      if (next !== undefined) {
        event.preventDefault();
        dropdown.open = true;
        trigger.setAttribute('aria-expanded', 'true');
        position();
        items[next].focus();
      }
    });
    window.addEventListener('resize', position);
  });
})();
