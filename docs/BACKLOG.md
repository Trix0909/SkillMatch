# Development backlog

This records actual implementation status. The three sprints below are the proposal's three functional increments, grouped from the Git history; they are not claimed as timed Scrum iterations. Create a task with the issue template for each new change and record its acceptance checks in the pull request template.

## Sprint increments

| Sprint | Goal | Delivered | Evidence |
| --- | --- | --- | --- |
| I: Accounts, profiles and jobs | Let job seekers and employers register, build profiles and post jobs | Role-based registration and login, structured seeker profiles (unique skill tags, certification and experience levels, summary, portfolio, evidence links), employer profiles, job creation, editing, closing and deletion, Django administration | Baseline commit `528ffef` (18 September 2026); account, profile, skill-uniqueness and job lifecycle tests |
| II: Matching and evaluation | Rank candidates for jobs and jobs for candidates, and explain each score | Capped TF-IDF with cosine similarity, certification and experience multipliers, both ranking directions, score explanations, offline Precision@k and SUS tooling, seeded synthetic demo, development environment and CI | Baseline `528ffef`, environment and CI `28f4bcf`, launcher fix `66ad397`; algorithm and ranking tests, passing CI on Windows and Linux |
| III: Security, access and experience | Protect accounts, let one person use both sides of the platform and improve daily use | Redesigned landing, login and registration, authenticator-app 2FA (optional for users, mandatory for staff), login reminder, one-time recovery codes, one account holding both roles with a switch, Google and GitHub sign-in, dashboards, saved jobs and saved candidates | PRs #18, #19, #20, #22 (30 September to 22 October 2026), #24 and #25 (22 October 2026), #27 and #29 (29 October 2026); 255 passing tests |

Sprints I and II reached the repository in one baseline commit, so their dates are not separable in Git history.

## Status of work items

| Work item | Status | Completion evidence or next action |
| --- | --- | --- |
| Authentication and structured profiles | Implemented | Registration, profile persistence, duplicate-skill and role tests |
| Job posting and bidirectional matching | Implemented | Job lifecycle, scoring constants, repetition cap and ranking tests |
| Automated regression checks | Implemented | 255 tests covering application behavior, startup, MFA, recovery codes, role switching, provider sign-in, dashboards and saved items, plus local browser checks |
| Authenticator-app 2FA | Implemented | Optional user enrollment, mandatory admin setup and login, verified sessions, optional login reminder; see [MFA guide](MFA.md) |
| MFA recovery codes | Implemented | One-time hashed recovery codes generated at setup and replaceable from account security; see the recovery section of the [MFA guide](MFA.md) |
| Dual role (one account, two workspaces) | Implemented | `Account.active_role`, `switch_role` view and sidebar toggle; a user gets the other profile on first switch; see [technical documentation](TECHNICAL.md) |
| Single sign-on (Google, GitHub) | Implemented | django-allauth sign-in that keeps the existing MFA gates; links to an existing account only when the provider email is verified, otherwise from Connected accounts after a password login; 65 tests in `test_sso.py` and the provider setup guide in the README. Microsoft is not included |
| Dashboards, saved jobs and saved candidates | Implemented | Seeker and employer dashboards, a redesigned profile editor, saved jobs for seekers and saved candidates for employers (`SavedJob`, `SavedCandidate`, migrations 0004 and 0005) |
| Reproducible development setup | Implemented | Python 3.12, pinned locks, one-command `start.cmd` launcher and environment inspector |
| Formatting and lint automation | Implemented | Ruff, djLint and first-party asset checks |
| Hosted continuous integration | Verified | Startup fix passed Windows and Linux in [run 35345983695](https://github.com/Trix0909/SkillMatch/actions/runs/35345983695); Windows CI exercises the launcher on a fresh environment |
| Public deployment | Not done | Application has not been hosted externally; deployment procedure is in [technical documentation](TECHNICAL.md#deployment) |
| Manual matching evaluation | Awaiting study labels | Freeze the corpus and review all candidate/job pairs before measuring Precision@k |
| SUS and user acceptance study | Awaiting participants | Collect actual responses and task observations using the evaluation protocol |

Before marking an implementation task complete, run `tools/dev.py check`, inspect the staged diff and update relevant documentation. For UI changes, also run browser checks at desktop and mobile sizes. Keep new product features aligned with `docs/REQUIREMENTS.md` or obtain an explicit scope change.
