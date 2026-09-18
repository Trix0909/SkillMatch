"""Offline research helpers; these never claim to replace manually reviewed ground truth."""

import hashlib
import json

from .matching import CERT_MULTIPLIERS, EXP_MULTIPLIERS
from .models import normalize_skill


def pair_fingerprint(profile, job):
    payload = [
        profile.matching_text,
        profile.certification_level,
        profile.experience_level,
        job.matching_text,
        job.certification_level,
        job.experience_level,
        [s.normalized_name for s in profile.skills.all()],
        job.required_skills,
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def rule_relevance(profile, job):
    required = {normalize_skill(s).casefold() for s in job.required_skills}
    present = {s.normalized_name for s in profile.skills.all()}
    coverage = len(required & present) / len(required) if required else 0
    levels_met = (
        CERT_MULTIPLIERS[profile.certification_level] >= CERT_MULTIPLIERS[job.certification_level]
        and EXP_MULTIPLIERS[profile.experience_level] >= EXP_MULTIPLIERS[job.experience_level]
    )
    return coverage, coverage >= 0.7 and levels_met


def precision_at_k(ranked_ids, relevant_ids, k):
    if not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer.")
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("Ranked candidate IDs must be unique.")
    return sum(pk in relevant_ids for pk in ranked_ids[:k]) / k


def sus_score(responses):
    if len(responses) != 10 or any(type(r) is not int or r not in range(1, 6) for r in responses):
        raise ValueError("SUS requires ten integer responses, each between 1 and 5.")
    return 2.5 * sum(r - 1 if i % 2 == 0 else 5 - r for i, r in enumerate(responses))
