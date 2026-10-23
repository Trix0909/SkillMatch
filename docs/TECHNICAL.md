# SkillMatch technical documentation

## Architecture

Presentation: Django server-rendered templates, Bootstrap 5.3.8 CSS stored locally, custom CSS and vanilla JavaScript for skill tags. No separate frontend framework or REST API.

Application: Django URL routing, forms, role-protected views, ORM and `MatchingAlgorithm`. Python/scikit-learn computes rankings on CPU at request time.

Persistence: SQLite through Django migrations. User passwords use Django’s configured password hasher; sessions are stored through Django’s session framework.

## Modules

- `config/settings.py`: environment-aware local/deployment settings.
- `skillmatch/models.py`: accounts, profiles, jobs, skills, evidence and MFA recovery codes.
- `skillmatch/mfa.py`, `mfa_forms.py`, `mfa_views.py`, `mfa_recovery.py`: authenticator-app 2FA, login reminder, session verification and recovery codes; see [MFA.md](MFA.md).
- `skillmatch/forms.py`: validation and atomic registration/profile saving.
- `skillmatch/matching.py`: capped TF-IDF pipeline and bidirectional rankings.
- `skillmatch/views.py`: server-rendered workflows and authorization.
- `skillmatch/evaluation.py`: relevance helper, Precision@k and SUS calculations.
- `skillmatch/management/commands/`: opt-in synthetic demo and offline evaluation.
- `skillmatch/tests/`: algorithm, integration and permission checks.
- `templates/` and `static/`: responsive frontend and locally vendored Bootstrap.

## Schema

| Entity | Key fields and relationships |
| --- | --- |
| Django User | Username, private email/name, hashed password, active/staff flags |
| Account | One-to-one User, `active_role` constrained to `seeker` or `employer`; the workspace currently in use |
| JobSeekerProfile | One-to-one User, constrained certification/experience, bio, portfolio, updated timestamp |
| Skill | Foreign key to JobSeekerProfile, display name, normalized casefolded name, optional SkillCategory |
| SkillCategory | Unique category name, administered without changing matching |
| EvidenceLink | Foreign key to JobSeekerProfile, validated HTTP(S) URL |
| EmployerProfile | One-to-one User, company name and description |
| RecoveryDevice | One-to-one TOTP device; throttled, confirmed device that owns the user's recovery codes |
| RecoveryCode | Foreign key to RecoveryDevice, SHA-256 digest of a 128-bit code, unique per device; deleted when used |
| JobPost | Foreign key to employer, title, description, JSON required-skills list, constrained minimum levels, active flag, timestamps |

Skill uniqueness is enforced by `(profile, normalized_name)` and a case-insensitive database constraint. Normalization applies Unicode NFKC and collapses whitespace before casefolding. User-created tags are additionally checked by server forms. Account creation saves the chosen role as `active_role` and the corresponding profile in one transaction. A person holds one account. The first switch to the other role (`POST /accounts/switch-role/`) creates that side's profile: hiring asks for a company name, job seeking opens profile editing. Switching changes only `active_role`; both profiles are kept. Profile saves update names, skills and evidence together.

## Algorithm details

`CountVectorizer` extracts word counts, keeping technical terms such as C++ and C#. Counts are clipped at 2 in the sparse matrix. `TfidfTransformer` applies smoothed IDF and L2 normalization. This two-stage scikit-learn API is the TF-IDF method in the proposal; it is needed because clipping TF-IDF weights after normalization would not correctly cap raw term frequencies.

The corpus contains the query and all eligible documents. Fit one shared vocabulary per request, calculate cosine similarities, then apply certification and experience multipliers. Scores are rounded only for display; sorting retains full precision. Ties use the candidate/job primary key. Empty vocabularies return zero scores. The algorithm does not fetch external evidence URLs.

Minimum role requirements participate as text and evaluation criteria, but are not undocumented hard ranking constraints. Recommending jobs multiplies all job similarities by the same candidate-level factor, which cannot change that candidate’s relative ordering. Rankings may change when corpus contents change because IDF is corpus-dependent.

## Access and validation

All private pages require login. Employer routes require the account's active role to be employer; seeker routes require seeker. A user with both profiles sees only the pages of the role they are currently in. Editing, closing, deletion and saved-job candidate ranking retrieve jobs scoped to the current employer. Profile views allow the profile’s owner, authorized employers for complete profiles, and administrators. Inactive accounts are removed from matching and cannot sign in. Names, emails and evidence URLs do not influence scores.

Django handles password hashing/validation, CSRF, session cookies and output escaping. Supporting URLs accept HTTP and HTTPS only; links open with `noopener noreferrer`. The app does not download linked content. Server validators enforce profile text/URL lengths, one to forty skills and at most eight links. HTML entered in descriptions is escaped. GET requests cannot sign out or close jobs; deletion requires a POST after a confirmation page.

## Two-factor authentication

Authenticator-app TOTP uses django-otp. Ordinary users may enroll from account security; staff and superusers must enroll and are blocked from the site and from `/admin/` until their session is verified. A middleware enforces this on every request for admins and for enrolled users. Enrolled users verify with a code at login; recovery codes are an alternative second step. An optional reminder after login offers enrollment. Details, routes and manual checks are in [MFA.md](MFA.md).

## Deployment

1. Install Python 3.12 and `requirements-lock.txt` in a virtual environment.
2. Set `DJANGO_DEBUG=0`, a unique random `DJANGO_SECRET_KEY`, and comma-separated `DJANGO_ALLOWED_HOSTS` containing only the production hostnames.
3. Set `SKILLMATCH_DB` to a persistent writable SQLite path if outside the application directory. SQLite suits the stated prototype scale; keep it on local persistent storage and back it up consistently.
4. Use a fresh database without demo users. Run `manage.py migrate` and `manage.py createsuperuser`.
5. Run `manage.py collectstatic --noinput`. Serve `staticfiles/` under `/static/` through the web server. Do not rely on Django runserver in production.
6. Serve `config.wsgi:application` using Waitress, for example `waitress-serve --listen=127.0.0.1:8000 config.wsgi:application`, behind a configured HTTPS reverse proxy.
7. Secure cookies, SSL redirect and HSTS are enabled when debug is off. Configure trusted proxy HTTPS forwarding for the actual deployment infrastructure before enabling a public site; do not blindly trust client-supplied forwarded headers. If the proxy terminates HTTPS, add `SECURE_PROXY_SSL_HEADER` only after it is configured to strip and set that header itself.
8. Run `manage.py check --deploy` with the real deployment environment. Restrict administration and protect the database and secret values with filesystem permissions and backups.

The default debug server is bound to loopback. Its persistent development secret is generated locally in ignored `.secret-key`. Deployments fail fast if no environment secret is provided. A hosting service, DNS, HTTPS certificates and external GitHub repository are not provisioned by this local build.

## Dependencies

Application requirements are pinned in `requirements.txt`; resolved packages from this build are recorded in `requirements-lock.txt`. Development tools and their resolved dependency set are maintained in `requirements-dev.txt` and `requirements-dev-lock.txt`. On Windows, `start.cmd` uses `tools/launch.py` to locate Python, prepare dependencies, apply migrations and start the server without requiring PowerShell scripts. `tools/dev.py` provides setup, formatting and validation; see `docs/DEVELOPMENT.md`. Bootstrap is vendored with its license header in `static/vendor/bootstrap.min.css` and license in `static/vendor/BOOTSTRAP-LICENSE.txt`. No external fonts, images, CDN runtime resources or paid services are needed.
