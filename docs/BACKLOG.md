# Development backlog

This records actual implementation status. The three sprints below are the proposal's three functional increments, grouped from the Git history; they are not claimed as timed Scrum iterations. Work added after the proposal's scope, and the deployment, are listed after them. Create a task with the issue template for each new change and record its acceptance checks in the pull request template.

## Sprint increments

| Sprint | Goal | Delivered | Evidence |
| --- | --- | --- | --- |
| I: Accounts, profiles and jobs | Let job seekers and employers register, build profiles and post jobs | Role-based registration and login, structured seeker profiles (unique skill tags, certification and experience levels, summary, portfolio, evidence links), employer profiles, job creation, editing, closing and deletion, Django administration | Baseline commit `528ffef` (18 September 2026); account, profile, skill-uniqueness and job lifecycle tests |
| II: Matching and evaluation | Rank candidates for jobs and jobs for candidates, and explain each score | Capped TF-IDF with cosine similarity, certification and experience multipliers, both ranking directions, score explanations, offline Precision@k and SUS tooling, seeded synthetic demo, development environment and CI | Baseline `528ffef`, environment and CI `28f4bcf`, launcher fix `66ad397`; algorithm and ranking tests, passing CI on Windows and Linux |
| III: Security, access and experience | Protect accounts, let one person use both sides of the platform and improve daily use | Redesigned landing, login and registration, authenticator-app 2FA (optional for users, mandatory for staff), login reminder, one-time recovery codes, one account holding both roles with a switch, Google and GitHub sign-in, dashboards, saved jobs and saved candidates | PRs #18, #19, #20, #22 (merged 22 October 2026), #24 and #25 (22 October 2026), #27 and #29 (29 October 2026); 255 passing tests at the end of this sprint |
| Beyond the proposal: recruitment workflow and deployment | Let employers and job seekers connect, manage hiring and present themselves, and put the system online | Applications and invitations (connections) with accept, decline and withdraw; hiring stages and interview scheduling; messaging with edit and unsend; notification bell; company profiles and company pages; profile photos, logos and cover images; job closing dates and reopening; minimum match filter; administration dashboard (overview, reports, settings directory and search); get-started and privacy pages; deployment on PythonAnywhere | PRs #30 (10 November 2026), #31 and #32 (12 November 2026); 459 passing tests; live site at https://skillmatcher.pythonanywhere.com from 12 November 2026 |

Sprints I and II reached the repository in one baseline commit, so their dates are not separable in Git history.

## Status of work items

| Work item | Status | Completion evidence or next action |
| --- | --- | --- |
| Authentication and structured profiles | Implemented | Registration, profile persistence, duplicate-skill and role tests |
| Job posting and bidirectional matching | Implemented | Job lifecycle, scoring constants, repetition cap and ranking tests |
| Automated regression checks | Implemented | 459 tests (39.7 s on Python 3.12) covering application behavior, startup, MFA, recovery codes, role switching, provider sign-in, dashboards, saved items, connections and messaging, concurrency, deadlines, match filters, company pages, image uploads, the administration dashboard and the privacy page; see [VERIFICATION.md](VERIFICATION.md) |
| Authenticator-app 2FA | Implemented | Optional user enrollment, mandatory admin setup and login, verified sessions, optional login reminder; see [MFA guide](MFA.md) |
| MFA recovery codes | Implemented | One-time hashed recovery codes generated at setup and replaceable from account security; see the recovery section of the [MFA guide](MFA.md) |
| Dual role (one account, two workspaces) | Implemented | `Account.active_role`, `switch_role` view and sidebar toggle; a user gets the other profile on first switch; see [technical documentation](TECHNICAL.md) |
| Single sign-on (Google, GitHub) | Implemented | django-allauth sign-in that keeps the existing MFA gates; links to an existing account only when the provider email is verified, otherwise from Connected accounts after a password login; 65 tests in `test_sso.py` and the provider setup guide in the README. Microsoft is not included |
| Dashboards, saved jobs and saved candidates | Implemented | Seeker and employer dashboards, a redesigned profile editor, saved jobs for seekers and saved candidates for employers (`SavedJob`, `SavedCandidate`, migrations 0004 and 0005) |
| Connections, hiring stages and messaging | Implemented | `Connection`, `Message` and `ConnectionActivity` (migrations 0008 and 0010); 20 new requests per rolling 24 hours, 15-minute edit/unsend window, serialised transactions; tests in `test_connections.py`, `test_connection_detail.py`, `test_connection_history.py`, `test_connection_concurrency.py`, `test_chat_messages.py` and `test_notification_bell.py` |
| Company profiles, company pages and profile images | Implemented | Company fields (migration 0006) and re-encoded JPEG/PNG/WebP uploads of up to 5 MB and 12 megapixels (migration 0007); `test_company_profile.py`, `test_company_detail.py`, `test_profile_images.py` |
| Job deadlines and minimum match filter | Implemented | Closing date in the Africa/Nairobi time zone (migration 0009) and a 30/50/70/80/90 percent filter applied after ranking; `test_job_deadlines.py`, `test_match_filters.py` |
| Administration dashboard | Implemented | Overview, reports, settings directory and search behind two-factor verification; `test_admin_dashboard.py` |
| Get-started, privacy page, profile dropdown | Implemented | Public `/privacy/` page (used for the Google consent screen), `/get-started/`, and the profile dropdown; `test_privacy.py`, `test_get_started.py`, `test_profile_dropdown.py` |
| Reproducible development setup | Implemented | Python 3.12, pinned locks, one-command `start.cmd` launcher and environment inspector |
| Formatting and lint automation | Implemented | Ruff, djLint and first-party asset checks |
| Hosted continuous integration | Verified | Startup fix passed Windows and Linux in [run 35345983695](https://github.com/Trix0909/SkillMatch/actions/runs/35345983695); Windows CI exercises the launcher on a fresh environment |
| Public deployment | Done | Live on the free PythonAnywhere plan at https://skillmatcher.pythonanywhere.com since 12 November 2026 (one web worker, HTTPS enforced, Google consent screen published, GitHub OAuth app registered). The live database is the development laptop's database, so it contains the demonstration accounts. Not load-tested; steps in [technical documentation](TECHNICAL.md#deployment) |
| Matching evaluation | Rule-suggested labels only | An automated run with rule-suggested labels gave Precision@5 0.40 and Precision@10 0.20 on the synthetic demonstration data; those labels were not reviewed by a person. Human review of all candidate/job pairs is still to do |
| SUS and user acceptance study | Not done | No participants have taken part yet. Collect actual responses and task observations using the evaluation protocol |
| Microsoft sign-in | Not built | Only Google and GitHub are configured |
| Open pull request | #26 | An older sidebar styling fix that was not merged |

Before marking an implementation task complete, run `tools/dev.py check`, inspect the staged diff and update relevant documentation. For UI changes, also run browser checks at desktop and mobile sizes. Keep new product features aligned with `docs/REQUIREMENTS.md` or obtain an explicit scope change.
