// Native disclosure remains usable without JavaScript; enhance dismissal behaviour.
const account = document.querySelector('[data-account-menu]');
if (account) {
  const toggle = account.querySelector('summary');
  account.addEventListener('toggle', () => {
    toggle.setAttribute('aria-expanded', String(account.open));
  });
  document.addEventListener('click', event => {
    if (!account.contains(event.target)) account.open = false;
  });
  document.addEventListener('focusin', event => {
    if (!account.contains(event.target)) account.open = false;
  });
  account.addEventListener('keydown', event => {
    if (event.key === 'Escape' && account.open) {
      account.open = false;
      toggle.focus();
      event.preventDefault();
    }
  });
}
