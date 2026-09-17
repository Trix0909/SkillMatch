# SkillMatch system design

Open `SkillMatch-system-design.drawio` in Draw.io / diagrams.net using **Open Existing Diagram**. It contains seven editable pages:

1. System architecture: presentation, application, matching and SQLite tiers.
2. Database schema: actual Django entities and cardinalities.
3. Use cases: job seeker, employer and administrator actions.
4. Matching activity: preprocessing, capped TF-IDF, cosine and multipliers.
5. Implementation class diagram: model composition and matching methods.
6. Matching sequence: request, query, ranking and response.
7. Interface wireframes: registration, profile, job posting and results.

These diagrams describe the implemented application and the supplied proposal’s workflows. The implementation class diagram uses Django User/profile composition rather than falsely showing runtime subclass inheritance. Wireframes summarize the implemented screens; the live interface provides the final visual design.

Regenerate with `python tools/build_diagrams.py`. The generator validates all node IDs and edge endpoints. No external Figma or Draw.io account is required to edit the file.
