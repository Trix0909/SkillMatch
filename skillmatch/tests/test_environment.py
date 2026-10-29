"""Local settings loading with isolated files and synthetic, temporary credentials."""

import os
import runpy
import secrets
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_KEYS = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
)


class EnvironmentTests(TestCase):
    @contextmanager
    def isolated_settings(self, file_values=None, shell_values=None, encoding="utf-8"):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "static").mkdir()
            settings_file = root / "config" / "settings.py"
            settings_file.write_text(
                (ROOT / "config" / "settings.py").read_text(encoding="utf-8"), encoding="utf-8"
            )
            if file_values is not None:
                (root / ".env").write_text(
                    "\n".join(f"{key}={value}" for key, value in file_values.items()),
                    encoding=encoding,
                )
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(
                    ("DJANGO_", "GOOGLE_", "GITHUB_", "SKILLMATCH_", "PYTHON_DOTENV")
                )
            }
            environment.update(shell_values or {})
            with patch.dict(os.environ, environment, clear=True):
                yield settings_file

    def credentials(self):
        return {key: secrets.token_hex(16) for key in PROVIDER_KEYS}

    def assert_provider_values(self, values, expected):
        for provider in ("google", "github"):
            app = values["SOCIALACCOUNT_PROVIDERS"][provider]["APPS"][0]
            self.assertEqual(app["client_id"], expected[f"{provider.upper()}_CLIENT_ID"])
            self.assertEqual(app["secret"], expected[f"{provider.upper()}_CLIENT_SECRET"])

    def test_root_dotenv_configures_both_providers(self):
        credentials = self.credentials()
        with self.isolated_settings(credentials) as filename:
            values = runpy.run_path(str(filename))
            self.assert_provider_values(values, credentials)
            self.assertTrue(values["DEBUG"])

    def test_missing_dotenv_leaves_providers_unconfigured(self):
        with self.isolated_settings() as filename:
            values = runpy.run_path(str(filename))
            self.assertTrue(values["DEBUG"])
            for provider in ("google", "github"):
                self.assertEqual(values["SOCIALACCOUNT_PROVIDERS"][provider]["APPS"], [])

    def test_shell_values_override_dotenv_without_overwriting_them(self):
        shell = self.credentials()
        with self.isolated_settings(self.credentials(), shell) as filename:
            values = runpy.run_path(str(filename))
            self.assert_provider_values(values, shell)
            for key, value in shell.items():
                self.assertEqual(os.environ[key], value)

    def test_shell_configuration_works_without_dotenv(self):
        shell = self.credentials()
        with self.isolated_settings(shell_values=shell) as filename:
            self.assert_provider_values(runpy.run_path(str(filename)), shell)

    def test_incomplete_credentials_still_disable_provider(self):
        for key in ("GOOGLE_CLIENT_ID", "GITHUB_CLIENT_SECRET"):
            with (
                self.subTest(key=key),
                self.isolated_settings({key: secrets.token_hex(16)}) as filename,
            ):
                values = runpy.run_path(str(filename))
                for provider in ("google", "github"):
                    self.assertEqual(values["SOCIALACCOUNT_PROVIDERS"][provider]["APPS"], [])

    def test_production_ignores_local_file_and_keeps_hosting_configuration(self):
        local = {**self.credentials(), "DJANGO_DEBUG": "1", "DJANGO_HTTPS": "0"}
        shell = {
            "DJANGO_DEBUG": "0",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
            "GOOGLE_CLIENT_ID": secrets.token_hex(16),
            "GOOGLE_CLIENT_SECRET": secrets.token_hex(16),
        }
        with self.isolated_settings(local, shell) as filename:
            values = runpy.run_path(str(filename))
            self.assertFalse(values["DEBUG"])
            self.assertEqual(values["SECRET_KEY"], shell["DJANGO_SECRET_KEY"])
            self.assertTrue(values["SECURE_SSL_REDIRECT"])
            self.assertEqual(values["SOCIALACCOUNT_PROVIDERS"]["github"]["APPS"], [])
            self.assertEqual(
                values["SOCIALACCOUNT_PROVIDERS"]["google"]["APPS"][0]["secret"],
                shell["GOOGLE_CLIENT_SECRET"],
            )
            self.assertNotIn("GITHUB_CLIENT_SECRET", os.environ)

    def test_production_cannot_take_required_secret_from_dotenv(self):
        local = {"DJANGO_DEBUG": "1", "DJANGO_SECRET_KEY": secrets.token_urlsafe(64)}
        with self.isolated_settings(local, {"DJANGO_DEBUG": "0"}) as filename:
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_path(str(filename))

    def test_windows_utf8_bom_dotenv_is_supported(self):
        credentials = self.credentials()
        with self.isolated_settings(credentials, encoding="utf-8-sig") as filename:
            self.assert_provider_values(runpy.run_path(str(filename)), credentials)

    def test_django_starts_and_login_buttons_follow_dotenv(self):
        script = """
import runpy
import sys
from pathlib import Path
import django
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
values = runpy.run_path(sys.argv[1])
values['TEMPLATES'][0]['DIRS'] = [Path(sys.argv[2]) / 'templates']
settings.configure(**{key: value for key, value in values.items() if key.isupper()})
django.setup()
call_command('check', verbosity=0)
response = Client().get(reverse('login'), HTTP_HOST='127.0.0.1')
html = response.content.decode()
assert response.status_code == 200
for provider, name in [('google', 'Google'), ('github', 'GitHub')]:
    assert f'Continue with {name}' in html
    enabled = f'action="{reverse(provider + "_login")}"' in html
    assert enabled == (sys.argv[3] == 'configured')
assert 'Continue with Microsoft' not in html
assert 'Not configured' not in html
print('Startup and provider buttons passed.')
"""
        for credentials in (None, self.credentials()):
            with self.subTest(configured=credentials is not None):
                with self.isolated_settings(credentials) as filename:
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            script,
                            str(filename),
                            str(ROOT),
                            "configured" if credentials else "missing",
                        ],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        env={**os.environ, "PYTHONUTF8": "1"},
                        timeout=30,
                        check=False,
                    )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Startup and provider buttons passed.", result.stdout)

    def test_dotenv_is_ignored_and_example_remains_trackable(self):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", ".env"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        example = subprocess.run(
            ["git", "check-ignore", "--no-index", ".env.example"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(example.returncode, 1)

    def test_example_has_empty_provider_placeholders_only(self):
        from dotenv import dotenv_values

        values = dotenv_values(ROOT / ".env.example")
        for key in PROVIDER_KEYS:
            self.assertEqual(values[key], "")
        self.assertFalse(any(key.startswith("MICROSOFT_") for key in values))
