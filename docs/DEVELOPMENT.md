# Development environment and workflow

This guide maps the development setup to the requested project requirements. Product scope and the matching algorithm remain governed by the three original source files.

## Environment

Use **Python 3.12** and Git. The application needs no API keys, cloud account, database server or JavaScript build service. Bootstrap is stored locally. Microsoft Edge and Node.js/Playwright are optional for browser QA.

From the repository root on Windows:

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe tools/dev.py doctor
.\start.ps1
```

If `python` does not point to Python 3.12, use `setup.ps1 -Python 'C:\path\to\python.exe'`. Setup creates `.venv`, installs exact development dependencies, runs migrations and checks Django. It is safe to rerun and does not reset the database or demo passwords.

On Linux/macOS:

```bash
python3.12 tools/dev.py setup
.venv/bin/python tools/dev.py doctor
.venv/bin/python tools/dev.py run
```

`.python-version` records the expected interpreter. `requirements.txt` identifies the direct application dependencies; `requirements-lock.txt` pins the resolved application set. `requirements-dev.txt` identifies development tools and `requirements-dev-lock.txt` pins their full resolved set. Setup and CI consume the locked set.

`.env.example` documents supported environment variables. It is a reference, not a loaded secrets file. Set values in your shell or hosting service. Local defaults work without configuration; production requires an environment-provided secret.

## Organization and code standards

| Location | Responsibility |
| --- | --- |
| `config/` | Django configuration, root URLs and WSGI entry point |
| `skillmatch/` | Models, validation, views, matching and evaluation logic |
| `skillmatch/migrations/` | Versioned database schema changes |
| `skillmatch/tests/` | Behavioral and security regression tests |
| `templates/` | Server-rendered pages and shared partials |
| `static/css/`, `static/js/` | Readable first-party frontend source |
| `static/vendor/` | Bootstrap distribution and license; excluded from formatting |
| `tools/` | Development commands, formatting, repository checks and QA helpers |
| `docs/` | Requirements, design, user, technical and evaluation documentation |
| `evaluation/` | Versioned blank templates and ignored local study records |
| `.github/` | CI, issue and pull request templates |

Ruff checks Python syntax/imports and formats Python. djLint formats Django templates. The asset formatter uses pinned CSS/JavaScript beautifiers and consistent JSON indentation. `.editorconfig` and `.gitattributes` specify UTF-8, indentation and LF line endings. Vendor code retains its upstream format and license.

In VS Code, select the `.venv` interpreter. The checked-in tasks expose validation, formatting, environment inspection and the Django server. The Django debug configuration starts on localhost with automatic reloading disabled for stable debugging. Extension recommendations are suggestions; setup does not install editor extensions.

## Automation

```powershell
# Format first-party Python, Django templates, CSS, JavaScript and editor JSON.
.\.venv\Scripts\python.exe tools/dev.py format

# Run the development gate before committing.
.\.venv\Scripts\python.exe tools/dev.py check

# Inspect Python, dependencies, Git, migration state and SQLite integrity/counts.
.\.venv\Scripts\python.exe tools/dev.py doctor
```

Validation runs linting, formatting checks, dependency checks, Django system checks, migration-drift detection, the test suite, production-setting checks, static collection and a Git-index privacy check. Commands stop on failure. Django tests use their own temporary database. Formatting changes source files; `check` only checks source formatting and writes generated static files to the ignored output directory.

The GitHub Actions workflow runs setup and validation on **Windows and Linux**, on pushes, pull requests and manual dispatch. It uses read-only repository permissions and a 15-minute timeout. The repository is connected to [Trix0909/SkillMatch](https://github.com/Trix0909/SkillMatch); see its [Actions page](https://github.com/Trix0909/SkillMatch/actions) for hosted results.

## Git workflow

The repository has a real initial application commit. Development setup is recorded in a separate commit so implementation and tooling changes can be reviewed independently. No historical sprint dates or commits are fabricated.

For subsequent work:

```bash
git switch -c codex/describe-the-change
# Implement the task, then run tools/dev.py check.
git diff
git add path/to/changed/files
python tools/check_repository.py
git diff --cached
git commit -m "fix: describe the resulting behavior"
git status
```

Use focused commits and the issue/pull request templates to record source requirements, acceptance criteria and validation evidence. Avoid committing generated databases, secrets, credentials or study data. The repository checker examines staged blobs and rejects prohibited paths and known local secret values; it is a targeted guard, not a general-purpose secret scanner.

The `origin` remote is `https://github.com/Trix0909/SkillMatch.git`. Local `master` tracks `origin/master`. Push reviewed commits with `git push`; this triggers hosted validation. Credentials, SQLite files and local study records remain excluded from version control.

## Prepared resources

Database schema is fully represented by committed migrations. The existing local SQLite database and credentials are preserved. The deterministic synthetic-data command supplies 30 profiles and 10 jobs with randomly generated demo credentials. It refuses to overwrite existing demo accounts.

```powershell
# Optional, only for a database without existing demo accounts.
.\.venv\Scripts\python.exe tools/dev.py demo
```

The existing evaluation label sheet stays local. Generate new sheets from the actual database, so IDs and fingerprints match. Blank SUS templates are versioned; participant responses, reviewer labels and computed result JSON files are ignored. The original PDF/DOCX/PPTX files remain outside the repository and are not modified. `tools/extract_sources.py --help` documents explicit file arguments without assuming a developer's home directory.

No external APIs are applicable: the proposal excludes third-party job feeds and credential services. Evidence links are stored as URLs and never fetched by the server.

## Requirement checklist

| Requested requirement | Evidence |
| --- | --- |
| Properly configured development environment | Python version, isolated `.venv`, locked dependencies, setup script, environment inspector, VS Code configuration |
| Clean, professional codebase | Separation of Django concerns, readable formatted source, lint/format settings, guides and tests |
| Code under Git version control | Initial implementation commit, separate development-workflow commit, tracked source/migrations/configuration, protected private resources |
| Relevant resources prepared | Migrated SQLite database, reproducible synthetic dataset, local Bootstrap, evaluation templates and source/design documentation |
| Development automation | One-command formatting/checks/setup, editor tasks, CI workflow, issue/PR templates and repository guard |
