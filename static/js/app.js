document.querySelectorAll('[data-skill-editor]').forEach(editor => {
  const hidden = editor.querySelector('input[type=hidden]');
  const input = editor.querySelector('#skill-entry');
  const tags = editor.querySelector('[data-skill-tags]');
  const error = editor.querySelector('[data-skill-error]');
  let skills = [];
  try { const data = JSON.parse(hidden.value || '[]'); if (Array.isArray(data)) skills = data.filter(s => typeof s === 'string'); } catch (_) { /* Server renders validation for malformed input. */ }
  const normalized = s => s.normalize('NFKC').trim().replace(/\s+/g, ' ');
  const render = () => {
    tags.replaceChildren();
    skills.forEach((name, i) => {
      const tag = document.createElement('span'); tag.className = 'skill-tag editable';
      tag.append(document.createTextNode(name));
      const button = document.createElement('button'); button.type = 'button'; button.textContent = '×';
      button.setAttribute('aria-label', `Remove ${name}`);
      button.addEventListener('click', () => { skills.splice(i, 1); render(); input.focus(); });
      tag.append(button); tags.append(tag);
    });
    hidden.value = JSON.stringify(skills);
  };
  const add = () => {
    error.textContent = '';
    const value = normalized(input.value);
    if (!value) { error.textContent = 'Enter a skill first.'; input.focus(); return false; }
    if (value.length > 80) { error.textContent = 'Use at most 80 characters per skill.'; return false; }
    if (skills.some(s => normalized(s).toLowerCase() === value.toLowerCase())) { error.textContent = 'This skill is already added.'; return false; }
    if (skills.length >= 40) { error.textContent = 'You can add up to 40 skills.'; return false; }
    skills.push(value); input.value = ''; render(); input.focus(); return true;
  };
  editor.querySelector('[data-add-skill]').addEventListener('click', add);
  input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); add(); } });
  editor.closest('form').addEventListener('submit', event => {
    if (input.value.trim() && !add()) { event.preventDefault(); return; }
    if (!skills.length) { event.preventDefault(); error.textContent = 'Add at least one skill.'; input.focus(); }
  });
  render();
});
const role = document.getElementById('id_role');
const company = document.querySelector('[data-company-field]');
if (role && company) {
  const update = () => { company.hidden = role.value !== 'employer'; const input = company.querySelector('input'); if (input) input.required = role.value === 'employer'; };
  role.addEventListener('change', update); update();
}
