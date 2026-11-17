# SkillMatch test case record

This file is the full record of the 39 test cases summarised in Table 5.5 of the project report (Section 5.4.2). It lists, for each test case, its requirement traceability, the scenario and data used, the expected result, and the actual result with its evidence and verdict. Automated results refer to the Django test suite in `skillmatch/tests/` (459 automated tests passed on commit 2dd71d9, 15 November 2026, Python 3.12, Linux). Cases that were not executed, or only partly executed, say so in their actual result.

## TC-001

- **Traceability:** FR-01, NFR-02
- **Scenario, data and conditions:** Register a new job seeker with a valid form; register an employer without a company name.
- **Expected result:** Seeker account, role and empty profile created with a hashed password; employer form rejected with a field error.
- **Actual result, evidence and verdict:** Seeker saved with a hashed password, role seeker and an empty profile; the employer form returned “Enter your company name.” and no account was created. 2 tests in test_project.py passed.

## TC-002

- **Traceability:** FR-03
- **Scenario, data and conditions:** Submit registration with role=admin, is_staff and is_superuser fields.
- **Expected result:** No account created; role cannot be escalated.
- **Actual result, evidence and verdict:** The form was shown again (HTTP 200) and no account was created. 1 test in test_project.py passed.

## TC-003

- **Traceability:** FR-02, NFR-04
- **Scenario, data and conditions:** Request five protected pages anonymously; submit login with an external next address.
- **Expected result:** Redirect to the login page; after login, redirect to the internal home page only.
- **Actual result, evidence and verdict:** Five pages returned a 302 redirect to the login page; with an external next address, login redirected to the internal home page only. 2 tests in test_project.py passed.

## TC-004

- **Traceability:** FR-03
- **Scenario, data and conditions:** Signed-in seeker requests employer pages and another seeker's profile.
- **Expected result:** HTTP 403 for every request.
- **Actual result, evidence and verdict:** HTTP 403 for every request. 1 test in test_project.py passed.

## TC-005

- **Traceability:** FR-03, FR-08
- **Scenario, data and conditions:** Second employer requests edit, close, delete and candidate ranking for the first employer's job; employer posts a job with a forged employer field.
- **Expected result:** HTTP 404 and job unchanged; new job owned by the signed-in employer.
- **Actual result, evidence and verdict:** HTTP 404 for GET and POST and the job stayed active; the job posted with a forged employer field belonged to the signed-in employer. 2 tests in test_project.py passed.

## TC-006

- **Traceability:** FR-05, FR-06, DR-03
- **Scenario, data and conditions:** Enter skills with extra spaces, different letter case and full-width characters; insert a duplicate skill directly into the database.
- **Expected result:** Names normalised; duplicates rejected by the form and by the database constraint.
- **Actual result, evidence and verdict:** “  Data   Analysis  ” became “Data Analysis”; a duplicate insert raised IntegrityError (report Figure 5.3). 2 tests in test_project.py passed.

## TC-007

- **Traceability:** FR-04, FR-07, DR-04
- **Scenario, data and conditions:** Save a profile that adds and removes skills and an https link; submit javascript:, file: and ftp: links.
- **Expected result:** Profile and link saved; unsafe schemes rejected with a field error.
- **Actual result, evidence and verdict:** Profile and https link saved; javascript:, file: and ftp: links gave an error on the links field. 2 tests in test_project.py passed.

## TC-008

- **Traceability:** DR-02
- **Scenario, data and conditions:** Update a stored certification level to an invented value.
- **Expected result:** Database rejects the update.
- **Actual result, evidence and verdict:** IntegrityError raised (1 automated test in test_project.py). Pass.

## TC-009

- **Traceability:** FR-08, FR-19, FR-20
- **Scenario, data and conditions:** Close a job with GET and then POST; check the seeker job list; open the delete page and then confirm deletion.
- **Expected result:** GET refused (405); closed job hidden from seekers; job deleted only after POST.
- **Actual result, evidence and verdict:** GET returned HTTP 405; the closed job was hidden from seekers (HTTP 403 on its page) and deleted only after POST. 2 tests in test_project.py passed.

## TC-010

- **Traceability:** FR-10, FR-11, FR-12
- **Scenario, data and conditions:** Rank two profiles with identical text and different levels; apply all 16 multiplier combinations to a base score of 0.5.
- **Expected result:** Equal base scores; higher-level profile first; every final score equals base × certification × experience.
- **Actual result, evidence and verdict:** Equal base scores and the higher-level profile first; one score equalled base × 1.6 × 1.5 and all 16 combinations equalled base × certification × experience. 2 tests in test_project.py passed.

## TC-011

- **Traceability:** FR-09, NFR-08
- **Scenario, data and conditions:** Compare "Python Python Django SQL" with a profile repeating Python 1,000 times.
- **Expected result:** Identical base similarity.
- **Actual result, evidence and verdict:** Equal to 12 decimal places (1 automated test in test_project.py). Pass.

## TC-012

- **Traceability:** FR-09
- **Scenario, data and conditions:** Stop-word-only, empty and unrelated queries; C++, C#, .NET and a word followed by a full stop.
- **Expected result:** Zero scores without errors; technical tokens matched correctly.
- **Actual result, evidence and verdict:** Scores of 0 without errors; “C++” matched “C++ developer” but scored 0 against “C# developer”; .NET and “Python.” matched. 2 tests in test_project.py passed.

## TC-013

- **Traceability:** FR-07, FR-09
- **Scenario, data and conditions:** Match on a term found only in the portfolio; add an evidence link containing the query term.
- **Expected result:** Portfolio contributes to the score; the link does not change it.
- **Actual result, evidence and verdict:** A term found only in the portfolio gave a base score above 0; adding the link left the score unchanged. 2 tests in test_project.py passed.

## TC-014

- **Traceability:** FR-13, FR-15
- **Scenario, data and conditions:** Incomplete or inactive profiles; closed jobs and jobs of inactive employers; change a seeker's certification level.
- **Expected result:** Excluded items do not appear; recommendation order is unchanged while scores increase.
- **Actual result, evidence and verdict:** Excluded items did not appear; after raising the certification level the order was unchanged and the score higher. 3 tests in test_project.py passed.

## TC-015

- **Traceability:** NFR-07
- **Scenario, data and conditions:** Rank equal-score profiles; rank all 30 synthetic profiles twice for each of the 10 synthetic jobs.
- **Expected result:** Stable order by identifier; identical scores and order on repeated runs.
- **Actual result, evidence and verdict:** Equal scores were ordered by identifier; repeated runs gave identical scores and order (repeated-run script, 21 October 2026). 1 test in test_project.py passed.

## TC-016

- **Traceability:** NFR-03
- **Scenario, data and conditions:** POST to the close-job address without a CSRF token; request logout with GET.
- **Expected result:** HTTP 403 and HTTP 405 respectively.
- **Actual result, evidence and verdict:** HTTP 403 without a token and HTTP 405 for logout by GET. 1 test in test_project.py passed.

## TC-017

- **Traceability:** IR-01, FR-14
- **Scenario, data and conditions:** Store a script tag in a bio and open the profile as an employer; render every role page and paginate results.
- **Expected result:** Script shown as escaped text; all pages return HTTP 200.
- **Actual result, evidence and verdict:** The script tag appeared as escaped text; all role pages returned HTTP 200 and results showed “Why this match?”. 3 tests in test_project.py passed.

## TC-018

- **Traceability:** FR-22, FR-24
- **Scenario, data and conditions:** Ordinary seeker and employer log in without 2FA; choose Not now; start setup without a fresh password; submit a wrong and then a valid code.
- **Expected result:** Reminder shown once and never blocks access; setup needs a fresh password; device enabled only after a valid code.
- **Actual result, evidence and verdict:** The reminder appeared once and never blocked access; setup was refused without a fresh password; the device was enabled only after a valid code (report Figure 5.2). Tests in test_mfa.py and test_mfa_reminder.py passed.

## TC-019

- **Traceability:** FR-02, FR-16, FR-23
- **Scenario, data and conditions:** Administrator without a device signs in; administrator with a device signs in; password POST to /admin/login/; old password-only and promoted-user sessions.
- **Expected result:** Mandatory setup or code entry; no admin access until verified; old sessions signed out.
- **Actual result, evidence and verdict:** Administrators without a device were sent to setup and had no admin access before verification; the password POST to /admin/login/ and old sessions did not give access (report Figure 5.6). Tests in test_mfa.py and test_mfa_reminder.py passed.

## TC-020

- **Traceability:** NFR-12
- **Scenario, data and conditions:** Reuse a successful code; retry immediately after a failure; let a pending challenge expire; change the password or deactivate the user mid-login; submit another user's device identifier; omit the CSRF token.
- **Expected result:** Replay and immediate retry rejected; expired or invalidated challenges do not log in; no cross-account device use; CSRF enforced.
- **Actual result, evidence and verdict:** A reused code, an immediate retry, an expired or invalidated challenge, another user’s device and a missing CSRF token were all rejected. Tests in test_mfa.py passed.

## TC-021

- **Traceability:** NFR-13, DR-09
- **Scenario, data and conditions:** Inspect response headers and cookies on the login page; inspect 2FA page caching; run manage.py check --deploy; inspect the admin registry.
- **Expected result:** X-Frame-Options DENY, nosniff, HttpOnly SameSite=Lax session cookie, no-store and same-origin referrer on 2FA pages; no deployment warnings; devices not editable in admin.
- **Actual result, evidence and verdict:** Headers and cookies as expected; the 2FA pages were not cached; manage.py check --deploy reported no issues; devices were not editable in the admin (header inspection on 21 October 2026; tests in test_mfa.py).

## TC-022

- **Traceability:** FR-17, DR-07
- **Scenario, data and conditions:** Relevance rule at the 70% boundary; Precision@k with fewer than k results; SUS scoring; evaluation with unlabelled or changed data.
- **Expected result:** Correct rule and metric values; evaluation refuses incomplete or out-of-date labels.
- **Actual result, evidence and verdict:** The 70% rule held at the boundary; Precision@5 for two hits was 0.4; the SUS patterns scored 100, 0 and 50; unlabelled or changed data was refused. 4 tests in test_project.py passed.

## TC-023

- **Traceability:** NFR-11
- **Scenario, data and conditions:** Clean installation from locked dependencies through start.cmd (Windows) and tools/dev.py (Linux), followed by the full validation gate.
- **Expected result:** All checks pass on both operating systems.
- **Actual result, evidence and verdict:** Passed in GitHub Actions run 36742471015 for commit 5d2c28e; five startup tests in test_startup.py pass. Pass.

## TC-024

- **Traceability:** NFR-01
- **Scenario, data and conditions:** Synthetic corpus of 31 profiles and 10 jobs; 30 timed requests per page after one warm-up request (Table 5.7).
- **Expected result:** Ranked list returned within 10 seconds.
- **Actual result, evidence and verdict:** Maximum 0.102 seconds. Pass in the test environment.

## TC-025

- **Traceability:** NFR-06
- **Scenario, data and conditions:** Browser checks of landing, seeker and employer workflows at 1440 px and 390 px widths.
- **Expected result:** Pages usable without horizontal overflow, JavaScript errors or server errors.
- **Actual result, evidence and verdict:** Passed in headless Microsoft Edge (18 September 2026) and in headless Chromium 141 on Linux (23 October 2026), covering the seeker and employer workflows at both widths, with no JavaScript or server errors. The Chromium run used the repository’s check script with its login step adjusted for the post-login 2FA reminder and its pagination check adjusted for 31 seeded profiles. The two-factor and role-switch screens, and every page added on or after 29 October 2026, were not part of this run. Google Chrome itself and Mozilla Firefox were not tested in this study, and this is recorded as a limitation in Section 5.5.

## TC-026

- **Traceability:** NFR-05
- **Scenario, data and conditions:** SUS questionnaire after the participant tasks in docs/EVALUATION.md.
- **Expected result:** Mean SUS score of at least 70.
- **Actual result, evidence and verdict:** Not executed within the project period. The questionnaire form, the scoring command (TC-022) and the participant tasks are in place, so NFR-05 remains unverified and no SUS score is reported.

## TC-027

- **Traceability:** Objective v, FR-17
- **Scenario, data and conditions:** Precision@5 and Precision@10 for weighted and unweighted rankings, using manually reviewed labels.
- **Expected result:** Results reported for both methods.
- **Actual result, evidence and verdict:** Partly executed. The command was run once with the rule suggestions accepted as labels, without review by a person: mean Precision@5 was 0.40 and mean Precision@10 was 0.20, for the weighted ranking and the baseline alike (310 pairs, two relevant candidates per job). Human labelling was not carried out, so no accuracy result is claimed for the multipliers and Objective v remains not evaluated.

## TC-028

- **Traceability:** FR-27, NFR-12, DR-09
- **Scenario, data and conditions:** Complete authenticator setup; sign in with a recovery code, an invalid code and a used code; inspect stored values; replace the set with and without the password; let a challenge expire.
- **Expected result:** Ten codes shown once; a valid code works once; invalid or used codes fail with the same message; only digests are stored; replacement needs the password and replaces every old code.
- **Actual result, evidence and verdict:** Ten codes shown once; a valid code worked once, and invalid and used codes failed alike; only digests were stored; replacement needed the password. 29 tests in test_mfa_recovery.py passed.

## TC-029

- **Traceability:** FR-28, FR-03, DR-01
- **Scenario, data and conditions:** Switch an account between hiring and job seeking without and with a company name; use the pages of each role; send the switch as GET and without a CSRF token; attempt the switch with a pending second factor; store an invalid active role.
- **Expected result:** First switch creates the other profile; both profiles and their data are kept; each workspace allows only its own pages; non-POST and token-less switches refused; the switch cannot bypass 2FA; the database rejects invalid values.
- **Actual result, evidence and verdict:** The first switch created the other profile (employer needed a company name; seeker profile started empty); both profiles and their data were kept; GET and token-less switches were refused; 2FA could not be bypassed; an invalid role raised IntegrityError. 11 tests in test_project.py passed.

## TC-030

- **Traceability:** FR-30, FR-02, NFR-04, NFR-12
- **Scenario, data and conditions:** Start Google and GitHub sign-in with GET and without a CSRF token; complete callbacks with simulated provider responses for new and existing users; unverified or missing provider emails; users with 2FA, recovery codes and staff accounts; replayed, cancelled or expired OAuth state; remove the last sign-in method.
- **Expected result:** Sign-in starts only by POST with a token; a new user stays anonymous until onboarding; unverified emails are refused; an identity connected elsewhere is never reassigned; every provider login passes the same 2FA and staff gates; state cannot be replayed; the last sign-in method cannot be removed.
- **Actual result, evidence and verdict:** 65 automated tests in test_sso.py, using simulated provider responses, and 11 in test_environment.py for provider configuration, passed. They show that sign-in starts only by POST with a CSRF token, that a new user stays anonymous until onboarding, that unverified or missing emails are refused, that an identity connected to another account is never reassigned, that every provider login passes the same 2FA and staff checks, that replayed, cancelled or expired OAuth state creates no account, and that the last sign-in method cannot be removed. These tests do not exercise the live Google and GitHub services. Separately, Google and GitHub sign-in were tried by hand on the deployed site in November 2026 and both worked; this check is not repeatable and was not recorded as a test case. Pass.

## TC-031

- **Traceability:** FR-29, FR-03, DR-02
- **Scenario, data and conditions:** Save and unsave jobs as a seeker and candidates as an employer, with and without a CSRF token; request another user's list; save own, closed, incomplete or inactive items; delete a job or a candidate that has been saved; switch role and sign in again; open each dashboard with and without jobs.
- **Expected result:** Saves are private, repeatable without duplicates and limited to the right role; unavailable items are hidden but removable; deletions leave no broken list; saved items survive a role switch; dashboards show real counts and clear empty states; rankings are unchanged.
- **Actual result, evidence and verdict:** Saves were private, not duplicated and limited to the right role; unavailable items were hidden but removable; saved items survived a role switch; rankings were unchanged. 45 tests in test_dashboard.py, test_profile_editor.py, test_saved_jobs.py and test_saved_candidates.py passed.

## TC-032

- **Traceability:** FR-31, FR-14, DR-10
- **Scenario, data and conditions:** Job seeker applies and employer invites; the other party accepts or declines and the sender withdraws; self-application, closed or expired job, inactive account, incomplete profile, duplicate and opposing requests, the request limit; contact details before and after acceptance.
- **Expected result:** One pending connection is created; only the recipient can answer and only the sender can withdraw; invalid cases are refused with a message; contact details appear only after acceptance.
- **Actual result, evidence and verdict:** One pending connection was created; only the recipient answered and only the sender withdrew; invalid cases were refused with a message; contact details appeared only after acceptance. 45 tests in test_connections.py passed.

## TC-033

- **Traceability:** FR-32, DR-10
- **Scenario, data and conditions:** Move an accepted connection through the stages in order; schedule and reschedule an interview with past, invalid and valid times; skipped, backward and stale stage submissions; end consideration; read the history.
- **Expected result:** Stages advance one step at a time; interview times use the Nairobi time zone; invalid moves are refused without change; every change is recorded once.
- **Actual result, evidence and verdict:** Stages advanced one at a time; interview times used Nairobi time; invalid moves changed nothing; each change was recorded once. 15 tests in test_connection_detail.py and 7 in test_connection_history.py passed.

## TC-034

- **Traceability:** FR-33, DR-11
- **Scenario, data and conditions:** Send, edit and unsend messages as each participant and as an outsider; edit after the 15-minute limit; blank, overlong and repeated submissions; unread counts in the notification bell.
- **Expected result:** Only the sender can edit or unsend, within 15 minutes; invalid and repeated submissions change nothing; unread counts follow what has been displayed.
- **Actual result, evidence and verdict:** Only the sender could edit or unsend, within 15 minutes; invalid and repeated submissions changed nothing; unread counts followed what was displayed. 19 tests in test_chat_messages.py and 4 in test_notification_bell.py passed.

## TC-035

- **Traceability:** FR-34, FR-20, DR-05
- **Scenario, data and conditions:** Set, extend and clear a closing date; check the midnight boundary in Nairobi while the UTC date is still the previous day; reopen an expired job; apply, browse and invite after the deadline.
- **Expected result:** Expired jobs leave recommendations, browsing and invitations and refuse new applications; reopening needs a new date or no date; manual closure takes precedence.
- **Actual result, evidence and verdict:** Expired jobs left recommendations, browsing and invitations and refused new applications; reopening needed a new date or none; manual closure took precedence. 21 tests in test_job_deadlines.py passed.

## TC-036

- **Traceability:** FR-35
- **Scenario, data and conditions:** Apply each minimum match option to recommendations, candidates and free-text search with more than ten results, together with a search term and a page number.
- **Expected result:** Results below the chosen displayed percentage are hidden after ranking and before pagination; order, percentages and search context are unchanged; an empty result shows its own message.
- **Actual result, evidence and verdict:** Results below the chosen percentage were hidden after ranking and before pagination; order and percentages were unchanged; an empty result showed its own message. 13 tests in test_match_filters.py passed.

## TC-037

- **Traceability:** FR-36, FR-37, NFR-14
- **Scenario, data and conditions:** Save company fields, focus areas and links with valid and invalid values; open the company page as a seeker and as an employer; upload valid, non-image, SVG, oversized, animated and truncated images, and an image with metadata and appended content.
- **Expected result:** Valid values are saved and shown; invalid ones are refused without change; images are re-encoded under a generated name without metadata; only job seekers open the company page.
- **Actual result, evidence and verdict:** Valid values were saved and invalid ones refused unchanged; images were re-encoded under a generated name without metadata; only job seekers opened the company page. 19 tests in test_company_profile.py, 4 in test_company_detail.py and 8 in test_profile_images.py passed.

## TC-038

- **Traceability:** NFR-15, FR-31 to FR-33
- **Scenario, data and conditions:** Send simultaneous duplicate applications, opposing requests, accept and withdraw, closing and accepting, the last request slot, repeated message keys, and an edit with an unsend.
- **Expected result:** One request and one event are stored; the request limit cannot be overspent; histories stay valid; a removed message body is never restored.
- **Actual result, evidence and verdict:** One request and one event were stored; the request limit was not overspent; histories stayed valid; a removed message body was not restored. 12 tests in test_connection_concurrency.py passed.

## TC-039

- **Traceability:** FR-16, FR-25, NFR-04
- **Scenario, data and conditions:** Open the administration dashboard, reports and search with full and limited staff permissions; open the get started and privacy pages and the profile menu signed in and signed out, and during a pending sign-in.
- **Expected result:** Totals and trends follow the stored data; results respect model permissions and admin pages require 2FA; public pages open without a session and bypass no second factor.
- **Actual result, evidence and verdict:** Totals followed the stored data; admin pages needed 2FA and respected permissions; public pages opened without a session and bypassed no second factor. 16 tests in test_admin_dashboard.py, 4 in test_get_started.py, 4 in test_privacy.py, 9 in test_profile_dropdown.py and 4 in test_workspace_controls.py passed.
