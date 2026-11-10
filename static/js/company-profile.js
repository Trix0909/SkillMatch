// Presentation only: these previews never send a request or persist form values.
(() => {
  const editor = document.querySelector('[data-company-editor]');
  if (!editor) return;
  const form = editor.querySelector('#company-profile-form');
  const value = name => form.elements.namedItem(name).value.trim();
  const normalize = text => text.normalize('NFKC').trim().replace(/\s+/g, ' ');
  const focusField = form.elements.namedItem('focus_areas');
  const focusValues = () => focusField.value.split(/\r?\n/).map(normalize).filter(Boolean);
  const validFocus = () => {
    const names = focusValues();
    return names.length <= 3 && names.every(name => [...name].length <= 40) &&
      new Set(names.map(name => name.toLowerCase())).size === names.length ? names : [];
  };
  const selectedText = name => {
    const select = form.elements.namedItem(name);
    return select.value ? select.selectedOptions[0].textContent : '';
  };
  const safeLink = text => {
    if (!text || /\s/.test(text)) return null;
    try {
      const url = new URL(/^[a-z][a-z\d+.-]*:/i.test(text) ? text : `https://${text}`);
      return ['http:', 'https:'].includes(url.protocol) &&
        (url.hostname.includes('.') || url.hostname === 'localhost') ? url.href : null;
    } catch (_) {
      return null;
    }
  };
  const update = () => {
    const data = {};
    ['company_name', 'tagline', 'location', 'summary', 'description', 'workplace_culture'].forEach(name => {
      data[name] = value(name);
    });
    data.company_size = selectedText('company_size');
    data.industry = selectedText('industry');
    data.focus_areas = validFocus();
    const links = [
        ['website', 'Website'],
        ['linkedin', 'LinkedIn'],
        ['twitter', 'X / Twitter']
      ]
      .map(([name, label]) => ({
        label,
        url: safeLink(value(name))
      })).filter(link => link.url);
    editor.querySelectorAll('[data-cp-text]').forEach(node => {
      const name = node.dataset.cpText;
      node.textContent = data[name] || (name === 'company_name' ? 'Your company' : '');
    });
    editor.querySelectorAll('[data-cp-initial]').forEach(node => {
      node.textContent = [...(data.company_name || 'Your company')][0].toUpperCase();
    });
    editor.querySelectorAll('[data-cp-focus]').forEach(node => {
      node.replaceChildren(...data.focus_areas.map(name => {
        const pill = document.createElement('span');
        pill.className = 'cp-pill';
        pill.textContent = name;
        return pill;
      }));
    });
    editor.querySelectorAll('[data-cp-links]').forEach(node => {
      node.replaceChildren(...links.map(link => {
        const anchor = document.createElement('a');
        anchor.textContent = `${link.label} ↗`;
        anchor.href = link.url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.setAttribute('aria-label', `${link.label} (opens in a new tab)`);
        return anchor;
      }));
    });
    editor.querySelectorAll('[data-cp-section]').forEach(node => {
      const name = node.dataset.cpSection;
      node.hidden = name === 'tags' ? !(data.industry || data.focus_areas.length) :
        name === 'links' ? !links.length : !data[name];
    });
    editor.querySelectorAll('[data-cp-empty]').forEach(node => {
      const item = data[node.dataset.cpEmpty];
      node.hidden = Array.isArray(item) ? item.length > 0 : Boolean(item);
    });
    const essentials = ['company_name', 'tagline', 'location', 'company_size', 'industry',
      'summary', 'description', 'workplace_culture', 'focus_areas'
    ];
    const completed = essentials.filter(name => name === 'focus_areas' ? data[name].length : data[name]).length;
    const percent = Math.round(completed * 100 / essentials.length);
    const progress = editor.querySelector('.cp-progress');
    progress.style.setProperty('--progress', `${percent}%`);
    progress.setAttribute('aria-valuenow', percent);
    editor.querySelector('[data-cp-percent]').textContent = `${percent}%`;
    editor.querySelector('[data-cp-completed]').textContent = completed;
    editor.querySelector('[data-cp-strength-bar]').style.width = `${percent}%`;
    const checks = {
      ...data,
      identity: data.company_name && data.tagline,
      location_size: data.location && data.company_size,
      focus_areas: data.industry && data.focus_areas.length,
      links: links.length
    };
    editor.querySelectorAll('[data-cp-check]').forEach(node => {
      const complete = Boolean(checks[node.dataset.cpCheck]);
      node.classList.toggle('is-complete', complete);
      node.querySelector('.cp-check-mark').textContent = complete ? '✓' : '+';
      node.querySelector('[data-cp-check-status]').textContent = complete ? ' — Added' : ' — Not added';
    });
    editor.querySelectorAll('[data-counter-for]').forEach(node => {
      const field = document.getElementById(node.dataset.counterFor);
      node.textContent = `${[...field.value].length}/${field.maxLength}`;
    });
  };

  // Progressive enhancement of the same newline-based Django field.
  // Without JavaScript it remains an ordinary, server-validated textarea.
  const focusEditor = editor.querySelector('[data-focus-editor]');
  const controls = focusEditor.querySelector('.cp-focus-controls');
  const entry = controls.querySelector('input');
  const focusError = controls.querySelector('[role=status]');
  const tags = controls.querySelector('[data-focus-tags]');
  const renderFocus = () => {
    const names = focusValues();
    tags.replaceChildren(...names.map((name, index) => {
      const pill = document.createElement('span');
      pill.className = 'cp-pill';
      const text = document.createElement('span');
      text.textContent = name;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `Remove ${name}`);
      remove.addEventListener('click', () => {
        names.splice(index, 1);
        focusField.value = names.join('\n');
        focusError.textContent = '';
        entry.removeAttribute('aria-invalid');
        renderFocus();
        update();
        entry.focus();
      });
      pill.append(text, remove);
      return pill;
    }));
  };
  const addFocus = () => {
    const name = normalize(entry.value);
    const names = focusValues();
    let error = '';
    if (!name) error = 'Enter a focus area first.';
    else if ([...name].length > 40) error = 'Use at most 40 characters per focus area.';
    else if (names.some(item => item.toLowerCase() === name.toLowerCase())) error = 'This focus area is already added.';
    else if (names.length >= 3) error = 'You can add up to 3 focus areas.';
    focusError.textContent = error;
    if (error) {
      entry.setAttribute('aria-invalid', 'true');
      entry.focus();
      return false;
    }
    names.push(name);
    focusField.value = names.join('\n');
    entry.value = '';
    entry.removeAttribute('aria-invalid');
    renderFocus();
    update();
    entry.focus();
    return true;
  };
  focusField.hidden = true;
  focusEditor.querySelector('label').htmlFor = entry.id;
  if (focusField.getAttribute('aria-invalid') === 'true') {
    entry.setAttribute('aria-invalid', 'true');
    entry.setAttribute('aria-describedby', `${entry.getAttribute('aria-describedby')} id_focus_areas_error`);
  }
  controls.hidden = false;
  editor.querySelectorAll('[data-cp-fill]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault();
      const field = link.dataset.cpFill === 'focus_areas' ? entry : form.elements.namedItem(link.dataset.cpFill);
      field.scrollIntoView({
        block: 'center'
      });
      field.focus({
        preventScroll: true
      });
    });
  });
  controls.querySelector('[data-add-focus]').addEventListener('click', addFocus);
  entry.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      addFocus();
    }
  });
  form.addEventListener('submit', event => {
    if (entry.value.trim() && !addFocus()) event.preventDefault();
  });
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  renderFocus();
  update();

  // Native dialog supplies focus containment and Escape handling.
  const dialog = editor.querySelector('#company-live-preview');
  const opener = editor.querySelector('[data-open-preview]');
  if (typeof dialog.showModal === 'function') {
    opener.hidden = false;
    opener.addEventListener('click', () => {
      update();
      dialog.showModal();
      document.body.classList.add('company-preview-open');
      dialog.querySelector('[data-close-preview]').focus();
    });
    dialog.querySelector('[data-close-preview]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('keydown', event => {
      if (event.key !== 'Tab') return;
      const focusable = [...dialog.querySelectorAll('button:not([disabled]), a[href]')]
        .filter(node => node.getClientRects().length);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.addEventListener('click', event => {
      const rect = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right ||
          event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
    });
    dialog.addEventListener('close', () => {
      document.body.classList.remove('company-preview-open');
      opener.focus({
        preventScroll: true
      });
    });
  }
})();
