import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, Client
from django.urls import reverse
from skillmatch.models import Account, JobSeekerProfile, EmployerProfile, JobPost, Skill
from skillmatch.forms import ProfileForm, parse_skills
from skillmatch.matching import MatchingAlgorithm, CERT_MULTIPLIERS, EXP_MULTIPLIERS
from skillmatch.evaluation import precision_at_k, sus_score, rule_relevance


class ProjectCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer_user = User.objects.create_user('employer', password='Workplace-Test-832!')
        Account.objects.create(user=cls.employer_user, role='employer')
        cls.employer = EmployerProfile.objects.create(user=cls.employer_user, company_name='Test SME')
        cls.other_employer_user = User.objects.create_user('other_employer', password='Workplace-Test-832!')
        Account.objects.create(user=cls.other_employer_user, role='employer')
        cls.other_employer = EmployerProfile.objects.create(user=cls.other_employer_user, company_name='Other SME')
        cls.seeker = User.objects.create_user('seeker', password='Workplace-Test-832!', first_name='Amina', last_name='Kamau')
        Account.objects.create(user=cls.seeker, role='seeker')
        cls.profile = JobSeekerProfile.objects.create(user=cls.seeker, bio='Python Django software developer', portfolio='Built Python Django SQL software', certification_level='advanced', experience_level='senior')
        for name in ['Python', 'Django', 'SQL']:
            Skill.objects.create(profile=cls.profile, name=name)
        cls.second_user = User.objects.create_user('second', first_name='Second')
        Account.objects.create(user=cls.second_user, role='seeker')
        cls.second = JobSeekerProfile.objects.create(user=cls.second_user, bio=cls.profile.bio, portfolio=cls.profile.portfolio)
        for name in ['Python', 'Django', 'SQL']:
            Skill.objects.create(profile=cls.second, name=name)
        cls.job = JobPost.objects.create(employer=cls.employer, title='Python developer', description='Build Django software with SQL', required_skills=['Python', 'Django', 'SQL'], certification_level='intermediate', experience_level='mid')
        cls.unrelated = JobPost.objects.create(employer=cls.employer, title='Carpenter', description='Timber joinery furniture', required_skills=['Woodwork'])

    def profile_data(self):
        return {'first_name': 'Amina', 'last_name': 'Kamau', 'skills_json': json.dumps(['Python', 'Django']),
                'certification_level': 'advanced', 'experience_level': 'senior',
                'bio': 'I develop Django applications', 'portfolio': 'Built an inventory application', 'links': 'https://example.com/project'}

    def test_weighted_formula_and_equal_text_ranking(self):
        results = MatchingAlgorithm().rank_candidates(self.job.matching_text, [self.second, self.profile])
        self.assertEqual(results[0].item, self.profile)
        self.assertAlmostEqual(results[0].base, results[1].base)
        self.assertAlmostEqual(results[0].score, results[0].base * 1.6 * 1.5)

    def test_every_multiplier_combination(self):
        engine = MatchingAlgorithm()
        for cert, cert_weight in CERT_MULTIPLIERS.items():
            for exp, exp_weight in EXP_MULTIPLIERS.items():
                self.profile.certification_level = cert
                self.profile.experience_level = exp
                self.assertAlmostEqual(engine.apply_multipliers(.5, self.profile)[2], .5 * cert_weight * exp_weight)

    def test_term_repetition_is_capped_before_normalization(self):
        engine = MatchingAlgorithm()
        score_a = engine.compute_similarity('Python Django', ['Python Python Django SQL'])[0]
        score_b = engine.compute_similarity('Python Django', [('Python ' * 1000) + 'Django SQL'])[0]
        self.assertAlmostEqual(score_a, score_b, places=12)

    def test_empty_stopword_and_unrelated_queries(self):
        engine = MatchingAlgorithm()
        self.assertEqual(engine.compute_similarity('the and', ['or but']), [0])
        self.assertEqual(engine.compute_similarity('Python', []), [])
        self.assertEqual(engine.compute_similarity('woodwork', ['Python Django']), [0])

    def test_technical_punctuation_is_preserved(self):
        engine = MatchingAlgorithm()
        self.assertGreater(engine.compute_similarity('C++', ['C++ developer'])[0], 0)
        self.assertEqual(engine.compute_similarity('C++', ['C# developer'])[0], 0)
        self.assertGreater(engine.compute_similarity('Python', ['Python.'])[0], 0)
        self.assertGreater(engine.compute_similarity('.NET', ['.NET developer'])[0], 0)

    def test_portfolio_and_bio_contribute(self):
        self.profile.bio = 'Accounting records'
        self.profile.portfolio = 'Timber joinery furniture'
        matches = MatchingAlgorithm().rank_candidates('Timber', [self.profile])
        self.assertGreater(matches[0].base, 0)

    def test_evidence_links_do_not_contribute(self):
        engine = MatchingAlgorithm()
        before = engine.rank_candidates('Python', [self.profile])[0].score
        self.profile.evidence_links.create(url='https://example.com/python/python')
        after = engine.rank_candidates('Python', [self.profile])[0].score
        self.assertEqual(before, after)

    def test_incomplete_and_inactive_profiles_excluded(self):
        self.second.portfolio = ''
        self.profile.user.is_active = False
        self.assertEqual(MatchingAlgorithm().rank_candidates('Python', [self.second, self.profile]), [])

    def test_reverse_matching_excludes_closed_and_inactive_jobs(self):
        self.job.is_active = False
        results = MatchingAlgorithm().rank_jobs(self.profile, [self.job, self.unrelated])
        self.assertEqual([m.item for m in results], [self.unrelated])
        self.unrelated.employer.user.is_active = False
        self.assertEqual(MatchingAlgorithm().rank_jobs(self.profile, [self.unrelated]), [])

    def test_job_recommendations_keep_order_when_profile_multipliers_change(self):
        engine = MatchingAlgorithm()
        before = engine.rank_jobs(self.profile, [self.job, self.unrelated])
        self.profile.certification_level = 'expert'
        after = engine.rank_jobs(self.profile, [self.job, self.unrelated])
        self.assertEqual([m.item.pk for m in before], [m.item.pk for m in after])
        self.assertGreater(after[0].score, before[0].score)

    def test_equal_scores_have_stable_tie_break(self):
        self.profile.certification_level = 'basic'
        self.profile.experience_level = 'junior'
        matches = MatchingAlgorithm().rank_candidates('Python', [self.second, self.profile])
        self.assertEqual([m.item.pk for m in matches], sorted([self.profile.pk, self.second.pk]))

    def test_skills_are_normalized_and_case_insensitive(self):
        self.assertEqual(parse_skills('["  Data   Analysis  "]'), ['Data Analysis'])
        from django.core.exceptions import ValidationError
        for value in ['["Python","python"]', '[" Ｐｙｔｈｏｎ ","Python"]', '{}', '[]', '[1]', '[""]']:
            with self.assertRaises(ValidationError):
                parse_skills(value)

    def test_database_rejects_duplicate_skills(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Skill.objects.create(profile=self.profile, name='  PYTHON ')

    def test_database_rejects_invalid_levels(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobSeekerProfile.objects.filter(pk=self.profile.pk).update(certification_level='invented')

    def test_profile_save_adds_removes_and_persists_evidence(self):
        data = self.profile_data()
        data['skills_json'] = '["Python","HTML"]'
        form = ProfileForm(data, instance=self.profile)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(set(self.profile.skills.values_list('name', flat=True)), {'Python', 'HTML'})
        self.assertEqual(self.profile.evidence_links.get().url, 'https://example.com/project')

    def test_evidence_disallows_unsafe_schemes(self):
        for url in ['javascript:alert(1)', 'file:///etc/passwd', 'ftp://example.com/file']:
            data = self.profile_data()
            data['links'] = url
            form = ProfileForm(data, instance=self.profile)
            self.assertFalse(form.is_valid())
            self.assertIn('links', form.errors)

    def test_registration_creates_selected_role_with_hashed_password(self):
        data = {'username': 'new_person', 'first_name': 'Test', 'last_name': 'Person', 'email': 'test@example.test',
                'role': 'seeker', 'password1': 'New-Account-832#!', 'password2': 'New-Account-832#!'}
        response = self.client.post(reverse('register'), data)
        self.assertRedirects(response, reverse('profile_edit'))
        user = User.objects.get(username='new_person')
        self.assertTrue(user.check_password(data['password1']))
        self.assertEqual(user.account.role, 'seeker')
        self.assertFalse(user.seeker_profile.is_complete)

    def test_employer_registration_requires_company(self):
        response = self.client.post(reverse('register'), {'username': 'new_employer', 'first_name': 'Test', 'last_name': 'Employer', 'email': 'test@example.test', 'role': 'employer', 'password1': 'New-Account-832#!', 'password2': 'New-Account-832#!'})
        self.assertContains(response, 'Enter your company name.')
        self.assertFalse(User.objects.filter(username='new_employer').exists())

    def test_registration_cannot_escalate_role(self):
        response = self.client.post(reverse('register'), {'username': 'intruder', 'role': 'admin', 'is_staff': True, 'is_superuser': True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='intruder').exists())

    def test_anonymous_protected_routes_redirect_to_login(self):
        for name in ['profile_edit', 'recommendations', 'jobs', 'employer_jobs', 'candidates']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)

    def test_seeker_cannot_use_employer_tools_or_read_other_candidates(self):
        self.client.force_login(self.seeker)
        for name in ['employer_jobs', 'candidates', 'job_create']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertEqual(self.client.get(reverse('profile_detail', args=[self.second.pk])).status_code, 403)

    def test_employer_cannot_edit_close_delete_or_rank_another_employers_job(self):
        self.client.force_login(self.other_employer_user)
        for name in ['job_edit', 'job_candidates', 'job_delete']:
            self.assertEqual(self.client.get(reverse(name, args=[self.job.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse(name, args=[self.job.pk]), {}).status_code, 404)
        self.assertEqual(self.client.post(reverse('job_toggle', args=[self.job.pk])).status_code, 404)
        self.assertTrue(JobPost.objects.filter(pk=self.job.pk, is_active=True).exists())

    def test_employer_can_view_complete_candidate_profile(self):
        self.client.force_login(self.employer_user)
        self.assertContains(self.client.get(reverse('profile_detail', args=[self.profile.pk])), 'Amina Kamau')

    def test_html_profile_content_is_escaped(self):
        self.client.force_login(self.employer_user)
        self.profile.bio = '<script>alert(1)</script>'
        self.profile.save()
        response = self.client.get(reverse('profile_detail', args=[self.profile.pk]))
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_job_creation_ignores_forged_ownership(self):
        self.client.force_login(self.employer_user)
        response = self.client.post(reverse('job_create'), {'title': 'A new job', 'description': 'Python work', 'skills_json': '["Python"]', 'certification_level': 'basic', 'experience_level': 'junior', 'employer': self.other_employer.pk})
        job = JobPost.objects.get(title='A new job')
        self.assertEqual(job.employer_id, self.employer.pk)
        self.assertRedirects(response, reverse('job_candidates', args=[job.pk]))

    def test_invalid_job_skill_payload_returns_form_errors(self):
        self.client.force_login(self.employer_user)
        for payload in ['[]', '{}', '["Python", "python"]']:
            response = self.client.post(reverse('job_create'), {'title': 'Invalid skill job', 'description': 'Python work', 'skills_json': payload, 'certification_level': 'basic', 'experience_level': 'junior'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('skills_json', response.context['form'].errors)
        self.assertFalse(JobPost.objects.filter(title='Invalid skill job').exists())

    def test_job_lifecycle(self):
        self.client.force_login(self.employer_user)
        self.assertEqual(self.client.get(reverse('job_toggle', args=[self.job.pk])).status_code, 405)
        self.client.post(reverse('job_toggle', args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_active)
        self.client.force_login(self.seeker)
        self.assertNotContains(self.client.get(reverse('jobs')), self.job.title)
        self.assertEqual(self.client.get(reverse('job_detail', args=[self.job.pk])).status_code, 403)
        self.client.force_login(self.employer_user)
        self.client.get(reverse('job_delete', args=[self.job.pk]))
        self.assertTrue(JobPost.objects.filter(pk=self.job.pk).exists())
        self.client.post(reverse('job_delete', args=[self.job.pk]))
        self.assertFalse(JobPost.objects.filter(pk=self.job.pk).exists())

    def test_post_requires_csrf_and_logout_is_post_only(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employer_user)
        self.assertEqual(client.post(reverse('job_toggle', args=[self.job.pk])).status_code, 403)
        self.assertEqual(client.get(reverse('logout')).status_code, 405)

    def test_login_rejects_external_redirect(self):
        response = self.client.post(reverse('login'), {'username': 'seeker', 'password': 'Workplace-Test-832!', 'next': 'https://example.com/evil'})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_invalid_search_does_not_run_matching(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse('candidates'), {'q': 'a' * 8001})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['searched'])

    def test_all_role_pages_render_and_results_paginate(self):
        for user, routes in [(self.seeker, ['profile_edit', 'recommendations', 'jobs', 'methodology']), (self.employer_user, ['profile_edit', 'employer_jobs', 'candidates', 'job_create'])]:
            self.client.force_login(user)
            for name in routes:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        response = self.client.get(reverse('candidates'), {'q': 'Python', 'page': 'invalid'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Why this match?')
        self.client.logout()
        for name in ['landing', 'login', 'register', 'methodology']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_evaluation_relevance_threshold_and_levels(self):
        self.assertTrue(rule_relevance(self.profile, self.job)[1])
        self.assertFalse(rule_relevance(self.second, self.job)[1])
        self.job.required_skills = ['Python', 'Django', 'SQL', 'Git', 'Linux']
        self.assertFalse(rule_relevance(self.profile, self.job)[1])

    def test_precision_denominator_and_sus(self):
        self.assertEqual(precision_at_k([1, 2], {1, 2}, 5), .4)
        self.assertEqual(sus_score([5, 1] * 5), 100)
        self.assertEqual(sus_score([1, 5] * 5), 0)
        self.assertEqual(sus_score([3] * 10), 50)
        with self.assertRaises(ValueError): sus_score([6] * 10)
        with self.assertRaises(ValueError): sus_score([1] * 9)
        with self.assertRaises(ValueError): precision_at_k([1, 1], {1}, 5)

    def test_offline_evaluation_requires_manual_labels(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'labels.csv'
            call_command('evaluate_matching', export_labels=path, stdout=StringIO())
            with self.assertRaises(CommandError): call_command('evaluate_matching', labels=path, stdout=StringIO())
            with path.open(newline='', encoding='utf-8') as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                rows = list(reader)
            # Test-only labels; these are deliberately NOT a research study.
            for row in rows:
                row['relevant'] = row['rule_suggestion']
                row['reviewer'] = 'automated unit-test fixture'
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader(); writer.writerows(rows)
            output = StringIO()
            call_command('evaluate_matching', labels=path, stdout=output)
            self.assertIn('P@5', output.getvalue())
            self.assertIn('baseline', output.getvalue())
            self.profile.bio = 'Changed after manual review'
            self.profile.save()
            with self.assertRaises(CommandError):
                call_command('evaluate_matching', labels=path, stdout=StringIO())

    def test_sus_csv_rejects_empty_and_duplicate_participants(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'sus.csv'
            header = 'participant_id,' + ','.join(f'q{i}' for i in range(1, 11)) + '\n'
            path.write_text(header, encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('score_sus', path, stdout=StringIO())
            row = 'test,' + ','.join(['5', '1'] * 5) + '\n'
            path.write_text(header + row, encoding='utf-8')
            output = StringIO()
            call_command('score_sus', path, stdout=output)
            self.assertEqual(json.loads(output.getvalue())['mean_sus'], 100)
            path.write_text(header + row * 2, encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('score_sus', path, stdout=StringIO())
