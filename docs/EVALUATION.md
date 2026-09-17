# Evaluation protocol

This project supplies the software needed for the proposal’s controlled study. Automated checks demonstrate implementation behavior; they are not participant testing or proof of improved recruitment outcomes.

## Corpus and ground truth

The defense specifies up to 30 job seekers and 10 job postings. `seed_demo` creates that many fictional records for workflow demonstrations. The records are not consented participants and are not a substitute for the researcher’s prepared study corpus.

Freeze the chosen evaluation database before labelling. Export all candidate/job pairs using `evaluate_matching --export-labels`. Manually examine each candidate against each job and fill the blank `relevant` and `reviewer` columns. The rule suggestion uses the proposal’s criterion: at least 70% of the unique required skills and both certification and experience at or above the required levels. Suggestions must be reviewed; do not present them as independent human labels. Keep the candidate count and job count with the results.

## Precision

Run `evaluate_matching --labels` on the completed sheet. The command validates a complete unique label set for the current corpus. Results contain P@5 and P@10 for every job and a macro-average across jobs.

`P@k = number of relevant candidates in the first k results / k`.

If fewer than k candidates exist, the denominator stays k; the missing slots are non-relevant. Compare the weighted pipeline to the same capped TF-IDF/cosine pipeline without level multipliers. This isolates the multiplier contribution while keeping tokenization, repetition control and corpus fixed. Report per-job results as well as averages; do not assume improvement in advance. This comparison is not a separate flat boolean keyword retrieval baseline.

## SUS

Administer the standard ten-item System Usability Scale to consenting participants after representative tasks. Use the established questionnaire appropriate to the study; the source files specify SUS but do not supply questionnaire wording, so no wording has been invented here. Record anonymized participant IDs and ten integer responses (1–5) in a copy of the CSV template.

Odd-numbered items contribute `response − 1`; even-numbered items contribute `5 − response`. Multiply the sum by 2.5 to obtain 0–100. This score is not a percentage. `score_sus` validates all responses and reports individual scores and their mean. No responses or human scores are prepopulated.

## Suggested participant tasks

| Role | Task to observe |
| --- | --- |
| Job seeker | Register, add/remove skills, set levels and save summary/portfolio |
| Job seeker | Open recommendations and explain one score breakdown |
| Job seeker | Browse jobs and read a full opportunity |
| Employer | Register a company and create a job with required skills/levels |
| Employer | Inspect candidate rankings and evidence links |
| Employer | Search directly by a new description, then edit and close a job |

Record actual completion, errors and feedback. Do not invent completion rates, participant satisfaction, time savings or placement outcomes. The final research interpretation must acknowledge self-reported levels, nonsemantic keyword matching, small sample size and the lack of longitudinal outcomes described in the proposal.
