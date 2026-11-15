"""Bounded in-memory document extraction. No upload spool, files, logs or LLM calls."""

import asyncio
import json
import os
import sys
from typing import Literal

from pydantic import Field

from trojan_compass.contracts import Contract

DocumentKind = Literal["pdf", "docx"]
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_TEXT = 20_000


class DocumentText(Contract):
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_TEXT)
    kind: DocumentKind
    warnings: list[str] = Field(default_factory=list)


class DocumentFailure(Exception):
    """Static boundary error, never parser output or document contents."""


class MemoryDocumentParser:
    """Use a bounded worker with stdin/stdout pipes; kill and await it on cancellation.

    A separate process bounds malicious PDF decompression and synchronous parser work.
    Unlike a thread executor, it cannot outlive a cancelled request holding the upload.
    """

    async def parse(self, content: bytes, kind: DocumentKind) -> DocumentText:
        if not content or len(content) > MAX_DOCUMENT_BYTES:
            raise DocumentFailure()
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            "-m",
            "trojan_compass.document_worker",
            kind,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            # Parsers never receive provider credentials or other server secrets.
            env={
                k: v
                for k, v in os.environ.items()
                if k in ("PATH", "PYTHONPATH", "LANG", "LC_ALL", "SYSTEMROOT")
            },
        )
        try:
            async with asyncio.timeout(12):
                output, _ = await process.communicate(content)
            if process.returncode != 0 or len(output) > 130_000:
                raise DocumentFailure()
            result = DocumentText.model_validate(json.loads(output))
            if result.kind != kind:
                raise DocumentFailure()
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            raise DocumentFailure() from None
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
