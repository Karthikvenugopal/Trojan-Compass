"""Trusted parser entrypoint. Student bytes are data, never code or filesystem paths."""

import io
import json
import logging
import sys
import zipfile

MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT = 20_000


def extract(content: bytes, kind: str) -> str:
    if kind == "docx":
        from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(e.file_size for e in entries) > 12 * 1024 * 1024:
                raise ValueError()
            xml = archive.read("word/document.xml")
            root = fromstring(xml, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        paragraphs = []
        for paragraph in root.iter(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
        ):
            paragraphs.append("".join(paragraph.itertext()))
        text = "\n".join(paragraphs)
    elif kind == "pdf" and content.startswith(b"%PDF-"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or not 0 < len(reader.pages) <= 20:
            raise ValueError()
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
            if sum(len(c) for c in chunks) > MAX_TEXT:
                raise ValueError()
        text = "\n".join(chunks)
    else:
        raise ValueError()
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError()
    return text


def main() -> None:
    # OS limits complement the parent's wall-clock limit. No temporary documents.
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    logging.disable(logging.CRITICAL)
    try:
        content = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not 0 < len(content) <= MAX_BYTES or len(sys.argv) != 2:
            raise ValueError()
        kind = sys.argv[1]
        text = extract(content, kind)
        sys.stdout.write(
            json.dumps(
                dict(
                    text=text,
                    kind=kind,
                    warnings=[
                        "Review and edit this text before adding it to the conversation.",
                        "Scans and complex layouts may not extract accurately.",
                    ],
                )
            )
        )
    except Exception:
        # No document bytes, exception text or traceback go to either output stream.
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
