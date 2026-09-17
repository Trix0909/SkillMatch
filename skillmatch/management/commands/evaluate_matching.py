import csv
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from skillmatch.matching import MatchingAlgorithm
from skillmatch.evaluation import precision_at_k, rule_relevance, pair_fingerprint
from skillmatch.views import profiles, active_jobs


class Command(BaseCommand):
    help = 'Export a manual labelling sheet or evaluate P@5/P@10 using a fully reviewed label CSV.'

    def add_arguments(self, parser):
        parser.add_argument('--export-labels', type=Path)
        parser.add_argument('--labels', type=Path)
        parser.add_argument('--output', type=Path)

    def handle(self, *args, **options):
        candidates = [p for p in profiles() if p.is_complete]
        jobs = list(active_jobs())
        if not candidates or not jobs:
            raise CommandError('Evaluation requires complete candidate profiles and open jobs.')
        if options['export_labels']:
            path = options['export_labels']
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['job_id', 'job_title', 'candidate_id', 'candidate_username', 'fingerprint', 'skill_coverage', 'rule_suggestion', 'relevant', 'reviewer'])
                for job in jobs:
                    for profile in candidates:
                        coverage, suggestion = rule_relevance(profile, job)
                        writer.writerow([job.pk, job.title, profile.pk, profile.user.username, pair_fingerprint(profile, job), round(coverage, 4), int(suggestion), '', ''])
            self.stdout.write(f'Exported {len(jobs) * len(candidates)} pairs. Fill relevant (0 or 1) and reviewer after manual review. Suggestions are not ground truth.')
            return
        if not options['labels']:
            raise CommandError('Use --export-labels PATH first, then --labels PATH with reviewed labels.')
        labels = {}
        fingerprints = {(j.pk, p.pk): pair_fingerprint(p, j) for j in jobs for p in candidates}
        try:
            with options['labels'].open(encoding='utf-8-sig', newline='') as stream:
                for row in csv.DictReader(stream):
                    key = (int(row['job_id']), int(row['candidate_id']))
                    if key in labels or row['relevant'] not in ('0', '1') or not row['reviewer'].strip():
                        raise ValueError('Every pair must be unique, reviewed and labelled 0 or 1.')
                    if row['fingerprint'] != fingerprints.get(key):
                        raise ValueError('Profile or job contents changed since labelling. Export and review a fresh sheet.')
                    labels[key] = int(row['relevant'])
        except (OSError, ValueError, KeyError) as error:
            raise CommandError(str(error))
        expected = {(j.pk, p.pk) for j in jobs for p in candidates}
        if set(labels) != expected:
            raise CommandError('Labels do not match the current evaluation corpus. Export and review a fresh sheet.')
        engine = MatchingAlgorithm()
        rows = []
        for job in jobs:
            matches = engine.rank_candidates(job.matching_text, candidates)
            baseline = sorted(matches, key=lambda m: (-m.base, m.item.pk))
            relevant = {p.pk for p in candidates if labels[(job.pk, p.pk)]}
            rows.append({'job_id': job.pk, 'job': job.title, 'relevant_candidates': len(relevant),
                         'weighted': {f'P@{k}': precision_at_k([m.item.pk for m in matches], relevant, k) for k in (5, 10)},
                         'baseline': {f'P@{k}': precision_at_k([m.item.pk for m in baseline], relevant, k) for k in (5, 10)}})
        report = {'candidate_count': len(candidates), 'job_count': len(jobs),
                  'method': 'Capped TF-IDF cosine baseline versus identical pipeline with level multipliers. Macro-average across jobs. Missing results count as non-relevant; denominator remains k.',
                  'mean': {method: {f'P@{k}': sum(r[method][f'P@{k}'] for r in rows) / len(rows) for k in (5, 10)} for method in ('weighted', 'baseline')},
                  'jobs': rows}
        payload = json.dumps(report, indent=2)
        if options['output']:
            options['output'].parent.mkdir(parents=True, exist_ok=True)
            options['output'].write_text(payload, encoding='utf-8')
        self.stdout.write(payload)
