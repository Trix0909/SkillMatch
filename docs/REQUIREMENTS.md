# Requirements and source decisions

Only these user-selected files informed product scope:

1. `168111 - Concept note.pdf` (one page): original KAZIFORCE professional profile and skills management concept.
2. `KinyuaTrinaWanjiku_168111 (where changes are being made).docx`: SkillMatch working proposal, especially §§1.6–1.7, 2.5, 3.5–3.8.
3. `SkillMatch_Proposal_Defense_Presentation.pptx`: 12-slide SkillMatch proposal defense presentation, especially slides 7–11.

No other nearby project documents were used. Text extracts are private local working material under `docs/source-extracts`, ignored by Git. The originals were not edited.

## Resolving differences

| Issue | Source evidence | Implementation decision |
| --- | --- | --- |
| Name | Concept uses KAZIFORCE; proposal and presentation use SkillMatch | Use SkillMatch. |
| Frontend | Concept uses React; proposal scope and §3.8.4 explicitly specify HTML/CSS/Bootstrap and no separate JavaScript framework; presentation slide 8 agrees | Server-rendered Django templates, Bootstrap 5 and a small vanilla JavaScript skill-tag interaction. |
| Portfolios | Concept broadly describes samples; proposal explicitly excludes files, PDFs and images | Plain-text portfolio and optional HTTP(S) links only. |
| Weighting | Some high-level prose says “portfolio boost”; exact formula and slide 8 specify certification × experience | Portfolio contributes through TF-IDF text. No extra numerical multiplier. |
| Dropdown typo | A conceptual-framework paragraph calls Junior/Mid/Senior/Lead “certification”; scope, tables and delivery specification distinguish the levels | Certification Basic/Intermediate/Advanced/Expert; experience Junior/Mid/Senior/Lead. |
| Verified claims | Slides mention verified skills; limitations explicitly state self-reported levels and no credential verification | No verified badges or claims. Explain self-reporting on profile and score screens. |
| Schedule | Proposal contains conflicting dates and sprint durations | No invented elapsed sprint history, commits or study completion. Functional modules correspond to the three planned increments. |

## Traceability

| Requirement | Source | Implementation |
| --- | --- | --- |
| Role-based registration/login | Proposal §1.6; slides 4, 11 | `Account`, Django auth, registration/login views, role decorator |
| Profiles, bio, portfolio, level dropdowns | Proposal §§1.6, 3.6.2 | `JobSeekerProfile`, `ProfileForm`, profile templates |
| Unique case-insensitive skill tags | Proposal §§1.6, 3.6.1–2 | `Skill`, canonical names and DB constraints, `parse_skills`, skill editor |
| Optional evidence links, no uploads | Proposal §§1.6–1.7, 2.5 | `EvidenceLink`, HTTP(S) validation, linked profile evidence |
| Employer profiles, job posting | Proposal §§3.5–3.7 | `EmployerProfile`, `JobPost`, owner-scoped management |
| Employer-driven query/ranking | Proposal §2.5; slide 8 | Free-text search and per-job candidate ranking |
| Seeker-driven job recommendations | Proposal §2.5; slide 8 | `MatchingAlgorithm.rank_jobs` |
| Cap raw term frequency to 2 | Proposal §§2.3, 2.5, 3.7.1 | CountVectorizer → count clipping → TfidfTransformer |
| Fixed certification and experience multipliers | Proposal §3.7.4; slide 8 | Constants and `apply_multipliers` |
| Matched skills and relevance markers | Proposal §2.5 | Skill highlights, weighted scores, base similarity and factor details |
| Administrator user management | Proposal §3.5.1 | Django admin with active/staff controls |
| Precision@5 and Precision@10 | Proposal §3.2; slide 10 | Offline label export and weighted/baseline evaluation |
| SUS | Proposal §§1.6, 3.2; slide 10 | Response CSV and offline scoring |
| User and technical documentation | Proposal §3.7.3 | Guides in `docs/` |
| UML/design diagrams | Proposal §§3.5–3.6 | Editable Draw.io files in `docs/diagrams/` |

## Small implementation decisions where sources are silent

- Usernames and names use Django’s built-in user model; authentication uses usernames. Emails are private and are not exposed on candidate pages.
- Employer requirements include explicit skill tags and minimum levels so the specified ≥70% relevance criterion can be evaluated reproducibly.
- A matchable profile needs at least one skill, a nonblank bio and a nonblank portfolio. Links are optional. Level dropdowns use specified defaults.
- Job title, description and required skills form the employer text representation; URLs, company text, names and emails do not enter TF-IDF.
- Job posts can be edited, closed, reopened or deleted by their owner. These controls maintain the lifecycle of the requested job posts.
- SkillCategory is available in the database/admin in line with the concept and schema description. No category-based ranking or invented taxonomy affects matching.
- Use scikit-learn’s standard smoothed IDF, L2 normalization, lowercase English tokens and English stop words. Preserve technical tokens such as C++, C#, .NET and Node.js. No synonym expansion or semantic model.
- Fit the vocabulary per query with that candidate/job corpus. This prevents stale vectors after edits; the sources do not specify a persisted vector cache or training dataset.
- Pagination displays ten results per page. Deterministic ID tie-breaking makes results reproducible within a corpus.

Excluded: native apps, external job boards or third-party APIs, file uploads, image handling, CV/PDF processing, automated credential verification, chat, in-platform messaging, payments, applications/shortlists, analytics dashboards, geolocation matching and salary negotiation.
