// Native details navigation still works if JavaScript is unavailable.
const landingMenu = document.querySelector('.sm-mobile-nav');
if (landingMenu) {
  landingMenu.addEventListener('click', event => {
    if (event.target.closest('a')) landingMenu.open = false;
  });
  landingMenu.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      landingMenu.open = false;
      landingMenu.querySelector('summary').focus();
    }
  });
}
