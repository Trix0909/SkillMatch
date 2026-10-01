# Authentication design review

Login and signup share `templates/registration/auth_base.html`, which reuses the approved landing-page fonts, colours, logo and buttons. The corrected composition follows the supplied login visual target: a full-height 59/41 split (56/44 on smaller desktops), an integrated professional photograph and editorial copy on the left, and an ivory form surface on the right. The former navbar, outer margins and floating card are removed from these two pages. Home links remain on the two logos. Authentication-specific layout and form rules live in `static/css/auth.css`; other screens are not affected. Both pages reuse the existing locally hosted professional photograph.

The editorial area includes sage circular value icons and restrained decorative botanical SVGs. Signup's headline and supporting copy follow the real selected role. At mobile widths the shorter image/brand area stacks above the form.

Both pages now render the same `registration/story.html` partial. Shared headline and supporting-copy minimum heights keep the logo, eyebrow, text and value points on the same grid for login and either signup role. The photograph crop, panel width, padding, botanical decoration and desktop sticky behaviour are identical. Registration's existing role badge sits beside its heading and wraps below it on narrow mobile screens. Form controls and their styling are unchanged.

Registration's shorter headline is inset downward within its reserved block to reduce the gap before its supporting copy. This registration-only spacing refinement leaves all other element positions unchanged, including the logo, eyebrow, photograph, decoration, value points and form. Login is unaffected. Browser comparison at eight viewport sizes confirmed those boundaries for both registration roles; captures are in ignored `tmp/registration-spacing/`.

The viewport refinement removes the old 850 px minimum on the image column and uses viewport-aware desktop headline/spacing rules. Login fits a single normal desktop viewport; signup and validation content may scroll naturally. Existing input heights, radii and icon placement are preserved. Typed/focused inputs retain the ivory surface, and standard/WebKit autofill selectors use an inset ivory fill with navy text without disabling saved credentials. Both pages share the Better opportunities, Transparent matching and Real impact value points.

## Preserved behaviour

- Login still submits Django's username/password fields to the current URL with CSRF and the original hidden `next` value. No email login, password-reset route or social login was introduced.
- Signup still submits the existing role, first name, last name, username, email, password, confirmation and conditional company-name fields. The existing shared signup page is where the role is selected; there is no separate Get Started role-selection route.
- The role badge and helper text reflect the real role selector. The existing `app.js` continues to manage company-name visibility and its employer-only browser requirement. `auth.js` updates the badge, helper text and editorial copy, and enables keyboard-accessible password visibility controls. Visibility buttons are hidden when JavaScript is unavailable.
- The existing Django bound fields render their values, validation errors and password guidance. The authentication field partial supplies help-text/error IDs for accessibility. Forms submit normally without JavaScript.
- Views, models, URL patterns, authentication, server validation, role assignment and redirects are unchanged. No profile fields were added to signup.

## Review checks

All 40 existing tests and the full development check command passed. Browser review covered login and both signup roles at 320, 390, 768, 1024, 1440 and 1672 px, without horizontal overflow or missing assets. It also checked keyboard password visibility controls, role-specific editorial copy, invalid login, bound employer validation errors, retained input/role values, company-field visibility, existing seeker/employer login redirects, the `next` redirect and form availability without JavaScript. Browser review created no new accounts.

Local screenshots are in ignored `tmp/auth-review/`. Review these pages while signed out:

Additional captures in `tmp/auth-refinement/` verify single-viewport login at 1366×768, 1280×720, 1440×900, 1920×1080, 1280×650 and 1024×768. Mobile scrolling was checked at 390×844 and 320×700. Chromium's autofill pseudo-state was forced for visual/style checks on login and signup inputs; these checks verified the ivory inset fill, navy text and unchanged field height, rather than using a saved-password account.

- `/accounts/login/`
- `/accounts/register/`

Further page redesigns await approval.

The alignment refinement was compared against the preceding form styles at eight viewport sizes (320–1672 px). Browser measurements verified matching left-panel geometry across login and both registration roles, unchanged field/button dimensions and styles, and no horizontal overflow. Review screenshots are in ignored `tmp/auth-alignment/`. This refinement awaits visual approval.
