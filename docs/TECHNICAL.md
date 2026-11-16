# SkillMatch technical documentation

## Architecture

Presentation: Django server-rendered templates, Bootstrap 5.3.8 CSS stored locally, custom CSS and vanilla JavaScript for skill tags. No separate frontend framework or REST API.

Application: Django URL routing, forms, role-protected views, ORM and `MatchingAlgorithm`. Python/scikit-learn computes rankings on CPU at request time.

Persistence: SQLite through Django migrations (`0001` to `0010`). User passwords use Django’s configured password hasher; sessions are stored through Django’s session framework. Uploaded profile photos, company logos and cover images are stored under `MEDIA_ROOT` (`media/`).

Hosting: the live demonstration runs on the free PythonAnywhere plan at https://skillmatcher.pythonanywhere.com (see [Deployment](#deployment)). The local Windows build uses Waitress; PythonAnywhere uses its own WSGI server to serve `config.wsgi:application`.

## Modules

- `config/settings.py`: environment-aware local/deployment settings.
- `skillmatch/models.py`: accounts, profiles (with images), company fields, jobs (with closing dates), skills, evidence, saved items, connections, messages, connection activity and MFA recovery codes.
- `skillmatch/mfa.py`, `mfa_forms.py`, `mfa_views.py`, `mfa_recovery.py`: authenticator-app 2FA, login reminder, session verification and recovery codes; see [MFA.md](MFA.md).
- `skillmatch/forms.py`: validation and atomic registration/profile saving.
- `skillmatch/recruitment.py`, `connection_views.py`, `connection_forms.py`: applications and invitations (connections), accept/decline/withdraw, hiring stages, interview scheduling, messaging and the notification counts. Every state change runs as a serialised transaction.
- `skillmatch/job_dates.py`: closing-date rules in the `Africa/Nairobi` time zone.
- `skillmatch/match_filters.py`: the minimum-match filter, applied after ranking and before pagination.
- `skillmatch/profile_images.py`: upload validation and re-encoding of profile and company images.
- `skillmatch/admin_site.py`, `admin_dashboard.py`: the administration overview, reports and search pages.
- `skillmatch/social.py`, `social_views.py`: Google and GitHub sign-in adapters, onboarding and connected accounts.
- `skillmatch/context.py`: template context for the profile dropdown and the notification bell.
- `skillmatch/matching.py`: capped TF-IDF pipeline and bidirectional rankings.
- `skillmatch/views.py`: server-rendered workflows and authorization.
- `skillmatch/evaluation.py`: relevance helper, Precision@k and SUS calculations.
- `skillmatch/management/commands/`: opt-in synthetic demo and offline evaluation.
- `skillmatch/tests/`: 459 automated tests across 27 test modules: algorithm, integration, permission, concurrency, upload and sign-in checks (see [VERIFICATION.md](VERIFICATION.md)).
- `templates/` and `static/`: responsive frontend and locally vendored Bootstrap.

## Schema

| Entity | Key fields and relationships |
| --- | --- |
| Django User | Username, private email/name, hashed password, active/staff flags |
| Account | One-to-one User, `active_role` constrained to `seeker` or `employer`; the workspace currently in use |
| JobSeekerProfile | One-to-one User, constrained certification/experience, optional photo, bio (up to 2,000 characters), portfolio (up to 6,000), optional phone, updated timestamp |
| Skill | Foreign key to JobSeekerProfile, display name, normalized casefolded name, optional SkillCategory |
| SkillCategory | Unique category name, administered without changing matching |
| EvidenceLink | Foreign key to JobSeekerProfile, validated HTTP(S) URL |
| EmployerProfile | One-to-one User, company name and description, plus optional logo, cover image, tagline, location, company size, industry, summary (up to 300 characters), workplace culture, up to three focus areas and website, LinkedIn and X links |
| RecoveryDevice | One-to-one TOTP device; throttled, confirmed device that owns the user's recovery codes |
| RecoveryCode | Foreign key to RecoveryDevice, SHA-256 digest of a 128-bit code, unique per device; deleted when used |
| SavedJob | Foreign key to the user and to a JobPost, unique per user and job; a seeker's bookmark |
| SavedCandidate | Foreign key to the user (an employer), to a candidate profile and optionally to a job, unique per user and candidate; an employer's bookmark |
| JobPost | Foreign key to employer, title, description, JSON required-skills list, constrained minimum levels, active flag, optional closing date, timestamps |
| Connection | One application or invitation: foreign keys to a JobPost and a seeker profile (one connection per job and seeker), who started it, status (`pending`, `accepted`, `declined`, `withdrawn`), stage (`new`, `shortlisted`, `interview`, `offered`, `not selected`), optional interview time and note of up to 500 characters; database check constraints restrict the choice fields |
| Message | Foreign key to a Connection and the sender, text of up to 2,000 characters, created/read/edited/unsent times and a unique submission key that makes a repeated submit harmless |
| ConnectionActivity | Foreign key to a Connection, the acting user, the event (request, response, stage change), optional stage and interview time, with a read time used by the notification bell |

Skill uniqueness is enforced by `(profile, normalized_name)` and a case-insensitive database constraint. Normalization applies Unicode NFKC and collapses whitespace before casefolding. User-created tags are additionally checked by server forms. Account creation saves the chosen role as `active_role` and the corresponding profile in one transaction. A person holds one account. The first switch to the other role (`POST /accounts/switch-role/`) creates that side's profile: hiring asks for a company name, job seeking opens profile editing. Switching changes only `active_role`; both profiles are kept. Profile saves update names, skills and evidence together.

## Algorithm details

`CountVectorizer` extracts word counts, keeping technical terms such as C++ and C#. Counts are clipped at 2 in the sparse matrix. `TfidfTransformer` applies smoothed IDF and L2 normalization. This two-stage scikit-learn API is the TF-IDF method in the proposal; it is needed because clipping TF-IDF weights after normalization would not correctly cap raw term frequencies.

The corpus contains the query and all eligible documents. Fit one shared vocabulary per request, calculate cosine similarities, then apply certification and experience multipliers. Scores are rounded only for display; sorting retains full precision. Ties use the candidate/job primary key. Empty vocabularies return zero scores. The algorithm does not fetch external evidence URLs.

Minimum role requirements participate as text and evaluation criteria, but are not undocumented hard ranking constraints. Recommending jobs multiplies all job similarities by the same candidate-level factor, which cannot change that candidate’s relative ordering. Rankings may change when corpus contents change because IDF is corpus-dependent.

## Access and validation

All private pages require login. Employer routes require the account's active role to be employer; seeker routes require seeker. A user with both profiles sees only the pages of the role they are currently in. Editing, closing, deletion and saved-job candidate ranking retrieve jobs scoped to the current employer. Profile views allow the profile’s owner, authorized employers for complete profiles, and administrators. Inactive accounts are removed from matching and cannot sign in. Names, emails and evidence URLs do not influence scores.

Django handles password hashing/validation, CSRF, session cookies and output escaping. Supporting URLs accept HTTP and HTTPS only; links open with `noopener noreferrer`. The app does not download linked content. Server validators enforce profile text/URL lengths, one to forty skills and at most eight links. HTML entered in descriptions is escaped. GET requests cannot sign out or close jobs; deletion requires a POST after a confirmation page.

## Connections and messaging

A job seeker applies to an open job, or an employer invites a complete candidate, which creates a pending `Connection`. The other party accepts or declines it, and the sender may withdraw it. A request is refused when the job is closed or past its deadline, when either account is inactive, when the seeker's profile is incomplete, or when the sender has already started 20 requests (`CONNECTION_REQUEST_LIMIT`) in a rolling 24 hours. Only one connection can exist for a job and seeker. After acceptance the employer moves the connection through the stages New, Shortlisted, Interview and Offered, or marks it Not selected; stages advance one step at a time and an interview carries a future date and time. The seeker's email and phone number are shown to the employer only after acceptance.

The two parties exchange text messages (up to 2,000 characters) on the connection page. A sender may edit or unsend a message for 15 minutes. Messages are delivered when a page is loaded; there are no push notifications or websockets. The notification bell shows unread requests, stage changes and messages. Every action is stored as a `ConnectionActivity` row, and each state change runs inside a serialised database transaction (`recruitment.serialized`), so simultaneous requests cannot create a duplicate connection or exceed the request limit. None of this changes any matching score.

## Job deadlines

An employer may set a closing date on a job. Once that date has passed in the Africa/Nairobi time zone the job is shown as closed, stops accepting applications and invitations, and drops out of recommendations and browsing; existing accepted connections continue. Reopening a job whose date has passed requires a new date or removal of the date.

## Minimum match filter

Recommendations and candidate rankings can be narrowed to results with a displayed match of at least 30, 50, 70, 80 or 90 percent. The displayed percentage is `round(cosine similarity × 100)` before the certification and experience multipliers. The filter is applied after ranking and before pagination, so it never changes the order or the percentages of the results that remain.

## Company pages and images

Employers maintain a company profile (tagline, summary, description, location, size, industry, culture, focus areas and links). Job seekers see it on a company page (`/companies/<id>/`) linked from the company's jobs. Seekers may upload a profile photo, and employers a logo and cover image. An upload must be a JPEG, PNG or WebP of at most 5 MB and 12 megapixels. It is decoded and re-encoded as a PNG under a server-generated file name, so no client file name, metadata or embedded content is stored. A placeholder is shown when no image is set.

## Administration

Staff reach a custom administration site at `/admin/` (always behind two-factor verification). Besides the standard Django model pages it provides an overview dashboard with totals, a growth chart and recent activity (`/admin/`), monthly reports of new users and job posts (`/admin/reports/`), a settings directory (`/admin/settings/`) and a search page that finds administration pages (`/admin/search/`). These pages only read data and are scoped through the registered model administrators, so a staff member sees only what their permissions allow.

## Public pages

The landing page, the "How matching works" page, the get-started page and the privacy policy (`/privacy/`) are public. The privacy page describes what SkillMatch stores and is the URL registered with Google for the sign-in consent screen.

## Provider sign-in

Google and GitHub sign-in use django-allauth alongside the existing login. Provider users go through the same MFA gates as password users, new users complete a short onboarding form, and a provider identity links to an existing account only when the provider's email is verified. Connected accounts are managed from account security after fresh confirmation. Setup, callbacks and security policies are in the README.

## Dashboards and saved items

Seekers and employers have dashboards as their home pages. Seekers save jobs from recommendations and browsing (`/saved-jobs/`), and employers save candidates from rankings (`/employer/saved-candidates/`). Both lists are private to the user who made them.

## Two-factor authentication

Authenticator-app TOTP uses django-otp. Ordinary users may enroll from account security; staff and superusers must enroll and are blocked from the site and from `/admin/` until their session is verified. A middleware enforces this on every request for admins and for enrolled users. Enrolled users verify with a code at login; recovery codes are an alternative second step. An optional reminder after login offers enrollment. Details, routes and manual checks are in [MFA.md](MFA.md).

## Deployment

SkillMatch is deployed on the free plan of PythonAnywhere at https://skillmatcher.pythonanywhere.com (live since 12 November 2026). The live site uses the database from the development laptop, so it contains the demonstration accounts created by `seed_demo`. The free plan has one web worker, which is enough for a demonstration and is not load-tested.

### PythonAnywhere (current deployment)

1. Clone the repository into the home directory, create a Python 3.12 virtual environment named `skillmatch` and install `requirements-lock.txt`.
2. In the Web tab, add a manual-configuration web app. In the WSGI file, set the environment variables (`DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`) before the application is imported, because the local `.env` file is not read when debug is off.
3. Map `/static/` to `staticfiles/` and `/media/` to `media/`. Enable Force HTTPS.
4. Run `python manage.py migrate`, `python manage.py collectstatic --noinput` and `python manage.py createsuperuser`, then press **Reload**.
5. To update after a change to `master`: open a Bash console and run `workon skillmatch && cd ~/SkillMatch && git pull && pip install --no-cache-dir -r requirements-lock.txt && python manage.py migrate && python manage.py collectstatic --noinput`, then press **Reload** in the Web tab.

Register `https://skillmatcher.pythonanywhere.com/accounts/social/google/login/callback/` and the matching GitHub path as the callback URLs of the sign-in applications.

### Any other host

1. Install Python 3.12 and `requirements-lock.txt` in a virtual environment.
2. Set `DJANGO_DEBUG=0`, a unique random `DJANGO_SECRET_KEY`, and comma-separated `DJANGO_ALLOWED_HOSTS` containing only the production hostnames.
3. Set `SKILLMATCH_DB` to a persistent writable SQLite path if outside the application directory. SQLite suits the stated prototype scale; keep it on local persistent storage and back it up consistently. Back up `media/` as well.
4. Use a fresh database without demo users. Run `manage.py migrate` and `manage.py createsuperuser`.
5. Run `manage.py collectstatic --noinput`. Serve `staticfiles/` under `/static/` and `media/` under `/media/` through the web server (Django serves media itself only when debug is on). Do not rely on Django runserver in production.
6. Serve `config.wsgi:application` using a WSGI server such as Waitress, for example `waitress-serve --listen=127.0.0.1:8000 config.wsgi:application`, behind a configured HTTPS reverse proxy.
7. Secure cookies, SSL redirect and HSTS are enabled when debug is off. Configure trusted proxy HTTPS forwarding for the actual deployment infrastructure before enabling a public site; do not blindly trust client-supplied forwarded headers. If the proxy terminates HTTPS, add `SECURE_PROXY_SSL_HEADER` only after it is configured to strip and set that header itself.
8. Run `manage.py check --deploy` with the real deployment environment. Restrict administration and protect the database and secret values with filesystem permissions and backups.

The default debug server is bound to loopback. Its persistent development secret is generated locally in ignored `.secret-key`. Deployments fail fast if no environment secret is provided.

## Dependencies

Application requirements are pinned in `requirements.txt`; resolved packages from this build are recorded in `requirements-lock.txt`. Development tools and their resolved dependency set are maintained in `requirements-dev.txt` and `requirements-dev-lock.txt`. On Windows, `start.cmd` uses `tools/launch.py` to locate Python, prepare dependencies, apply migrations and start the server without requiring PowerShell scripts. `tools/dev.py` provides setup, formatting and validation; see `docs/DEVELOPMENT.md`. Bootstrap is vendored with its license header in `static/vendor/bootstrap.min.css` and license in `static/vendor/BOOTSTRAP-LICENSE.txt`. No external fonts, images, CDN runtime resources or paid services are needed.
