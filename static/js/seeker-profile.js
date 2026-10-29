// One form, with anchor navigation. Preview uses the existing saved-profile page.
const profileSteps = [...document.querySelectorAll('[data-profile-step]')];
if (profileSteps.length) {
  const sections = profileSteps.map(step => document.getElementById(step.dataset.profileStep));
  const markStep = index => {
    profileSteps.forEach((step, i) => {
      if (i === index) step.setAttribute('aria-current', 'step');
      else step.removeAttribute('aria-current');
    });
  };
  profileSteps.forEach((step, index) => {
    step.addEventListener('click', () => markStep(index));
  });
  let scheduled = false;
  document.addEventListener('scroll', () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      let index = 0;
      sections.forEach((section, i) => {
        if (section.getBoundingClientRect().top <= 120) index = i;
      });
      markStep(index);
      scheduled = false;
    });
  }, {
    passive: true
  });
}
