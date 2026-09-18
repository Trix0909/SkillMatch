"""Format first-party CSS, JavaScript and configuration JSON; leave vendor code untouched."""

import argparse
import json
from pathlib import Path

import cssbeautifier
import jsbeautifier

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    paths = [
        *ROOT.glob("static/css/*.css"),
        *ROOT.glob("static/js/*.js"),
        *ROOT.glob("tools/*.cjs"),
        *ROOT.glob(".vscode/*.json"),
    ]
    changed = []
    for path in paths:
        original = path.read_text(encoding="utf-8-sig")
        if path.suffix == ".json":
            formatted = json.dumps(json.loads(original), indent=2, ensure_ascii=False)
        else:
            beautifier = cssbeautifier if path.suffix == ".css" else jsbeautifier
            formatted = beautifier.beautify(original, {"indent_size": 2, "end_with_newline": True})
        formatted = formatted.rstrip() + "\n"
        if formatted != original:
            changed.append(str(path.relative_to(ROOT)))
            if args.write:
                path.write_text(formatted, encoding="utf-8", newline="\n")
    if changed:
        print(("Needs formatting: " if args.check else "Formatted: ") + ", ".join(changed))
    else:
        print("First-party assets are consistently formatted.")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
