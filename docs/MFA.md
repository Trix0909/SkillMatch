# Authenticator-app two-factor authentication

This stage implements standard TOTP only. It was explicitly requested on 1 October 2026. Recovery codes, lost-phone flows, email/SMS factors and disabling 2FA are not implemented. Keep access to the authenticator used for enrollment.

## Compatibility and dependencies

The inspected application uses Python 3.12, Django 5.2.17, Django's built-in `User`, `AuthenticationForm` and database sessions. Login accepts a **username**, as before; adding email login is outside this change. Registration creates the existing seeker/employer role and immediately signs the new user in. Staff/superuser flags identify administrators; no new role or user model was introduced.

- **django-otp 1.7.3** provides maintained Django-compatible TOTP devices, cryptographically generated secrets, replay prevention, throttling and verified-session support. Its [release history](https://django-otp-official.readthedocs.io/en/stable/) includes Django 5.2 support. Integration follows its [authentication and transaction guidance](https://django-otp-official.readthedocs.io/en/stable/auth.html).
- **Segno 1.6.6** generates QR images locally. It is a QR encoder, not a second MFA implementation. Nothing is sent to a third-party QR service.

Both packages are pinned in `requirements.txt` and `requirements-lock.txt`. The development lock already includes the runtime lock, so no separate development-package change is required.

## Enable and use 2FA

Ordinary users can keep using their entire existing workspace without 2FA. Registration remains unchanged. After a successful password login, an ordinary user without a confirmed device sees one optional reminder.

### Optional login reminder

The reminder offers **Enable now** and **Not now**. It never gates workspace access: the user is already authenticated and may navigate normally without choosing. It does not appear for administrators, users with enabled 2FA, or new registrations.

- **Not now** removes the invitation from the current session and follows the original validated login destination, including `next` and role-based redirects. A future fresh password login may create a new invitation; there is no permanent preference.
- **Enable now** reuses `/accounts/2fa/setup/` and its existing enrollment verification. The just-completed password login authorizes enrollment for the existing five-minute freshness window; after that, the existing account-security page asks for the password again. No second setup flow or device model is added.
- The server-side session stores the destination, password-verification time and a `shown` marker. The marker prevents refreshes or revisits from displaying the reminder again. Choosing either option removes the invitation. No background redirect or access restriction depends on that invitation.
- The reminder uses the existing workspace card/button styles and CSRF-protected POST choices at `/accounts/2fa/reminder/`. Its explanatory links use **My profile → Two-factor authentication settings** for seekers and **Company profile → Two-factor authentication settings** for employers; both paths already existed.

The reminder addition modifies `skillmatch/mfa_views.py`, `skillmatch/mfa.py` (redirect-loop exclusion only), `skillmatch/urls.py`, `skillmatch/tests/test_mfa.py`, `skillmatch/tests/test_project.py` and this guide. It creates `templates/registration/mfa_reminder.html` and `skillmatch/tests/test_mfa_reminder.py`. Existing MFA policy, admin enforcement, QR/TOTP code, registration and profile navigation are unchanged.

### Enrollment from profile settings

1. Sign in and open **My profile** or **Company profile**.
2. Select **Two-factor authentication settings** in the existing profile sidebar panel.
3. The security page shows **Not enabled**. Enter your current password and select **Enable Two-Factor Authentication**.
4. Scan the QR code with Google Authenticator, Microsoft Authenticator, Authy or another compatible TOTP app. Alternatively expand the manual-key instructions. Provisioning uses issuer `SkillMatch`, your username, six digits, SHA-1 and a 30-second period.
5. Enter the current six-digit code and select **Verify and enable**. An incorrect code leaves 2FA disabled. Successful verification confirms the device and shows **Enabled**.
6. On subsequent logins, enter your username/password, then your authenticator code. Only after both succeed does SkillMatch create the authenticated session and follow the original safe `next` destination or normal workspace redirect.

The first setup verification consumes that code. If you immediately sign out and back in, wait for the next code in the app. Reusing a successful code is deliberately rejected. Keep the phone's clock set automatically; the library tolerates one adjacent 30-second time step and tracks clock drift.

Setup and login challenges expire after five minutes. Confirm the password again to continue. Cancel uses a CSRF-protected POST, clears the pending challenge and leaves 2FA disabled if setup was not completed. An unconfirmed device is reused on a later setup attempt so refreshes do not create duplicates or reset its throttling counter.

## Administrator enforcement

Accounts with `is_staff` **or** `is_superuser` require 2FA, including existing and demo administrators. Without a confirmed device, successful password authentication leads to mandatory setup. With one, it leads to code verification. Neither path creates a Django authenticated session until the code is accepted.

`MFAEnforcementMiddleware` blocks password-only authenticated sessions belonging to administrators or users with enabled 2FA, including old sessions and users promoted to staff. Such sessions are signed out and asked to authenticate again. Ordinary users without 2FA are unaffected.

The default admin site now extends `OTPAdminSite`; it retains the existing model registry, URLs and permissions and additionally requires a confirmed TOTP-verified session. `/admin/login/`, including direct password POSTs, routes through the existing SkillMatch sign-in page. The admin permission gate also enforces verification independently of the middleware. TOTP device editing/deletion is unregistered from admin so manually confirming a device or exposing its key is not an alternate enrollment/recovery mechanism.

## State and security

- Enabled means `TOTPDevice(user=current_user, confirmed=True)` exists. Merely opening setup never enables it. No status flag was added to the user/profile models.
- Password-passed challenges contain only a server-side user ID, backend, password-session hash, expiry, mode and validated destination. They contain no raw password, TOTP key or authenticated user session key. The hash invalidates the challenge after a password change; inactive users cannot complete it.
- Django rotates/flushes session identifiers across authentication boundaries. Successful verification records the device through `django_otp.login`; middleware checks the device's ownership and confirmed status. Logout clears both stages.
- Verification uses the library's `verify_token()` inside a transaction with row locks, retaining its exponential throttling and last-used time-step checks. Failed attempts commit their throttle counter. Concurrent conflicting SQLite verification writes fail closed and show a retry message.
- Account and device selection happen server-side. User/device IDs supplied in URLs or submitted forms do not select another account's device.
- Setup/verification/settings pages are not cached. QR codes are embedded images; secrets never appear in HTTP request URLs. A same-origin referrer policy prevents cross-site referrer disclosure while preserving browser CSRF Origin validation.
- The standard Django CSRF, password validators, cookie flags, HTTPS production settings and permission checks remain enabled. No trusted-device bypass is added.
- As with the library's normal storage model, TOTP keys are stored in the database and must be readable to verify codes. Protect the database and backups as secrets. Existing `.gitignore` and repository checks exclude databases and local credentials. No user passwords or enrolled secrets were committed.

## Routes

| URL | Purpose |
| --- | --- |
| `/accounts/security/` | Authenticated account status and password-confirmed optional enrollment |
| `/accounts/2fa/setup/` | QR/manual key and code confirmation for an authorized setup challenge |
| `/accounts/2fa/verify/` | Complete a pending login using a confirmed device |
| `/accounts/2fa/cancel/` | POST-only cancellation |

Existing `/accounts/login/`, registration, logout and admin URLs are preserved.

## Local commands and migrations

Stop an already running server and run the usual command from the project folder:

```powershell
.\start.cmd
```

The launcher installs changed pinned dependencies and applies migrations automatically. For explicit setup/checks:

```powershell
.\start.cmd --setup-only
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe tools/dev.py check
```

The dependencies were installed and these three upstream migrations were applied on the development database:

- `otp_totp.0001_initial`
- `otp_totp.0002_auto_20190420_0723`
- `otp_totp.0003_add_timestamps`

No SkillMatch model fields or custom migrations were needed. There are **no new environment variables or external-service credentials**. Settings use issuer `SkillMatch`, throttling factor `1` and a five-minute pending-challenge timeout. Existing production HTTPS/secret-key requirements still apply. No real account was enrolled automatically.

## Manual acceptance checks

Use separate ordinary and administrator test accounts and retain access to the authenticator for any account you enroll.

| Scenario | Check and expected result |
| --- | --- |
| New ordinary user | Register as seeker or employer. Profile editing opens immediately, with no MFA prompt. Visit the existing workspace pages. |
| Optional setup | Open security settings, confirm the password, scan the QR, submit a wrong code, then a current correct code after the retry delay. Only the correct code changes status to Enabled. Refreshing/revisiting must not create another active device. |
| Enabled login | Log out and sign in. Before entering the code, type a protected workspace URL: it must not grant access. A wrong code fails; a current unused code succeeds. |
| Intended destination | Visit `/accounts/login/?next=/jobs/` as an enrolled seeker. After both factors, `/jobs/` opens. External destinations must not be followed. |
| First admin setup | Sign in as a fresh staff/superuser account. Setup is mandatory. Try `/admin/` or `/admin/auth/user/` before finishing; access remains blocked. Verify the setup code and then use the normal admin interface. |
| Returning admin | Log out, visit `/admin/` and sign in again. A password alone is insufficient; a valid authenticator code is required. |
| Session and logout | Confirm both session stages clear on logout. Wait for a new code before testing another successful login. A five-minute abandoned challenge must require the password again. |
| Appearance | Check setup and code-entry screens on desktop and mobile; login and registration retain their approved designs. |

Automated verification: 77 tests (37 new MFA tests plus the existing 40), full development checks, and browser flows covering ordinary enrollment, invalid/correct codes, redirects, mandatory administrator setup/login, direct admin access and five viewport sizes (320–1440 px). An independent JavaScript QR decoder read the browser-rendered QR and matched its provisioning URI. Existing authentication browser checks were also rerun. QA used a separate ignored SQLite database and synthetic accounts, not live user enrollment. Phone-app interoperability follows the standard provisioning format; no claim is made that each named phone application was physically tested.

## File inventory

Created:

- `skillmatch/admin_site.py` — OTP-aware default admin site using the shared login.
- `skillmatch/mfa.py` — policy, server-side pending handoff, device enrollment and enforcement middleware.
- `skillmatch/mfa_forms.py` — current-password confirmation and six-digit code forms.
- `skillmatch/mfa_views.py` — login handoff, security settings, setup, verification and cancellation.
- `skillmatch/tests/test_mfa.py` — behavior and security regression tests.
- `templates/registration/mfa_base.html` — shared MFA composition using existing branding.
- `templates/registration/mfa_setup.html` — QR/manual setup and confirmation.
- `templates/registration/mfa_verify.html` — second-factor entry.
- `templates/registration/security.html` — account status and optional enrollment.
- `static/css/mfa.css` — styles scoped to the new MFA pages.
- `docs/MFA.md` — this implementation and test guide.

Modified:

- `config/settings.py` — OTP apps, middleware, admin config and policy settings.
- `requirements.txt`, `requirements-lock.txt` — pinned runtime dependencies.
- `skillmatch/apps.py` — default admin-site configuration.
- `skillmatch/admin.py` — remove device editing from the admin registry.
- `skillmatch/urls.py` — retain password route and add MFA routes.
- `templates/skillmatch/profile_form.html` — link to account security from the current profile interface.
- `README.md`, `docs/USER_GUIDE.md`, `docs/REQUIREMENTS.md`, `docs/BACKLOG.md` — feature, usage, authorized scope and progress updates.

Existing login/registration templates, their CSS, existing Django forms, registration view, account models, role logic and matching code are unchanged. Generated screenshots, throwaway browser scripts, decoder tooling, credentials and the QA database remain in ignored `tmp/` and are not part of the project deliverable.
