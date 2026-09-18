"""Opt-in fictional data for exercising the prototype, never research results."""

import secrets

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from skillmatch.models import Account, EmployerProfile, JobPost, JobSeekerProfile, Skill

AREAS = [
    (
        "Python developer",
        ["Python", "Django", "SQL", "Git"],
        "Build and maintain web applications, design databases and deliver reliable software.",
        "Built a Django inventory application with Python, SQL reporting and Git version control.",
    ),
    (
        "Bookkeeper",
        ["Bookkeeping", "Excel", "Accounting", "Reconciliation"],
        "Maintain financial records, reconcile transactions and prepare accounting reports.",
        "Maintained bookkeeping records and monthly reconciliation reports using Excel.",
    ),
    (
        "Graphic designer",
        ["Graphic design", "Illustrator", "Photoshop", "Branding"],
        "Create brand identities and visual materials for small businesses.",
        "Created a branding package with print layouts and illustrations in Illustrator and Photoshop.",
    ),
    (
        "Data analyst",
        ["Python", "SQL", "Excel", "Data analysis"],
        "Analyse business data, prepare reports and communicate useful findings.",
        "Used Python, SQL and Excel for data analysis of inventory and sales records.",
    ),
    (
        "Digital marketer",
        ["Digital marketing", "SEO", "Copywriting", "Content planning"],
        "Plan content, write clear copy and improve search visibility.",
        "Created an SEO and content planning project with copywriting for digital marketing.",
    ),
    (
        "Electrician",
        ["Electrical installation", "Wiring", "Maintenance", "Safety"],
        "Install electrical wiring, maintain equipment and follow safety procedures.",
        "Completed an electrical installation project including wiring, maintenance and safety checks.",
    ),
    (
        "Customer support officer",
        ["Customer service", "Communication", "Problem solving", "Record keeping"],
        "Respond to customer enquiries, solve problems and keep accurate records.",
        "Organised customer service requests, communication records and problem solving documentation.",
    ),
    (
        "Web designer",
        ["HTML", "CSS", "Bootstrap", "Web design"],
        "Build responsive web layouts and accessible interfaces.",
        "Created a responsive web design portfolio using HTML, CSS and Bootstrap.",
    ),
    (
        "Network technician",
        ["Networking", "Troubleshooting", "Linux", "Configuration"],
        "Configure local networks and troubleshoot connectivity problems.",
        "Built a networking lab with Linux configuration and troubleshooting notes.",
    ),
    (
        "Project coordinator",
        ["Project planning", "Scheduling", "Communication", "Documentation"],
        "Coordinate project activities, schedules and team documentation.",
        "Prepared project planning schedules, communication plans and delivery documentation.",
    ),
]
NAMES = [
    ("Amina", "Kamau"),
    ("Brian", "Otieno"),
    ("Faith", "Njeri"),
    ("David", "Mwangi"),
    ("Grace", "Wanjiru"),
    ("James", "Kiptoo"),
    ("Joy", "Achieng"),
    ("Kevin", "Kariuki"),
    ("Mercy", "Mutua"),
    ("Peter", "Omondi"),
]


class Command(BaseCommand):
    help = "Create 30 fictional candidates, 10 jobs and demo accounts. Never changes existing accounts."

    def add_arguments(self, parser):
        parser.add_argument("--credentials-file", default="demo-credentials.txt")

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(username__startswith="demo_").exists():
            raise CommandError(
                "Demo accounts already exist. Existing data was not changed. Credentials remain in demo-credentials.txt."
            )
        path = (settings.BASE_DIR / options["credentials_file"]).resolve()
        if not path.is_relative_to(settings.BASE_DIR):
            raise CommandError("Credentials file must be inside this project.")
        if path.exists():
            raise CommandError("Credentials file already exists; choose a new filename.")
        password = secrets.token_urlsafe(16)
        employer_user = User.objects.create_user(
            "demo_employer",
            password=password,
            first_name="Sam",
            last_name="Njoroge",
            email="employer@example.test",
        )
        Account.objects.create(user=employer_user, role="employer")
        employer = EmployerProfile.objects.create(
            user=employer_user,
            company_name="Nairobi Works · Demo SME",
            description="A fictional Kenyan small business used to demonstrate SkillMatch. All jobs and profiles in this demo are synthetic.",
        )
        for i, (title, skills, description, portfolio) in enumerate(AREAS):
            JobPost.objects.create(
                employer=employer,
                title=title,
                description=description + " Required skills: " + ", ".join(skills) + ".",
                required_skills=skills,
                certification_level="intermediate",
                experience_level="mid",
            )
            for variant in range(3):
                index = i * 3 + variant + 1
                username = "demo_seeker" if index == 1 else f"demo_candidate_{index:02}"
                first, last = NAMES[(i + variant) % len(NAMES)]
                user = User.objects.create_user(
                    username,
                    password=password,
                    first_name=first,
                    last_name=last,
                    email=f"candidate{index}@example.test",
                )
                Account.objects.create(user=user, role="seeker")
                profile = JobSeekerProfile.objects.create(
                    user=user,
                    certification_level=["advanced", "intermediate", "basic"][variant],
                    experience_level=["senior", "mid", "junior"][variant],
                    bio=f"{title.capitalize()} focused on practical work for Kenyan SMEs. {description}"
                    if variant < 2
                    else f"Early-career {title.lower()} developing practical skills.",
                    portfolio=portfolio
                    if variant < 2
                    else f"Completed an introductory practice project using {skills[0]}.",
                )
                for name in skills[: 4 if variant < 2 else 2]:
                    Skill.objects.create(profile=profile, name=name)
        User.objects.create_superuser("demo_admin", "admin@example.test", password)
        with path.open("x", encoding="utf-8") as output:
            output.write(
                "LOCAL SYNTHETIC DEMO ONLY\n\nJob seeker: demo_seeker\nEmployer: demo_employer\nAdministrator: demo_admin\nShared demo password: "
                + password
                + "\n\nSign in: http://127.0.0.1:8000/accounts/login/\nAdministration: http://127.0.0.1:8000/admin/\n\nAll 30 candidate profiles and 10 jobs are fictional. Do not deploy these demo accounts publicly.\n"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created 30 synthetic profiles and 10 jobs. Local credentials saved to {path.name}."
            )
        )
