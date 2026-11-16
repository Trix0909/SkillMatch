# Implementation verification

The automated suite was last run on 15 November 2026 against the merged master branch (commit `2dd71d9`) using Python 3.12, Django 5.2 and SQLite: **459 tests passed**. Earlier sections record the state of the earlier stages; the first-stage list and the browser evidence below date from 18 September 2026 and were not rerun for this update.

## Automated results

**459 tests pass** with a freshly migrated temporary database (about 40 seconds). By test module:

| Area | Tests |
| --- | --- |
| Application, algorithm and role switching (`test_project`) | 49 |
| Core MFA (`test_mfa`) | 37 |
| MFA login reminder (`test_mfa_reminder`) | 14 |
| MFA recovery codes (`test_mfa_recovery`) | 29 |
| Google and GitHub sign-in (`test_sso`) | 65 |
| Dashboards (`test_dashboard`), profile editor (`test_profile_editor`), saved jobs (`test_saved_jobs`) and saved candidates (`test_saved_candidates`) | 6 + 7 + 13 + 19 = 45 |
| Connections: requests and responses (`test_connections`), detail page (`test_connection_detail`), history (`test_connection_history`) and concurrency (`test_connection_concurrency`) | 45 + 15 + 7 + 12 = 79 |
| Messaging (`test_chat_messages`) and notification bell (`test_notification_bell`) | 19 + 4 = 23 |
| Job deadlines (`test_job_deadlines`) and minimum match filter (`test_match_filters`) | 21 + 13 = 34 |
| Company profiles (`test_company_profile`), company pages (`test_company_detail`) and profile images (`test_profile_images`) | 19 + 4 + 8 = 31 |
| Administration dashboard (`test_admin_dashboard`) | 16 |
| Profile dropdown, get-started, privacy and workspace controls (`test_profile_dropdown`, `test_get_started`, `test_privacy`, `test_workspace_controls`) | 9 + 4 + 4 + 4 = 21 |
| Startup (`test_startup`) and environment (`test_environment`) | 5 + 11 = 16 |

The 49 application tests include account role switching. The behaviors below were the first 40:

- Exact certification and experience constants, weighted formula and ranking for equal-text profiles.
- Term-frequency saturation at 2 before TF-IDF; repeated text cannot keep increasing its term count.
- Empty vocabulary, stop-word-only queries, empty corpora and no-overlap results.
- C++, C#, .NET and sentence-ending punctuation handling.
- Bio and portfolio contribution; evidence URLs excluded from scoring.
- Incomplete/inactive profiles, closed jobs and inactive employers excluded from eligible matching corpora.
- Both ranking directions and stable tie-breaking.
- Unicode/whitespace normalization, case-insensitive skill uniqueness and database level constraints.
- Atomic profile updates, safe evidence schemes and registration with hashed passwords.
- Registration role restrictions, unauthorized profile access, owner-scoped job changes and candidate ranking.
- POST/CSRF protection, safe login redirection and HTML output escaping.
- Job creation, closure and deletion; role-specific templates and result pagination.
- Relevance thresholds, Precision@k denominators and SUS scoring.
- Manual-label requirements, changed-corpus fingerprint rejection, empty/duplicate SUS response rejection.
- Startup dependency reuse, setup when dependencies or the interpreter are missing, included lock-file checks, and preventing server startup after migration failure.

`manage.py check` and the production-setting `check --deploy` reported no issues. Migrations match the models (`makemigrations --check --dry-run`). `pip check` reported no broken requirements. Static-file collection completed successfully. This checks configuration and dependencies. The deployment on PythonAnywhere is described under the 15 November 2026 status below.

## Browser checks

Headless Edge exercised the actual local Django server at desktop width 1440 and mobile width 390:

- Landing page and responsive layout.
- Seeker sign-in, ten job recommendations and expanded score details.
- Duplicate skill feedback, adding/removing a tag and saving a profile.
- Employer sign-in, free-text candidate search and full profile inspection.
- Query-preserving pagination across the 30 synthetic candidate profiles.
- Mobile employer/candidate pages, registration role changes and sign-out.

No JavaScript page errors or HTTP 5xx responses occurred, and inspected pages had no horizontal document overflow. Desktop landing, profile, recommendations and mobile candidate screenshots were visually reviewed. Browser snapshots and the machine-readable check report are local QA material in ignored `tmp/browser/`.

## Research status

The demonstration database contains 31 synthetic candidate profiles and 10 synthetic job posts. The exported label sheet has 310 candidate/job pairs with suggested rule values and blank reviewer/relevance fields. These are not participant findings.

An automated run that used the rule-suggested labels, which no person reviewed, gave Precision@5 of 0.40 and Precision@10 of 0.20. This is a check that the tooling works, not a finding about relevance. Formal Precision@k results need a frozen study corpus and completed manual relevance labels. SUS and user acceptance testing need actual participants and their responses. No accuracy improvement, usability score, recruitment outcome or completed Scrum schedule is claimed by this implementation report.

## Reproduce

Run the Django commands in the README. `tools/browser_check.cjs` additionally needs Playwright and Microsoft Edge, uses only the local demo application, and reads generated credentials from `demo-credentials.txt`. Playwright is a QA dependency, not a requirement for running SkillMatch. Set `PLAYWRIGHT_MODULE` when Playwright is installed outside the default Node.js module path.

## Development environment follow-up (18 September 2026)

The full `tools/dev.py check` workflow passed after source formatting: Ruff lint/format, Django template formatting, CSS/JavaScript/JSON formatting, dependency compatibility, all 35 tests, migration consistency, Django checks, production-setting checks, static-file collection and Git-index checks. Browser checks also passed after formatting, and the desktop landing page was visually inspected.

Setup was rerun successfully with pinned development dependencies and without resetting the database. The environment inspector confirmed Python 3.12.14, current migrations, SQLite integrity `ok`, 30 candidate profiles and 10 job posts. Unicode output is configured for child processes to support the existing Windows folder name.

The GitHub Actions and VS Code configuration files parse successfully. The repository is now connected to `https://github.com/Trix0909/SkillMatch.git`, with `master` tracking `origin/master`. Both hosted Windows and Linux jobs passed for commit `28f4bcf` in [GitHub Actions run 35301744459](https://github.com/Trix0909/SkillMatch/actions/runs/35301744459). These jobs install the locked dependencies and execute the full development validation workflow. See `docs/DEVELOPMENT.md` for the requirement checklist and `docs/BACKLOG.md` for pending research tasks.

## Current status (29 September 2026)

The full `tools/dev.py check` workflow passed with all 40 tests, formatting and lint checks, dependency checks, migration consistency, Django development and production checks, static collection and the Git-index privacy check. `tools/dev.py doctor` confirmed current migrations, SQLite integrity `ok`, 30 candidate profiles and 10 job posts.

The Windows entry point is now `start.cmd`, which prepares the environment when necessary and starts the application without changing PowerShell execution policy. The startup fix at commit `66ad397` passed both Windows and Linux in [GitHub Actions run 35345983695](https://github.com/Trix0909/SkillMatch/actions/runs/35345983695). Windows CI uses the launcher to set up a fresh environment. `SkillMatch.url` opens the local site after the server has started.

Manual study labels, participant SUS responses and user acceptance observations remain outstanding. This update adds no research findings or external deployment claim.

## Current status (23 October 2026)

All 134 tests pass on master after merging 2FA, recovery codes and dual-role support (PRs #18, #19, #20, #22, #24, #25). The startup test `test_migration_failure_prevents_server_start` needs the project virtual environment in `.venv` at the repository root; with another interpreter layout it fails because the launcher cannot find that environment. Browser checks, manual study labels, participant SUS responses and user acceptance observations remain outstanding, and no external deployment has been made.

## Current status (29 October 2026)

The suite has grown to 255 tests after provider sign-in (65 tests), dashboards, the profile editor, saved jobs and saved candidates (45 tests) and environment checks (11 tests) were merged. All 255 pass on Python 3.12 and migrations match the models. The browser checks listed above predate these screens and have not been rerun against them.

## Current status (15 November 2026)

All 459 tests pass on master at `2dd71d9` (Python 3.12, Django 5.2, about 40 seconds). The growth from 255 comes from connections and messaging, company profiles, profile images, job deadlines, the minimum match filter, the administration dashboard and the privacy page (PRs #30, #31 and #32). Migrations 0001 to 0010 match the models.

SkillMatch has been deployed since 12 November 2026 on the free plan of PythonAnywhere at https://skillmatcher.pythonanywhere.com. Google and GitHub sign-in and authenticator-app setup were tried by hand on the live site and worked; these manual checks were not recorded as automated tests. The live database is the development laptop's database, so it includes the demonstration accounts. The site was not load-tested, and the free plan has one web worker.

Still outstanding: human review of the relevance labels, the SUS study with participants, a browser and device matrix, and a rerun of the browser checks above against the newer screens.
