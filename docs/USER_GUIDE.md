# SkillMatch user guide

## Start

SkillMatch is online at https://skillmatcher.pythonanywhere.com (free hosting, so it can be slow). To run your own copy, double-click `start.cmd` in the project folder, or run `.\start.cmd` in its terminal. It prepares the environment and starts the app. Open `http://127.0.0.1:8000` once the server is ready. Keep the terminal open while using SkillMatch; press Ctrl+C to stop.

Select **Get started** and choose **I’m looking for work** or **I’m hiring**, then register with your name, email, username and password. Employers also enter a company name. Registration signs you in and opens profile editing. You can instead use **Continue with Google** or **Continue with GitHub** on the login or registration page; new provider users choose a role and, for employers, a company name before the account is created.

One account can do both jobs. Use the **Job seeking | Hiring** toggle in the sidebar to switch workspace. The first time you switch, you are asked for a company name (to start hiring) or taken to your profile (to start job seeking). Both profiles are kept, and you only see the pages of the workspace you are in. The **privacy policy** (`/privacy/`) and **How matching works** pages are open to everyone.

If demo data has been seeded, use the usernames and generated password in `demo-credentials.txt`. The demo candidates, jobs and accounts are fictional. The live site was started from a demonstration database, so it also contains these demo accounts.

## Account security

Before or after editing a profile, you can open **Two-factor authentication settings** from **My profile** or **Company profile**. It is optional for ordinary users. Confirm your password, scan the QR with a compatible authenticator app, and enter its current code to enable it. Every later login will require that app's code. Staff/superusers, including the demo administrator, must complete setup at their next login. When you enable two-factor authentication you are shown ten one-time **recovery codes**; keep them somewhere safe. A recovery code can be used once instead of an authenticator code at login, and you can generate a fresh set from **Account security** after confirming your password. Disabling two-factor authentication is not available, so retain access to the app or the recovery codes. Google and GitHub accounts are managed under **Connected accounts** in the profile menu; you cannot disconnect your last way of signing in. See the [complete MFA guide](MFA.md).

## Job seekers

1. Open **My profile**. Add each skill using **Add skill** or Enter. Remove a skill with its × button. Repeated names are rejected even if capitalization changes.
2. Choose your certification and experience levels from the prescribed dropdowns.
3. Write your professional summary and describe projects in **Project portfolio**. Be specific about work and skills; repeated keywords are capped during scoring.
4. Optionally enter supporting HTTP(S) links, one per line, and add a profile photo (JPEG, PNG or WebP, up to 5 MB). CV and document uploads are not supported.
5. Select **Save profile**. Skills, summary and portfolio must all be present to participate in matching.
6. Open **My matches** for ranked job recommendations. **Why this match?** explains the exact score. Select **View opportunity** for the full job description and requirements.
7. Use **Browse jobs** to explore all open jobs or search job text by keyword. This page is ordered newest first; **My matches** is ordered by relevance.
8. Use **Save** on a job to keep it in **Saved jobs**. Your saved list is private.
9. Select the company name on a job to read the employer's company page.
10. Select **Apply** on an open job to send an application (see Connections below). Your dashboard summarises recent matches, profile progress and connection activity.

## Employers

1. Complete **Company profile** with your company name and description. Optional fields (tagline, summary, location, size, industry, culture, focus areas and links) and a logo and cover image are shown to job seekers on your company page, with a preview as you edit.
2. From **My job posts**, select **Post a job**. Enter a title, description, required skills and minimum certification/experience levels.
3. Select **Post job & find matches** to see ranked candidate profiles.
4. Inspect highlighted skills and expand **Why this match?** to see base similarity and qualification multipliers.
5. Open **View profile** to read the candidate’s summary, portfolio and optional supporting links.
6. Use **Find candidates** to search with a job description or keywords without saving a job post. **Save** a candidate to keep them in your private **Saved candidates** list, or select **Invite** to invite them to a job.
7. Manage existing jobs with **Edit**, **Close job**, **Reopen job** and **Delete**. Closing removes a job from seeker recommendations. Deletion has a confirmation page and permanently removes that job.

### Application deadlines

Jobs may have an optional application deadline. They remain open throughout that date in **Africa/Nairobi**, expiring at midnight at the start of the next day. An expired job stops appearing among open jobs and recommendations and cannot receive new applications, invitations or saves. Existing saved jobs remain listed as unavailable. Existing requests can still be accepted, and recruitment conversations can continue after deadline expiry.

**Close job** manually pauses the job and its connections without removing its deadline. **Reopen job** is explicit: for a passed deadline, choose a new date (today or later) or explicitly choose **No deadline**, then **Save and reopen**. Opening or cancelling this form changes nothing. An ordinary edit keeps the manual open/closed state: extending or removing a passed deadline reopens applications only if the job was not manually closed. An unchanged historical deadline may be kept when editing; a newly chosen past deadline is rejected. Job status distinguishes **Open**, **Closed by employer**, and **Closed: deadline passed**.

## Connections, hiring stages and messages

An application (from a job seeker) or an invitation (from an employer) creates a **connection** that is pending until the other person accepts or declines it. The person who sent it can **Withdraw** it while it is pending. You can send up to 20 new requests in a rolling 24 hours. A request is refused if the job is closed or past its deadline, if either account is inactive, or if the job seeker's profile is incomplete, and there is only ever one connection between a job and a job seeker. Open **Connections** from the sidebar to see them.

After a connection is accepted, the employer can move it through the stages **New, Shortlisted, Interview and Offered**, or mark it **Not selected**. Stages move one step at a time. For an interview the employer sets a future date and time, which can be rescheduled. The job seeker's email and phone number become visible to the employer only after acceptance. The connection page keeps a history of every request, response and stage change.

Both people can exchange messages (up to 2,000 characters) on the connection page. You can **Edit** or **Unsend** your own message within 15 minutes of sending it. Messages appear when the page is opened or refreshed; they are not pushed to you. The bell in the top bar shows unread requests, stage changes and messages.

## Understanding scores

On **My matches**, a job's candidate matches, or **Find candidates**, use **Minimum match** to choose **Any match**, **30%+**, **50%+**, **70%+**, **80%+**, or **90%+**, then submit the filter/search form. The threshold uses the displayed text-similarity percentage; it does not change weighted ranking. **Any match** is the default and includes zero-percent results. **Clear filter** retains your search keywords or current job and returns to the first page. Counts reflect the filtered results, while the seeker's **Best match** still shows the first result from the full ranking.

Similarity measures keyword overlap, then the candidate’s self-reported levels multiply it. Scores range from 0 to 3.6 and are not probabilities. A zero score means no meaningful token overlap. Higher scores do not guarantee qualification; compare the listed role requirements and inspect the profile.

Skill highlights indicate exact matching tag text. A score can also arise from bio or portfolio text even with no highlighted skill tag. Evidence URLs are for manual inspection and do not affect the algorithm. The platform does not verify claims, ownership of links, certifications or project work.

## Administration

Create an administrator with `python manage.py createsuperuser` or use the demo admin. Open `/admin/` and complete two-factor verification. The overview shows totals, a growth chart and recent activity, **Reports** lists new users and new job posts for each month, **Search** finds the administration pages you can open (such as users, profiles and jobs), and the usual Django pages manage users, active status, profiles, jobs and optional skill categories. Deactivate a user to prevent sign-in and remove that person’s candidates/jobs from matching. Only staff with appropriate permissions can use administration.

## Sign out

Open the profile menu (your name and photo) and choose **Log out**. Signing out uses a CSRF-protected POST request.

## Troubleshooting

- No recommendations: complete your profile or check that there are open jobs.
- No candidates: candidates need active accounts and complete profiles.
- Form error: correct the inline field message; existing submitted values remain available.
- Duplicate skill: remove or rename the existing tag rather than adding it again.
- Cannot access a page: some pages are restricted to a role or to the job’s owner.
- Cannot apply or invite: the job may be closed or past its deadline, your profile may be incomplete, or you may have reached the 20-request limit.
- Google or GitHub sign-in says the email already exists: sign in with your password first, then connect the provider from **Connected accounts**.
- Port 8000 is occupied: run `python manage.py runserver 127.0.0.1:8001` and open that address.
- First start: run migrations before opening the application. The virtual environment needs the packages in `requirements.txt`.
