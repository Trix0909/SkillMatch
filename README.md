# SkillMatch

A Django web application for structured professional profiles and keyword-weighted job matching, implemented from Trina Kinyua’s three supplied project files (admission number 168111).

The working proposal is the implementation authority where the files differ. This build uses **Django templates, Bootstrap 5, SQLite and scikit-learn**, as specified in the proposal and defense presentation. The earlier concept note’s React frontend is superseded by those detailed specifications. See [requirements and source decisions](docs/REQUIREMENTS.md).

## Run on Windows

From this directory, using Python 3.12 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open **http://127.0.0.1:8000**. After setup, `start.ps1` starts the development server. Python in this project’s `.venv` is already configured on the build machine.

On macOS/Linux, use `python3`, `.venv/bin/python`, and the same management commands.

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

- Separate job seeker and employer registration and workspaces, password hashing, session authentication, CSRF protection and server-side role/ownership checks.
- Structured profiles: names, unique skill tags, certification and experience dropdowns, professional summary, project descriptions and optional HTTP(S) evidence links.
- Employer company profile, job creation/editing, closing/reopening, deletion confirmation and candidate search.
- Ranked candidates for an employer’s job or free-text search, ranked job recommendations for seekers, and employer access to candidate profiles.
- Exact matching-skill indicators and an expandable explanation showing base similarity, both multipliers and final score.
- Django administration for users, profiles, jobs and skill categories.
- Offline Precision@5/Precision@10 comparison and SUS scoring tools. No analytics dashboard.

There are no uploads, CV parsing, external APIs, credential verification, messaging, payments, application submission, salary negotiation or geolocation matching.

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
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test skillmatch.tests --verbosity 2
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Tests cover the real ranking pipeline, repetition capping, qualification multipliers, bidirectional matching, duplicate prevention, evidence safety, registration, role permissions, ownership, CSRF, escaped content, job lifecycle and research metric calculations.

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

## Deployment

This is a local academic prototype. For deployment, use an empty database without demo accounts, a strong environment-provided `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, explicit `DJANGO_ALLOWED_HOSTS`, HTTPS, a WSGI server and a web server serving collected static files. See [deployment procedure](docs/TECHNICAL.md#deployment). No external hosting or GitHub publication has been performed.
