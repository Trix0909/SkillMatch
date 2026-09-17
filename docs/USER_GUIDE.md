# SkillMatch user guide

## Start

Run `start.ps1` from the project folder, or use the `manage.py runserver` command in the README. Open `http://127.0.0.1:8000`.

Select **Get started** to register. Enter your name, email, username and password. Choose **I’m looking for work** or **I’m hiring**. Employers also enter a company name. Registration signs you in and opens profile editing. Your selected role cannot be switched through a web request or form; use separate accounts for the two roles.

If demo data has been seeded, use the usernames and generated password in `demo-credentials.txt`. The demo is fictional and intended for local demonstrations only.

## Job seekers

1. Open **My profile**. Add each skill using **Add skill** or Enter. Remove a skill with its × button. Repeated names are rejected even if capitalization changes.
2. Choose your certification and experience levels from the prescribed dropdowns.
3. Write your professional summary and describe projects in **Project portfolio**. Be specific about work and skills; repeated keywords are capped during scoring.
4. Optionally enter supporting HTTP(S) links, one per line. Files and CV uploads are not supported.
5. Select **Save profile**. Skills, summary and portfolio must all be present to participate in matching.
6. Open **My matches** for ranked job recommendations. **Why this match?** explains the exact score. Select **View opportunity** for the full job description and requirements.
7. Use **Browse jobs** to explore all open jobs or search job text by keyword. This page is ordered newest first; **My matches** is ordered by relevance.

## Employers

1. Complete **Company profile** with your company name and description.
2. From **My job posts**, select **Post a job**. Enter a title, description, required skills and minimum certification/experience levels.
3. Select **Post job & find matches** to see ranked candidate profiles.
4. Inspect highlighted skills and expand **Why this match?** to see base similarity and qualification multipliers.
5. Open **View profile** to read the candidate’s summary, portfolio and optional supporting links.
6. Use **Find candidates** to search with a job description or keywords without saving a job post.
7. Manage existing jobs with **Edit**, **Close job**, **Reopen job** and **Delete**. Closing removes a job from seeker recommendations. Deletion has a confirmation page and permanently removes that job.

## Understanding scores

Similarity measures keyword overlap, then the candidate’s self-reported levels multiply it. Scores range from 0 to 3.6 and are not probabilities. A zero score means no meaningful token overlap. Higher scores do not guarantee qualification; compare the listed role requirements and inspect the profile.

Skill highlights indicate exact matching tag text. A score can also arise from bio or portfolio text even with no highlighted skill tag. Evidence URLs are for manual inspection and do not affect the algorithm. The platform does not verify claims, ownership of links, certifications or project work.

## Administration

Create an administrator with `python manage.py createsuperuser` or use the local demo admin. Open `/admin/`. Django administration can manage users, active status, profiles, jobs and optional skill categories. Deactivate a user to prevent sign-in and remove that person’s candidates/jobs from matching. Only staff with appropriate permissions can use administration.

## Sign out

Use the sign-out arrow beside your name in the sidebar. On mobile, use **Sign out** in the navigation. Signing out uses a CSRF-protected POST request.

## Troubleshooting

- No recommendations: complete your profile or check that there are open jobs.
- No candidates: candidates need active accounts and complete profiles.
- Form error: correct the inline field message; existing submitted values remain available.
- Duplicate skill: remove or rename the existing tag rather than adding it again.
- Cannot access a page: some pages are restricted to a role or to the job’s owner.
- Port 8000 is occupied: run `python manage.py runserver 127.0.0.1:8001` and open that address.
- First start: run migrations before opening the application. The virtual environment needs the packages in `requirements.txt`.
