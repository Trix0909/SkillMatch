import csv
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from skillmatch.evaluation import sus_score


class Command(BaseCommand):
    help = 'Score collected SUS responses from a CSV with participant_id and q1 through q10.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=Path)
        parser.add_argument('--output', type=Path)

    def handle(self, *args, **options):
        scores = []
        seen = set()
        try:
            with options['csv_file'].open(encoding='utf-8-sig', newline='') as stream:
                for row in csv.DictReader(stream):
                    participant = row['participant_id'].strip()
                    if not participant or participant in seen:
                        raise ValueError('Participant IDs must be present and unique.')
                    seen.add(participant)
                    scores.append({'participant_id': participant, 'sus_score': sus_score([int(row[f'q{i}']) for i in range(1, 11)])})
            if not scores:
                raise ValueError('No participant responses found. Collect responses before scoring.')
        except (OSError, KeyError, ValueError) as error:
            raise CommandError(str(error))
        report = {'participants': len(scores), 'mean_sus': sum(s['sus_score'] for s in scores) / len(scores), 'scores': scores}
        payload = json.dumps(report, indent=2)
        if options['output']:
            options['output'].parent.mkdir(parents=True, exist_ok=True)
            options['output'].write_text(payload, encoding='utf-8')
        self.stdout.write(payload)
