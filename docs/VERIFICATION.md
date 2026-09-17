# Implementation verification

Verified locally on 18 September 2026 using Python 3.12, Django 5.2.17, scikit-learn 1.7.2, SQLite and headless Microsoft Edge.

## Automated results

**35 Django tests passed** with a freshly migrated temporary database. Covered behaviors:

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

`manage.py check` and the production-setting `check --deploy` reported no issues. Migrations match the models (`makemigrations --check --dry-run`). `pip check` reported no broken requirements. Static-file collection completed successfully. This checks configuration and dependencies; it does not mean external hosting has been configured.

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

The demonstration database contains 30 synthetic profiles and 10 synthetic job posts. The exported label sheet has 300 candidate/job pairs with suggested rule values and blank reviewer/relevance fields. These are not participant findings.

Formal Precision@k results need a frozen study corpus and completed manual relevance labels. SUS and user acceptance testing need actual participants and their responses. No accuracy improvement, usability score, recruitment outcome or completed Scrum schedule is claimed by this implementation report.

## Reproduce

Run the Django commands in the README. `tools/browser_check.cjs` additionally needs Playwright and Microsoft Edge, uses only the local demo application, and reads generated credentials from `demo-credentials.txt`. Playwright is a QA dependency, not a requirement for running SkillMatch. The script defaults to the bundled Codex package path; set `PLAYWRIGHT_MODULE` to your own Playwright module path when running elsewhere.

