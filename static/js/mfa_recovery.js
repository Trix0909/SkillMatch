(() => {
  const list = document.querySelector('[data-recovery-codes]');
  if (!list) return;
  const status = document.querySelector('[data-recovery-status]');
  const text = () => 'SkillMatch one-time recovery codes\nStore these securely. Each code can be used once, after your password.\n\n' +
    Array.from(list.querySelectorAll('code'), node => node.textContent).join('\n') + '\n';
  document.querySelector('[data-recovery-actions]').hidden = false;
  document.querySelector('[data-recovery-copy]').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(text());
      status.textContent = 'Recovery codes copied. Store them securely.';
    } catch {
      status.textContent = 'Copy is unavailable. Select the codes above to copy them, or download them.';
    }
  });
  document.querySelector('[data-recovery-download]').addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([text()], {
      type: 'text/plain;charset=utf-8'
    }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'skillmatch-recovery-codes.txt';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = 'Recovery codes downloaded. Store the file securely.';
  });
  window.addEventListener('pagehide', () => {
    list.replaceChildren();
    document.querySelector('[data-recovery-actions]').hidden = true;
    status.textContent = 'For your security, these codes are no longer displayed. Return to security settings to generate a new set.';
  });
})();
