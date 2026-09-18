"""Read the three explicitly supplied source files without changing the originals."""

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concept", required=True, type=Path, help="Concept note PDF")
    parser.add_argument("--proposal", required=True, type=Path, help="Working proposal DOCX")
    parser.add_argument("--presentation", required=True, type=Path, help="Defense PPTX")
    parser.add_argument("--output", type=Path, default=Path("docs/source-extracts"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pdf = PdfReader(args.concept)
    (args.output / "concept.txt").write_text(
        "\n\n".join(
            f"PAGE {index + 1}\n{page.extract_text()}" for index, page in enumerate(pdf.pages)
        ),
        encoding="utf-8",
    )
    with ZipFile(args.proposal) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = [
            "".join(text.text or "" for text in paragraph.findall(".//w:t", namespaces))
            for paragraph in root.findall(".//w:p", namespaces)
        ]
        (args.output / "proposal.txt").write_text("\n".join(paragraphs), encoding="utf-8")
    with ZipFile(args.presentation) as archive:
        names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.search(r"slide(\d+)", name)[1]),
        )
        namespaces = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        slides = []
        for name in names:
            root = ET.fromstring(archive.read(name))
            slides.append(
                name
                + "\n"
                + "\n".join(text.text or "" for text in root.findall(".//a:t", namespaces))
            )
        (args.output / "presentation.txt").write_text("\n\n".join(slides), encoding="utf-8")
    print("Extracted the three specified source files.")


if __name__ == "__main__":
    main()
