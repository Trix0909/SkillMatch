(() => {
  const page = document.querySelector('[data-connection-detail]');
  if (!page) return;

  page.querySelectorAll('[data-copy-contact]').forEach(button => {
    const container = button.closest('.rc-contact-value');
    const feedback = container.querySelector('.rc-copy-feedback');
    let timeout;
    button.addEventListener('click', async () => {
      clearTimeout(timeout);
      feedback.textContent = '';
      button.disabled = true;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(container.querySelector('[data-copy-value]').textContent);
        feedback.textContent = 'Copied';
        timeout = setTimeout(() => {
          feedback.textContent = '';
        }, 4000);
      } catch {
        feedback.textContent = 'Could not copy. Select and copy the text.';
      } finally {
        button.disabled = false;
      }
    });
  });

  page.querySelectorAll('[data-progress-cancel]').forEach(cancel => {
    cancel.addEventListener('click', event => {
      event.preventDefault();
      const disclosure = cancel.closest('[data-progress-disclosure]');
      disclosure.querySelector('form').reset();
      disclosure.open = false;
      disclosure.querySelector('summary').focus();
    });
  });
})();
