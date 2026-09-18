"""Prepare and start SkillMatch without PowerShell scripts or environment activation."""

import argparse
import subprocess
import sys

if __package__:
    from . import dev
else:
    import dev

DEPENDENCY_CHECK = """
import importlib.metadata
import sys
from pathlib import Path

def verify(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            verify(path.parent / line[3:].strip())
            continue
        name, expected = line.split("==", 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            sys.exit(1)
        if actual != expected:
            sys.exit(1)

verify(Path(sys.argv[1]))
"""


def environment_ready():
    """Check installed versions with the project interpreter, even after a folder move."""
    try:
        result = subprocess.run(
            [
                str(dev.VENV_PYTHON),
                "-c",
                DEPENDENCY_CHECK,
                str(dev.ROOT / "requirements-dev-lock.txt"),
            ],
            cwd=dev.ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def prepare(force=False):
    if force or not environment_ready():
        print("Preparing the Python environment. First setup needs internet access.", flush=True)
        dev.setup()
    else:
        print("The project environment is ready.", flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--setup-only", action="store_true", help="Install/check dependencies and exit."
    )
    parser.add_argument("--port", type=int, default=8000, help="Local server port (default: 8000).")
    parser.add_argument(
        "--noreload", action="store_true", help="Disable development auto-reloading."
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("SkillMatch requires Python 3.12.")
        prepare(force=args.setup_only)
        if args.setup_only:
            print("Setup complete. Run start.cmd to open the development server.")
            return 0
        dev.run(dev.python(), "manage.py", "migrate", "--noinput")
        dev.run(dev.python(), "manage.py", "check")
        address = f"127.0.0.1:{args.port}"
        print(
            f"\nOpen http://{address} in your browser.\nKeep this window open. Press Ctrl+C to stop.",
            flush=True,
        )
        extra = ["--noreload"] if args.noreload else []
        dev.run(dev.python(), "manage.py", "runserver", address, *extra)
    except KeyboardInterrupt:
        print("\nSkillMatch stopped.")
        return 0
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"\nStartup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
