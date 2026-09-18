"""Regression checks for preparing an existing or newly installed environment."""

import importlib.metadata
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tools import launch


class StartupTests(TestCase):
    def test_ready_environment_does_not_reinstall_dependencies(self):
        with (
            patch.object(launch, "environment_ready", return_value=True),
            patch.object(launch.dev, "setup") as setup,
        ):
            launch.prepare()
        setup.assert_not_called()

    def test_missing_dependencies_trigger_setup(self):
        with (
            patch.object(launch, "environment_ready", return_value=False),
            patch.object(launch.dev, "setup") as setup,
        ):
            launch.prepare()
        setup.assert_called_once_with()

    def test_missing_interpreter_triggers_setup(self):
        with patch.object(launch.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(launch.environment_ready())

    def test_migration_failure_prevents_server_start(self):
        with (
            patch.object(launch.sys, "argv", ["launch.py"]),
            patch.object(launch, "prepare"),
            patch.object(
                launch.dev, "run", side_effect=subprocess.CalledProcessError(1, "migrate")
            ) as run,
        ):
            self.assertEqual(launch.main(), 1)
        self.assertEqual(run.call_count, 1)
        self.assertIn("migrate", run.call_args.args)

    def test_dependency_check_reads_included_lock_and_rejects_missing_package(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / "requirements.txt"
            included = root / "included.txt"
            lock.write_text("-r included.txt\n", encoding="utf-8")
            included.write_text(
                f"Django=={importlib.metadata.version('Django')}\n", encoding="utf-8"
            )
            command = [sys.executable, "-c", launch.DEPENDENCY_CHECK, str(lock)]
            ready = subprocess.run(command, capture_output=True, check=False)
            self.assertEqual(ready.returncode, 0, ready.stderr.decode())
            included.write_text("skillmatch-nonexistent-package==0.0.0\n", encoding="utf-8")
            missing = subprocess.run(command, capture_output=True, check=False)
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(missing.stderr, b"")
