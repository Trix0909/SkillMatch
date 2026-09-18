# SkillMatch technical documentation

## Architecture

Presentation: Django server-rendered templates, Bootstrap 5.3.8 CSS stored locally, custom CSS and vanilla JavaScript for skill tags. No separate frontend framework or REST API.

Application: Django URL routing, forms, role-protected views, ORM and `MatchingAlgorithm`. Python/scikit-learn computes rankings on CPU at request time.

Persistence: SQLite through Django migrations. User passwords use Django’s configured password hasher; sessions are stored through Django’s session framework.

## Modules

- `config/settings.py`: environment-aware local/deployment settings.
- `skillmatch/models.py`: accounts, profiles, jobs, skills and evidence.
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
| Account | One-to-one User, constrained role `seeker` or `employer` |
| JobSeekerProfile | One-to-one User, constrained certification/experience, bio, portfolio, updated timestamp |
| Skill | Foreign key to JobSeekerProfile, display name, normalized casefolded name, optional SkillCategory |
| SkillCategory | Unique category name, administered without changing matching |
| EvidenceLink | Foreign key to JobSeekerProfile, validated HTTP(S) URL |
| EmployerProfile | One-to-one User, company name and description |
| JobPost | Foreign key to employer, title, description, JSON required-skills list, constrained minimum levels, active flag, timestamps |

Skill uniqueness is enforced by `(profile, normalized_name)` and a case-insensitive database constraint. Normalization applies Unicode NFKC and collapses whitespace before casefolding. User-created tags are additionally checked by server forms. Account creation saves a role and corresponding profile in one transaction. Profile saves update names, skills and evidence together.

## Algorithm details

`CountVectorizer` extracts word counts, keeping technical terms such as C++ and C#. Counts are clipped at 2 in the sparse matrix. `TfidfTransformer` applies smoothed IDF and L2 normalization. This two-stage scikit-learn API is the TF-IDF method in the proposal; it is needed because clipping TF-IDF weights after normalization would not correctly cap raw term frequencies.

The corpus contains the query and all eligible documents. Fit one shared vocabulary per request, calculate cosine similarities, then apply certification and experience multipliers. Scores are rounded only for display; sorting retains full precision. Ties use the candidate/job primary key. Empty vocabularies return zero scores. The algorithm does not fetch external evidence URLs.

Minimum role requirements participate as text and evaluation criteria, but are not undocumented hard ranking constraints. Recommending jobs multiplies all job similarities by the same candidate-level factor, which cannot change that candidate’s relative ordering. Rankings may change when corpus contents change because IDF is corpus-dependent.

## Access and validation

All private pages require login. Employer routes enforce the employer role; seeker routes enforce the seeker role. Editing, closing, deletion and saved-job candidate ranking retrieve jobs scoped to the current employer. Profile views allow the profile’s owner, authorized employers for complete profiles, and administrators. Inactive accounts are removed from matching and cannot sign in. Names, emails and evidence URLs do not influence scores.

Django handles password hashing/validation, CSRF, session cookies and output escaping. Supporting URLs accept HTTP and HTTPS only; links open with `noopener noreferrer`. The app does not download linked content. Server validators enforce profile text/URL lengths, one to forty skills and at most eight links. HTML entered in descriptions is escaped. GET requests cannot sign out or close jobs; deletion requires a POST after a confirmation page.

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

Application requirements are pinned in `requirements.txt`; resolved packages from this build are recorded in `requirements-lock.txt`. Development tools and their resolved dependency set are maintained in `requirements-dev.txt` and `requirements-dev-lock.txt`. `setup.ps1` and `tools/dev.py` provide setup, formatting and validation; see `docs/DEVELOPMENT.md`. Bootstrap is vendored with its license header in `static/vendor/bootstrap.min.css` and license in `static/vendor/BOOTSTRAP-LICENSE.txt`. No external fonts, images, CDN runtime resources or paid services are needed.
