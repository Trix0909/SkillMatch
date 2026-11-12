from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import Client, RequestFactory
from django.urls import reverse

from skillmatch import recruitment as workflow
from skillmatch.match_filters import MIN_MATCH_OPTIONS
from skillmatch.matching import Match
from skillmatch.models import Account, JobPost, JobSeekerProfile, SavedCandidate, SavedJob, Skill
from skillmatch.tests.test_connections import WorkflowCase


class FilterMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.links = []
        self.options = []
        self.current_form = None
        self.select = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current_form = {"attrs": attrs, "fields": []}
            self.forms.append(self.current_form)
        elif tag in {"input", "textarea", "select"} and self.current_form is not None:
            self.current_form["fields"].append(attrs)
        if tag == "select":
            self.select = attrs.get("name")
        elif tag == "option" and self.select == "min_match":
            self.options.append(attrs)
        elif tag == "a":
            self.links.append(attrs.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None
        elif tag == "select":
            self.select = None

    @property
    def filter_form(self):
        return next(
            form
            for form in self.forms
            if any(field.get("name") == "min_match" for field in form["fields"])
        )


class MinimumMatchTests(WorkflowCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.job_items = [cls.job]
        cls.profile_items = [cls.profile]
        for index in range(25):
            cls.job_items.append(
                JobPost.objects.create(
                    employer=cls.company,
                    title=f"Filter role {index}",
                    description="Python",
                    required_skills=["Python"],
                )
            )
            user = User.objects.create_user(
                f"filter_candidate_{index}", first_name=f"Candidate {index}"
            )
            Account.objects.create(user=user, active_role="seeker")
            profile = JobSeekerProfile.objects.create(user=user, bio="Python", portfolio="Project")
            Skill.objects.create(profile=profile, name="Python")
            cls.profile_items.append(profile)

    def scope(self, name):
        if name == "jobs":
            return self.seeker, reverse("recommendations"), "rank_jobs", self.job_items
        if name == "job_candidates":
            return (
                self.employer,
                reverse("job_candidates", args=[self.job.pk]),
                "rank_candidates",
                self.profile_items,
            )
        return self.employer, reverse("candidates"), "rank_candidates", self.profile_items

    def ranked(self, name, bases):
        items = self.scope(name)[3]
        return [
            Match(items[index], base, 1.0, 1.0, 3.0 - index / 100, ["Python"])
            for index, base in enumerate(bases)
        ]

    def fetch(self, name, ranked, params=None):
        user, url, method, _ = self.scope(name)
        self.login(user)
        params = {**({"q": "Python"} if name == "search" else {}), **(params or {})}
        with patch(f"skillmatch.views.MatchingAlgorithm.{method}", return_value=ranked) as rank:
            response = self.client.get(url, params)
        return response, rank

    def test_shared_supported_options_and_normalized_any_includes_zero(self):
        self.assertEqual(
            MIN_MATCH_OPTIONS,
            (
                ("", "Any match"),
                ("30", "30%+"),
                ("50", "50%+"),
                ("70", "70%+"),
                ("80", "80%+"),
                ("90", "90%+"),
            ),
        )
        invalid = [
            None,
            "",
            " ",
            "bad",
            "-1",
            "0",
            "20",
            "100",
            "80.0",
            "080",
            "+80",
            " 80 ",
            "80%",
        ]
        for name in ["jobs", "job_candidates", "search"]:
            ranked = self.ranked(name, [0.8, 0.0])
            for raw in invalid:
                with self.subTest(scope=name, raw=raw):
                    response, rank = self.fetch(
                        name, ranked, {} if raw is None else {"min_match": raw}
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["min_match"], "")
                    self.assertEqual(list(response.context["page_obj"]), ranked)
                    self.assertEqual(response.context["page_obj"].paginator.count, 2)
                    selected = [
                        option["value"]
                        for option in FilterMarkup(response.content.decode()).options
                        if "selected" in option
                    ]
                    self.assertEqual(selected, [""])
                    rank.assert_called_once()

    def test_all_thresholds_are_inclusive_of_display_rounding_in_every_scope(self):
        for name in ["jobs", "job_candidates", "search"]:
            for value, _ in MIN_MATCH_OPTIONS[1:]:
                threshold = int(value) / 100
                ranked = self.ranked(name, [threshold - 0.001, threshold - 0.006, threshold, 0])
                with self.subTest(scope=name, minimum=value):
                    response, _ = self.fetch(name, ranked, {"min_match": value})
                    self.assertEqual(ranked[0].similarity_percent, int(value))
                    self.assertLess(ranked[0].base, threshold)
                    self.assertEqual(list(response.context["page_obj"]), [ranked[0], ranked[2]])
                    self.assertEqual(response.context["min_match"], value)
                    selected = [
                        option["value"]
                        for option in FilterMarkup(response.content.decode()).options
                        if "selected" in option
                    ]
                    self.assertEqual(selected, [value])

    def test_weighted_order_and_existing_tie_order_survive_percentage_filtering(self):
        for name in ["jobs", "job_candidates", "search"]:
            ranked = self.ranked(name, [0.70, 0.799, 0.95, 0.85])
            ranked[0].score = 2.5  # A high weighted score does not pass an 80% similarity filter.
            ranked[1].score, ranked[2].score, ranked[3].score = 2.0, 1.0, 1.0
            response, _ = self.fetch(name, ranked, {"min_match": "80"})
            self.assertEqual(list(response.context["page_obj"]), ranked[1:])

    def test_filter_runs_before_ten_result_pagination_without_changing_ranker_inputs(self):
        for name in ["jobs", "job_candidates", "search"]:
            ranked = self.ranked(name, [0.2] * 5 + [0.85] * 21)
            baseline, original_rank = self.fetch(name, ranked)
            response, filtered_rank = self.fetch(name, ranked, {"min_match": "80", "page": "2"})
            page = response.context["page_obj"]
            self.assertEqual(page.paginator.count, 21)
            self.assertEqual(page.paginator.per_page, 10)
            self.assertEqual(page.paginator.num_pages, 3)
            self.assertEqual(list(page), ranked[15:25])
            self.assertEqual(baseline.context["page_obj"].paginator.count, 26)
            original_rank.assert_called_once()
            filtered_rank.assert_called_once()
            self.assertEqual(original_rank.call_args.args[0], filtered_rank.call_args.args[0])
            self.assertEqual(
                list(original_rank.call_args.args[1].values_list("pk", flat=True)),
                list(filtered_rank.call_args.args[1].values_list("pk", flat=True)),
            )

    def test_navigation_and_apply_clear_keep_encoded_search_and_job_context(self):
        query = "C++ & Django / API?x=1 + café #招聘"
        for name in ["jobs", "job_candidates", "search"]:
            ranked = self.ranked(name, [0.85] * 26)
            response, _ = self.fetch(name, ranked, {"q": query, "min_match": "80", "page": "2"})
            user, url, _, _ = self.scope(name)
            parsed = FilterMarkup(response.content.decode())
            page_links = [href for href in parsed.links if href.startswith("?page=")]
            self.assertEqual(len(page_links), 2)
            for href, target in zip(page_links, ["1", "3"]):
                self.assertEqual(
                    parse_qs(urlsplit(href).query),
                    {"page": [target], "q": [query], "min_match": ["80"]},
                )
            form = parsed.filter_form
            self.assertEqual(form["attrs"]["method"], "get")
            self.assertEqual(form["attrs"]["action"], url)
            self.assertNotIn("page", [field.get("name") for field in form["fields"]])
            clear = response.context["clear_match_url"]
            self.assertEqual(urlsplit(clear).path, url)
            self.assertEqual(parse_qs(urlsplit(clear).query), {"q": [query]})
            self.assertIn(clear, parsed.links)
            if name == "search":
                self.assertEqual(response.context["form"]["q"].value(), query)
            else:
                self.assertIn({"type": "hidden", "name": "q", "value": query}, form["fields"])
            self.login(user)
            method = self.scope(name)[2]
            with patch(f"skillmatch.views.MatchingAlgorithm.{method}", return_value=ranked):
                cleared = self.client.get(clear)
                applied = self.client.get(form["attrs"]["action"], {"q": query, "min_match": "50"})
            self.assertEqual(cleared.context["min_match"], "")
            self.assertEqual(cleared.context["page_obj"].number, 1)
            self.assertEqual(applied.context["page_obj"].number, 1)

    def test_duplicate_incoming_page_parameters_do_not_reappear_in_navigation(self):
        self.login(self.employer)
        ranked = self.ranked("search", [0.9] * 26)
        with patch("skillmatch.views.MatchingAlgorithm.rank_candidates", return_value=ranked):
            response = self.client.get(
                reverse("candidates") + "?q=Python&min_match=80&page=1&page=2"
            )
        links = [
            href
            for href in FilterMarkup(response.content.decode()).links
            if href.startswith("?page=")
        ]
        for href in links:
            self.assertEqual(len(parse_qs(urlsplit(href).query)["page"]), 1)

    def test_filtered_counts_and_best_match_use_the_correct_separate_lists(self):
        ranked = self.ranked("jobs", [0.70, 0.9])
        response, _ = self.fetch("jobs", ranked, {"min_match": "80"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertIs(response.context["best_match"], ranked[0])
        self.assertContains(response, "1 job match at 80%+")
        self.assertContains(response, reverse("job_detail", args=[ranked[0].item.pk]))
        response, _ = self.fetch("jobs", ranked[:1], {"min_match": "90"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertIs(response.context["best_match"], ranked[0])
        self.assertContains(response, "No jobs meet your minimum match of 90%")
        self.assertContains(response, "70%")
        for name in ["job_candidates", "search"]:
            response, _ = self.fetch(name, self.ranked(name, [0.7, 0.9]), {"min_match": "80"})
            self.assertEqual(response.context["page_obj"].paginator.count, 1)
            self.assertContains(response, "at 80%+")

    def test_original_empty_corpus_and_threshold_empty_are_distinct(self):
        for name in ["jobs", "job_candidates", "search"]:
            response, _ = self.fetch(name, [], {"min_match": "80"})
            self.assertFalse(response.context["filter_excludes_all"])
            self.assertNotContains(response, "meet your minimum match")
            self.assertContains(
                response,
                "There are no open jobs yet."
                if name == "jobs"
                else "No complete candidate profiles yet.",
            )
            response, _ = self.fetch(name, self.ranked(name, [0]), {"min_match": "80"})
            self.assertTrue(response.context["filter_excludes_all"])
            self.assertContains(
                response,
                f"No {'jobs' if name == 'jobs' else 'candidates'} meet your minimum match of 80%",
            )
            self.assertContains(response, "Clear filter")

    def test_incomplete_profile_and_unsubmitted_or_invalid_search_keep_their_guidance(self):
        self.profile.bio = ""
        self.profile.save(update_fields=["bio"])
        self.login(self.seeker)
        response = self.client.get(reverse("recommendations"), {"min_match": "80"})
        self.assertContains(response, "Complete my profile")
        self.assertNotContains(response, "meet your minimum match")
        self.assertIsNone(response.context["best_match"])
        self.login(self.employer)
        for query in [None, "", "   ", "x" * 8001]:
            with patch("skillmatch.views.MatchingAlgorithm.rank_candidates") as rank:
                response = self.client.get(
                    reverse("candidates"),
                    {"min_match": "80", **({"q": query} if query is not None else {})},
                )
            rank.assert_not_called()
            self.assertFalse(response.context["searched"])
            self.assertContains(response, "A clear description makes a better starting point.")
            self.assertNotContains(response, "meet your minimum match")
            if query is not None:
                self.assertTrue(response.context["form"].errors)

    def test_shared_pagination_keeps_existing_unfiltered_list_behavior(self):
        request = RequestFactory().get(
            "/jobs/", {"q": "C++ & Django / café", "min_match": "80", "page": "2"}
        )
        html = render_to_string(
            "partials/pagination.html",
            {"request": request, "page_obj": Paginator(range(26), 10).page(2)},
        )
        links = FilterMarkup(html).links
        self.assertEqual(len(links), 2)
        for href, page in zip(links, ["1", "3"]):
            self.assertEqual(
                parse_qs(urlsplit(href).query), {"page": [page], "q": ["C++ & Django / café"]}
            )

    def test_saved_items_and_recruitment_controls_keep_existing_state(self):
        connection, _ = workflow.initiate(self.seeker, self.job.pk)
        SavedJob.objects.create(user=self.seeker, job=self.job)
        SavedCandidate.objects.create(user=self.employer, candidate=self.profile, job=self.job)
        response, _ = self.fetch(
            "job_candidates", self.ranked("job_candidates", [0.9]), {"min_match": "80"}
        )
        self.assertContains(response, "Review application")
        self.assertIn(self.profile.pk, response.context["saved_candidate_ids"])
        workflow.respond(self.employer, connection.pk, "accept")
        response, _ = self.fetch("jobs", self.ranked("jobs", [0.9]), {"min_match": "80"})
        self.assertContains(response, "Open connection")
        self.assertIn(self.job.pk, response.context["saved_job_ids"])
        self.assertContains(response, reverse("connection_detail", args=[connection.pk]))

    def test_employer_home_top_three_remains_unfiltered(self):
        ranked = self.ranked("job_candidates", [0.29, 0.2, 0])
        self.login(self.employer)
        with patch("skillmatch.views.MatchingAlgorithm.rank_candidates", return_value=ranked):
            response = self.client.get(reverse("employer_jobs"), {"min_match": "90"})
        self.assertEqual(response.context["top_matches"], ranked)
        self.assertEqual(response.context["candidate_match_count"], 3)

    def test_existing_role_profile_and_job_ownership_checks_remain(self):
        urls = [
            reverse("recommendations"),
            reverse("candidates"),
            reverse("job_candidates", args=[self.job.pk]),
        ]
        for url in urls:
            self.assertEqual(Client().get(url, {"min_match": "80"}).status_code, 302)
        self.login(self.seeker)
        for url in urls[1:]:
            self.assertEqual(self.client.get(url, {"min_match": "80"}).status_code, 403)
        self.login(self.employer)
        self.assertEqual(self.client.get(urls[0], {"min_match": "80"}).status_code, 403)
        self.login(self.third)
        self.assertEqual(self.client.get(urls[2], {"min_match": "80"}).status_code, 404)
        self.profile.delete()
        self.login(self.seeker)
        self.assertEqual(self.client.get(urls[0], {"min_match": "80"}).status_code, 403)
