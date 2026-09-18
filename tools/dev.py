"""Portable development tasks. Run with Python 3.12 from any working directory."""

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*arguments, env=None, allowed_codes=(0,)):
    print("\n> " + " ".join(str(value) for value in arguments), flush=True)
    child_env = dict(os.environ if env is None else env, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [str(value) for value in arguments], cwd=ROOT, env=child_env, check=False
    )
    if result.returncode not in allowed_codes:
        result.check_returncode()


def python():
    if not VENV_PYTHON.exists():
        raise RuntimeError("Run 'python tools/dev.py setup' first to create .venv.")
    return VENV_PYTHON


def setup():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use Python 3.12 for the tested development environment.")
    if not VENV_PYTHON.exists():
        run(sys.executable, "-m", "venv", ROOT / ".venv")
    run(python(), "-m", "pip", "install", "-r", "requirements-dev-lock.txt")
    run(python(), "manage.py", "migrate")
    run(python(), "manage.py", "check")
    print("\nSetup complete. Run 'python tools/dev.py run'. Demo seeding is optional.")


def format_code(check=False):
    if check:
        run(python(), "-m", "ruff", "check", ".")
        run(python(), "-m", "ruff", "format", "--check", ".")
    else:
        run(python(), "-m", "ruff", "format", ".")
        run(python(), "-m", "ruff", "check", "--fix", ".")
        run(python(), "-m", "ruff", "format", ".")
    # djLint returns 1 when --reformat changes files. Always verify the result.
    if not check:
        run(python(), "-m", "djlint", "templates", "--reformat", "--quiet", allowed_codes=(0, 1))
    run(python(), "-m", "djlint", "templates", "--check", "--quiet")
    run(python(), "tools/format_assets.py", "--check" if check else "--write")


def check():
    format_code(check=True)
    run(python(), "-m", "pip", "check")
    run(python(), "manage.py", "check")
    run(python(), "manage.py", "makemigrations", "--check", "--dry-run")
    run(python(), "manage.py", "test", "skillmatch.tests", "--verbosity", "1")
    # Inspect production defaults without changing the developer's settings or secrets.
    env = dict(os.environ, DJANGO_DEBUG="0", DJANGO_SECRET_KEY=secrets.token_urlsafe(64))
    run(python(), "manage.py", "check", "--deploy", env=env)
    run(python(), "manage.py", "collectstatic", "--noinput")
    run(python(), "tools/check_repository.py")
    print("\nAll development checks passed.")


def doctor():
    run(
        python(),
        "-c",
        "import sys; print('Python:', sys.version); print('Interpreter:', sys.executable)",
    )
    run(python(), "-m", "pip", "check")
    run("git", "status", "--short")
    run("git", "log", "-3", "--oneline")
    run(python(), "manage.py", "migrate", "--check")
    database = Path(os.environ.get("SKILLMATCH_DB", ROOT / "db.sqlite3")).resolve()
    if database.exists():
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()[0]
            print("SQLite integrity:", result)
            if result != "ok":
                raise RuntimeError("SQLite integrity check failed.")
            counts = {
                name: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for name, table in [
                    ("candidate_profiles", "skillmatch_jobseekerprofile"),
                    ("job_posts", "skillmatch_jobpost"),
                ]
            }
            print("Prepared resources:", json.dumps(counts))
    print("\nEnvironment inspected. No secrets or participant responses were printed.")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["setup", "check", "format", "doctor", "run", "demo"])
    args = parser.parse_args()
    try:
        if args.task == "setup":
            setup()
        elif args.task == "check":
            check()
        elif args.task == "format":
            format_code()
        elif args.task == "doctor":
            doctor()
        elif args.task == "run":
            run(python(), "manage.py", "migrate", "--check")
            run(python(), "manage.py", "runserver", "127.0.0.1:8000")
        elif args.task == "demo":
            run(python(), "manage.py", "seed_demo")
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"\nTask failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
