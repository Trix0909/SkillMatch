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

  const thread = page.querySelector('[data-chat-server-time]');
  if (thread) {
    // This clock only hides expired controls. Every POST is checked again by Django.
    const serverTime = Date.parse(thread.dataset.chatServerTime);
    const started = performance.now();
    const check = () => {
      const now = serverTime + performance.now() - started;
      thread.querySelectorAll('[data-message-until]').forEach(message => {
        if (now < Date.parse(message.dataset.messageUntil)) return;
        const menu = message.querySelector('.rc-message-menu');
        if (menu) {
          menu.open = false;
          menu.hidden = true;
        }
        message.querySelectorAll('form button[type="submit"]').forEach(button => {
          button.disabled = true;
        });
        const feedback = message.querySelector('.rc-message-expiry');
        if (feedback) feedback.hidden = false;
        message.removeAttribute('data-message-until');
      });
    };
    check();
    const timer = setInterval(check, 1000);
    window.addEventListener('pagehide', () => clearInterval(timer), {
      once: true
    });
  }
})();
