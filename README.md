# SkillMatch

A Django web application for structured professional profiles and keyword-weighted job matching.

This build uses **Django templates, Bootstrap 5, SQLite and scikit-learn**, as specified in the proposal and defense presentation. The React frontend is superseded by detailed specifications in the documentation. See [requirements and source decisions](docs/REQUIREMENTS.md).

## Run on Windows

**Double-click `start.cmd` in the SkillMatch project folder**, or open a terminal in that folder and run this one command:

```powershell
.\start.cmd
```

When the server is ready, open **http://127.0.0.1:8000** in your browser. Keep the terminal window open while using the app; press **Ctrl+C** to stop it.

You can also double-click `SkillMatch.url` to open that address after starting the server. The shortcut opens the browser only; use `start.cmd` to start the application.

The launcher finds Python 3.12, creates the project environment if needed, installs missing or changed pinned dependencies, applies database migrations and starts Django. The first setup needs internet access; later starts reuse installed dependencies. Your existing database, accounts and demo passwords are preserved. You do not need to activate an environment or run a separate setup command.

### First installation and troubleshooting

- **Python:** Install Python **3.12** with the Python launcher if it is not already installed. The launcher first reuses a working project `.venv`, then checks `py -3.12`, `python`, and the bundled Python on the original development machine.
- **PowerShell says scripts are disabled:** Use `.\start.cmd`, rather than the older `.ps1` commands. No execution-policy change or administrator terminal is needed.
- **Moved the folder:** Open the new **SkillMatch** folder in VS Code (**File → Open Folder**) and open a new terminal there. Run `.\start.cmd`. On a different computer, install Python 3.12 and recreate the environment; virtual environments are machine-specific.
- **Port 8000 is in use:** Stop your other development server with Ctrl+C, or run `.\start.cmd --port 8001` and open **http://127.0.0.1:8001**.
- **Install or refresh dependencies without starting:** Run `.\start.cmd --setup-only`.
- **Use a specific Python installation:** Set `$env:SKILLMATCH_PYTHON = 'C:\path\to\python.exe'` before running `.\start.cmd`. It must be Python 3.12.

On macOS/Linux, run `python3.12 tools/dev.py setup`, then `.venv/bin/python tools/dev.py run`.

See [development environment and workflow](docs/DEVELOPMENT.md) for editor configuration, validation and the Git workflow.

### Try the synthetic demonstration

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
```

This explicitly creates **30 fictional candidate profiles, 10 job posts**, a seeker, an employer and an administrator. It generates a random password and writes it to `demo-credentials.txt` (excluded from version control). Sign in with `demo_seeker`, `demo_employer` or `demo_admin` and that password. These users and records are demonstration data, not project participants or research findings. The command refuses to overwrite existing demo users.

For a clean installation, skip demo seeding, register your own accounts, and create an administrator with:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Features

The landing, login and signup pages use the Match Point visual design, local Inter/Playfair fonts and responsive Kenyan editorial imagery. See [landing design and asset notes](docs/LANDING-DESIGN.md) and [authentication design notes](docs/AUTH-DESIGN.md). Other pages retain their current UI pending design approval.

- Separate job seeker and employer registration and workspaces, password hashing, session authentication, CSRF protection and server-side role/ownership checks.
- Authenticator-app 2FA: optional for job seekers/employers and mandatory for staff/superusers, including direct Django admin access. Enable it through the profile page's **Account security** link. See the [MFA setup, testing and implementation guide](docs/MFA.md). Recovery and disabling are deferred; keep access to your authenticator.
- Structured profiles: names, unique skill tags, certification and experience dropdowns, professional summary, project descriptions and optional HTTP(S) evidence links.
- Employer company profile, job creation/editing, closing/reopening, deletion confirmation and candidate search.
- Ranked candidates for an employer’s job or free-text search, ranked job recommendations for seekers, and employer access to candidate profiles.
- Exact matching-skill indicators and an expandable explanation showing base similarity, both multipliers and final score.
- Django administration for users, profiles, jobs and skill categories.
- Offline Precision@5/Precision@10 comparison and SUS scoring tools. No analytics dashboard.

There are no uploads, CV parsing, external job-board integrations, credential verification, messaging, payments, application submission, salary negotiation or geolocation matching.

## Matching

Candidate text is `skills + bio + portfolio`; job text is `title + description + required skills`. The title and structured required skills are treated as parts of the employer’s description. Both sides share one fitted TF-IDF vocabulary for each ranking request.

1. Lowercase, tokenize and remove English stop words.
2. Cap every raw term count at **2**.
3. Apply smoothed inverse document frequency and L2 normalization.
4. Compute cosine similarity.
5. Multiply by the candidate’s certification and experience factors.

```
final_score = cosine_similarity × certification_multiplier × experience_multiplier

Certification: Basic 1.0 | Intermediate 1.3 | Advanced 1.6 | Expert 2.0
Experience:   Junior 1.0 | Mid 1.2 | Senior 1.5 | Lead 1.8
```

The score is **0–3.6**, not a probability. Supporting links never contribute to the score. Portfolio descriptions contribute through their text, with no invented extra portfolio multiplier. Incomplete or inactive candidate profiles and closed/inactive-employer jobs are omitted. Ties use ascending database ID. Zero-score results remain visible at the bottom instead of introducing an undocumented threshold.

The same algorithm works in reverse. A single seeker’s multipliers are constant across all their recommended jobs, so they change scores but not their relative order. Minimum job levels are presented as requirements and used for evaluation relevance; they do not add an undocumented hard ranking filter.

## Validate

```powershell
.\.venv\Scripts\python.exe tools/dev.py check
```

The command runs Python linting, formatting checks, dependency and Django checks, migration drift detection, all tests, production-setting checks, static collection and a Git-index privacy check. `tools/dev.py format` formats first-party code, and `tools/dev.py doctor` inspects the environment and prepared database. GitHub Actions is configured to run validation on Windows and Linux when the repository is pushed to GitHub.

Tests cover the real ranking pipeline, repetition capping, qualification multipliers, bidirectional matching, duplicate prevention, evidence safety, registration, role permissions, ownership, CSRF, escaped content, job lifecycle and research metric calculations. MFA tests cover optional enrollment, mandatory admin setup, second-factor login, direct admin protection, replay/throttling, expiry, session isolation and safe redirects.

## Evaluate

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_matching --export-labels evaluation/labels.csv
# Manually review every job/candidate pair. Fill relevant (0/1) and reviewer.
.\.venv\Scripts\python.exe manage.py evaluate_matching --labels evaluation/labels.csv --output evaluation/matching-results.json
# Collect actual responses in a copy of evaluation/sus_responses_template.csv.
.\.venv\Scripts\python.exe manage.py score_sus evaluation/responses.csv --output evaluation/sus-results.json
```

Relevance means at least **70% of required skills** and meeting both required levels. The label sheet provides rule suggestions separately from the blank reviewer fields. Evaluation refuses incomplete, duplicate or stale label sets. It compares the weighted algorithm with the same capped TF-IDF/cosine pipeline without multipliers. SUS requires ten integer responses from 1 to 5 per participant. **No human evaluation scores are fabricated or prefilled.**

See [user guide](docs/USER_GUIDE.md), [technical documentation](docs/TECHNICAL.md), [evaluation protocol](docs/EVALUATION.md), [verification report](docs/VERIFICATION.md), and [editable diagrams](docs/diagrams/README.md).

## Google and GitHub sign-in

Optional provider sign-in uses `django-allauth[socialaccount]==65.20.1` with Django 5.2 and Python 3.12. The existing SkillMatch login, registration, logout, role switching, TOTP and recovery-code flows remain in place. Only provider handshakes and the SkillMatch onboarding/account-management routes are exposed; allauth's default password/signup pages are not mounted.

### Install and configure

From the project folder, with the Python 3.12 environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev-lock.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

The dependency brings its own `account` and `socialaccount` migrations. There are no new SkillMatch models or migrations. Back up an existing database before applying migrations. The normal setup/start scripts also install dependencies and apply migrations.

For local development, create `.env` beside `manage.py` (use `.env.example` as a reference) and put your Google/GitHub credentials there once. Start normally with `.\start.cmd`; `python-dotenv` loads that exact file before Django reads its settings. The file is optional, Git-ignored, and must never be committed. Existing shell variables take precedence (`override=False`). Restart after editing `.env`.

Production continues to use the hosting service's environment variables. When the hosting environment sets `DJANGO_DEBUG=0`, the local `.env` file is not loaded; the existing production secret-key and HTTPS requirements remain unchanged.

| Provider | Required environment variables | Requested scopes |
| --- | --- | --- |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | `openid email profile` |
| GitHub | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `read:user user:email` |

Google and GitHub buttons are always visible. Both credential values must be present to enable a provider's button; otherwise it remains disabled without starting OAuth or displaying a configuration label. Missing credentials leave password login and other configured providers available. Connected accounts lists only Google and GitHub with their configuration status. Database `SocialApp` credentials are ignored and allauth identity/credential tables are not editable through Django admin. Never commit credentials or tokens.

### Exact callback addresses

| Provider | Local callback | Production callback (replace the example host) |
| --- | --- | --- |
| Google | `http://127.0.0.1:8000/accounts/social/google/login/callback/` | `https://your-skillmatch-domain.example/accounts/social/google/login/callback/` |
| GitHub | `http://127.0.0.1:8000/accounts/social/github/login/callback/` | `https://your-skillmatch-domain.example/accounts/social/github/login/callback/` |

Use the same hostname throughout a sign-in attempt: `localhost` and `127.0.0.1` have different browser cookies. Match the full callback path and trailing slash. Use separate local and production applications/secrets. Production requires HTTPS and the project's existing secure Django settings; register the actual HTTPS address with each provider.

### Google setup

1. In Google Cloud / Google Auth Platform, create or select a project and configure its consent screen, audience and test users while it is in testing mode.
2. Create an OAuth client of type **Web application**. Add the exact Google callback above under authorized redirect URIs.
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from that client. No browser SDK, API key, or service account is needed.
4. Restart SkillMatch. Choose **Continue with Google**. allauth exchanges the authorization code and validates the provider identity; SkillMatch requires a verified provider email for new accounts/connections. Existing identities resolve by Google's UID.

See [Google's OpenID Connect setup](https://developers.google.com/identity/openid-connect/openid-connect).

### GitHub setup

1. In GitHub **Settings → Developer settings → OAuth Apps**, register an OAuth app. Use `http://127.0.0.1:8000` as the development homepage and the exact GitHub callback above as its authorization callback URL.
2. Generate a client secret and set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`. Create a separate OAuth app for the production callback.
3. Restart SkillMatch and choose **Continue with GitHub**. allauth retrieves the user identity and `/user/emails`; SkillMatch accepts a verified email from that endpoint, including a private email. A public profile email without verification is insufficient. GitHub's UID remains the identity key.

See [GitHub's OAuth authorization documentation](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).

### Account, MFA and connection behaviour

- New users remain anonymous with an unsaved, unusable-password user during onboarding. The short form reuses registration's role/company validation and creates the User, SocialAccount, Account and initial profile in one transaction. No partial account or authenticated bypass exists before completion. The chosen `active_role` can later be switched using the existing dual-role flow.
- A trusted provider email matching **any** existing local user is refused. No account is merged or linked by email, including when several local users share it. Sign in normally, then use **My profile → Connected accounts** to connect explicitly. `can_auto_link()` intentionally returns false because local email ownership has not been independently verified.
- Previously linked identities resolve by provider and UID even after an email change. Inactive users cannot log in. Connecting an identity belonging to another user is refused.
- Normal users without 2FA receive the existing optional **Enable now / Not now** reminder. Users with confirmed TOTP enter the existing pending MFA flow and may use their authenticator or a saved recovery code. Staff/superusers must complete mandatory setup or verification before any protected/admin access. Provider login alone never satisfies SkillMatch MFA.
- Provider start, connect and disconnect actions use CSRF-protected POSTs. allauth owns OAuth state, single-use callback handling and PKCE. Safe local `next` destinations are retained through onboarding, reminders and MFA. Cancelled, expired or failed handshakes return to login or Connected accounts without creating an account.
- **Connected accounts** requires fresh identity confirmation for connection, disconnection and a first password. Password users re-enter their current password; social-only users complete a new OAuth round trip using an identity already connected to the same user. Google/GitHub request account selection (Google also requests `max_age=0`). The upstream provider controls its own sign-in UI/session. No existing SkillMatch session alone grants confirmation. A required SkillMatch MFA session must already be verified.
- Confirmation lasts five minutes and is bound to the current user and password hash; password changes invalidate it. The callback rechecks freshness, ownership and the initiating user. This explicit policy is necessary because allauth 65.20.1's default recent-authentication helper accepts social-only users when it has no reauthentication flow. Password confirmation is throttled after five failed attempts for five minutes using Django's cache; use a shared cache if deploying multiple application processes.
- Disconnect cannot remove the last usable login method. Another provider counts only if configured; a usable local password also counts. Other sessions are not forcibly terminated by connecting/disconnecting.
- Social-only users can set their first password using Django's validated `SetPasswordForm` after confirmation. Existing password users cannot use that endpoint to replace a password. This repository has no existing change-password page, so no new change-password system was added.
- Social-only users can enable TOTP immediately through the reminder or later from security settings after provider confirmation. Their initial recovery codes work unchanged. The existing recovery-code regeneration policy still requires a local password, so they must set a password before generating a replacement set.
- Access/refresh tokens and avatars are not stored. SocialAccount metadata contains only the verified email, when available; User stores required identity/name fields. OAuth secrets are used transiently for provider communication. Onboarding expires after five minutes; restarting provider sign-in starts a fresh attempt.

### Manual verification and automated checks

Configure each provider's real test application before end-to-end provider testing. Automated tests mock all external HTTP and do not validate your actual credentials, consent policies or provider-console settings.

1. Try a new verified provider identity: verify onboarding is required; employer signup needs a company; both starting roles create the correct profile. Try navigating to `/jobs/` before onboarding: access must require login.
2. Try an email belonging to one or more local users: expect refusal, no duplicate user and no silent link. Connect it explicitly after logging in locally and confirming your password.
3. Log in through a connected provider without 2FA: decline the one-time reminder and check the original destination. Enable TOTP, log out, then repeat: password/provider first factor must now require the existing TOTP or recovery-code step.
4. Test a staff account with and without a confirmed device. Direct `/admin/` access must remain blocked until mandatory MFA completes.
5. Under Connected accounts, try connecting/disconnecting before confirmation, after confirmation, and after five minutes. For a social-only user, a different provider identity must not satisfy confirmation. Check last-method protection, then set a first password and verify normal password login works.
6. Cancel provider consent; retry with expired/missing OAuth state; try an external `next` URL. Expect a safe local return and no partially created account.

```powershell
.\.venv\Scripts\python.exe manage.py test skillmatch.tests.test_sso
.\.venv\Scripts\python.exe manage.py makemigrations --check
.\.venv\Scripts\python.exe tools/dev.py check
```

The SSO tests exercise the actual allauth state/callback routes with mocked provider HTTP, including Google identity validation, GitHub private-email retrieval, account collisions, onboarding, TOTP/recovery/admin gates, pending-state tampering/replay, recent confirmation, CSRF, lockout protection and redirect safety. The full check command also runs all existing password/MFA/dual-role tests. There is no new email verification, account merging, provider profile import or recovery mechanism.

## Deployment

This is an academic prototype with source maintained at [Trix0909/SkillMatch](https://github.com/Trix0909/SkillMatch). For deployment, use an empty database without demo accounts, a strong environment-provided `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, explicit `DJANGO_ALLOWED_HOSTS`, HTTPS, a WSGI server and a web server serving collected static files. See [deployment procedure](docs/TECHNICAL.md#deployment). The application itself has not been deployed to an external hosting service.
