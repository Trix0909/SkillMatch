"""Proposal §§1.6, 2.5 and 3.7.4: capped TF-IDF × certification × experience."""
from dataclasses import dataclass
import re
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.metrics.pairwise import cosine_similarity
from .models import normalize_skill

CERT_MULTIPLIERS = {'basic': 1.0, 'intermediate': 1.3, 'advanced': 1.6, 'expert': 2.0}
EXP_MULTIPLIERS = {'junior': 1.0, 'mid': 1.2, 'senior': 1.5, 'lead': 1.8}
TERM_FREQUENCY_CAP = 2
# Preserve names such as C++, C#, .NET and Node.js rather than collapsing them into C.
TOKEN_PATTERN = r'(?u)(?:\.[a-zA-Z]\w*|\b\w(?:[\w.+#-]*[\w+#])?)'


@dataclass
class Match:
    item: object
    base: float
    cert: float
    experience: float
    score: float
    matched_skills: list

    @property
    def similarity_percent(self):
        return round(self.base * 100)


class MatchingAlgorithm:
    """Fit a shared vocabulary per query/corpus; use exactly the same pipeline in both directions.

    CountVectorizer + TfidfTransformer permits clipping raw counts BEFORE IDF and L2 normalization.
    Clipping an already-normalized TfidfVectorizer output would not implement the proposal.
    """
    def vectorize(self, texts):
        counter = CountVectorizer(lowercase=True, stop_words='english', token_pattern=TOKEN_PATTERN)
        try:
            counts = counter.fit_transform(texts)
        except ValueError as error:
            if 'empty vocabulary' in str(error):
                return None
            raise
        counts.data = counts.data.clip(max=TERM_FREQUENCY_CAP)
        return TfidfTransformer(norm='l2', smooth_idf=True).fit_transform(counts)

    def compute_similarity(self, query, documents):
        if not documents:
            return []
        matrix = self.vectorize([query, *documents])
        if matrix is None:
            return [0.0] * len(documents)
        return cosine_similarity(matrix[0:1], matrix[1:]).ravel().clip(0, 1).tolist()

    def apply_multipliers(self, base, profile):
        cert = CERT_MULTIPLIERS[profile.certification_level]
        exp = EXP_MULTIPLIERS[profile.experience_level]
        return cert, exp, float(base * cert * exp)

    @staticmethod
    def matched_skills(profile, query):
        query = normalize_skill(query).casefold()
        return [s.name for s in profile.skills.all()
                if re.search(r'(?<!\w)' + re.escape(s.name.casefold()) + r'(?!\w)', query)]

    def rank_candidates(self, query, profiles):
        profiles = [p for p in profiles if p.is_complete and p.user.is_active]
        bases = self.compute_similarity(query, [p.matching_text for p in profiles])
        matches = []
        for profile, base in zip(profiles, bases):
            cert, exp, score = self.apply_multipliers(base, profile)
            matches.append(Match(profile, base, cert, exp, score, self.matched_skills(profile, query)))
        return sorted(matches, key=lambda m: (-m.score, m.item.pk))

    def rank_jobs(self, profile, jobs):
        if not profile.is_complete:
            return []
        jobs = [j for j in jobs if j.is_active and j.employer.user.is_active]
        bases = self.compute_similarity(profile.matching_text, [j.matching_text for j in jobs])
        matches = []
        for job, base in zip(jobs, bases):
            cert, exp, score = self.apply_multipliers(base, profile)
            matches.append(Match(job, base, cert, exp, score, self.matched_skills(profile, job.matching_text)))
        return sorted(matches, key=lambda m: (-m.score, m.item.pk))
