# Development backlog

This records actual implementation status, not elapsed Scrum sprint dates. Create a task with the issue template for each new change and record its acceptance checks in the pull request template.

| Work item | Status | Completion evidence or next action |
| --- | --- | --- |
| Authentication and structured profiles | Implemented | Registration, profile persistence, duplicate-skill and role tests |
| Job posting and bidirectional matching | Implemented | Job lifecycle, scoring constants, repetition cap and ranking tests |
| Automated regression checks | Implemented | 40 tests covering application behavior and startup, plus local browser checks |
| Reproducible development setup | Implemented | Python 3.12, pinned locks, one-command `start.cmd` launcher and environment inspector |
| Formatting and lint automation | Implemented | Ruff, djLint and first-party asset checks |
| Local Git history | Implemented | Application baseline and development workflow commits |
| Hosted continuous integration | Verified | Startup fix passed Windows and Linux in [run 35345983695](https://github.com/Trix0909/SkillMatch/actions/runs/35345983695); Windows CI exercises the launcher on a fresh environment |
| Manual matching evaluation | Awaiting study labels | Freeze the corpus and review all candidate/job pairs before measuring Precision@k |
| SUS and user acceptance study | Awaiting participants | Collect actual responses and task observations using the evaluation protocol |

Before marking an implementation task complete, run `tools/dev.py check`, inspect the staged diff and update relevant documentation. For UI changes, also run browser checks at desktop and mobile sizes. Keep new product features aligned with `docs/REQUIREMENTS.md` or obtain an explicit scope change.
