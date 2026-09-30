// Reflect the existing Django role selector; submission and role assignment stay unchanged.
const authRole = document.querySelector('.sm-auth #id_role');
if (authRole) {
  const roleBadge = document.querySelector('[data-role-badge]');
  const roleHelper = document.querySelector('[data-role-helper]');
  const storyHeadline = document.querySelector('[data-role-headline]');
  const storyCopy = document.querySelector('[data-role-story]');
  const reflectRole = () => {
    const employer = authRole.value === 'employer';
    roleBadge.textContent = employer ? 'Employer' : authRole.value === 'seeker' ? 'Job Seeker' : 'Choose account type';
    roleHelper.textContent = employer ?
      'Find the skills your business needs. Complete your company profile after signup.' :
      'Take the first step. Add your skills and professional profile after signup.';
    const accent = document.createElement('em');
    accent.textContent = employer ? 'great hire' : 'opportunity';
    storyHeadline.replaceChildren('Your next ', accent,
      employer ? ' starts here.' : ' starts with you.');
    storyCopy.textContent = employer ?
      'Build your team with Kenyan professionals whose skills and experience fit your business.' :
      'Let your skills and experience open doors. Connect with opportunities that help you grow.';
  };
  authRole.addEventListener('change', reflectRole);
  window.addEventListener('pageshow', reflectRole);
  reflectRole();
}

document.querySelectorAll('[data-password-toggle]').forEach(button => {
  const input = document.getElementById(button.getAttribute('aria-controls'));
  const label = button.getAttribute('aria-label').slice(5);
  button.hidden = false;
  button.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(show));
    button.setAttribute('aria-label', `${show ? 'Hide' : 'Show'} ${label}`);
  });
});
