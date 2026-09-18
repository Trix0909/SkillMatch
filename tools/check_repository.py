"""Check the Git index for private/generated resources and known local secrets."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    private_dirs = {".venv", "node_modules", "__pycache__", "tmp", "staticfiles", ".ruff_cache"}
    failures = []
    secrets = []
    secret_file = ROOT / ".secret-key"
    if secret_file.exists():
        secrets.append(secret_file.read_bytes().strip())
    credentials = ROOT / "demo-credentials.txt"
    if credentials.exists():
        for line in credentials.read_text(encoding="utf-8").splitlines():
            if line.startswith("Shared demo password: "):
                secrets.append(line.split(": ", 1)[1].encode())
    for name in filter(None, tracked):
        path = Path(name)
        forbidden = (
            bool(private_dirs.intersection(path.parts))
            or path.suffix in {".sqlite3", ".db", ".pyc"}
            or path.name.startswith("demo-credentials")
            or path.name == ".secret-key"
            or (path.name.startswith(".env") and path.name != ".env.example")
            or name.startswith("docs/source-extracts/")
            or (
                name.startswith("evaluation/")
                and path.suffix in {".csv", ".json"}
                and not path.name.endswith("_template.csv")
            )
        )
        if forbidden:
            failures.append(name)
            continue
        # Inspect the staged/committed blob, not only the working copy.
        blob = subprocess.check_output(["git", "show", f":{name}"], cwd=ROOT)
        if any(secret and secret in blob for secret in secrets):
            failures.append(name + " (contains a local secret)")
    if failures:
        print("Remove these private/generated items from the Git index:\n" + "\n".join(failures))
        return 1
    print("Git index contains no prohibited resources or known local secret values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
