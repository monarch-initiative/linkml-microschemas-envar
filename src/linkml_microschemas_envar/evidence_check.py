"""Check evidence items against the public documents they cite (needs network).

For every support or closest item that names a document, fetch the document
from its registered URL and check that the quote, field or output value is
really in it. Passing items get a fingerprint in ``evidence.lock.yaml``; the
offline test only accepts ``status: verified`` on items that have one.

Documents are never committed: most cited sources have no licence that allows
redistribution. Fetched copies go to a gitignored cache for inspection only.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import re
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from linkml_microschemas_envar import slot_evidence as se

CACHE_DIR = Path(".evidence_cache")
LOCK_HEADER = "# Written by `just check-evidence`. Do not edit by hand.\n"


@dataclass
class CheckResult:
    passed: list[se.Item] = field(default_factory=list)
    failed: list[tuple[se.Item, str]] = field(default_factory=list)
    skipped: list[se.Item] = field(default_factory=list)


def fetch(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "envar-evidence-check"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (registry URLs only)
        return response.read()


def document_text(url: str, data: bytes) -> str:
    """Plain text of a fetched document: PDF and HTML are converted, the rest decoded."""
    if data[:5] == b"%PDF-":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    text = data.decode("utf-8", errors="replace")
    if url.lower().endswith((".html", ".htm")) or text.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
        from bs4 import BeautifulSoup

        return BeautifulSoup(text, "html.parser").get_text(" ")
    return text


def _json_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _json_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _json_keys(item)}
    return set()


def output_fields(url: str, text: str) -> set[str] | None:
    """Column names of a CSV/TSV or keys of a JSON output; None for other files."""
    path = url.lower().split("?")[0]
    if path.endswith((".csv", ".tsv")):
        delimiter = "\t" if path.endswith(".tsv") else ","
        return {name.strip() for name in next(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=delimiter), [])}
    if path.endswith(".json"):
        try:
            return _json_keys(json.loads(text))
        except json.JSONDecodeError:
            return None
    return None


@lru_cache(maxsize=1)
def _quote_matcher():
    from linkml_reference_validator.models import ReferenceValidationConfig
    from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator

    return SupportingTextValidator(ReferenceValidationConfig())


def _occurs(name: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def item_problem(item: se.Item, url: str, text: str) -> str | None:
    """Why the document does not back the item, or None when it does."""
    data, kind = item.data, item.data.get("type")
    if kind in ("documentation", "argument"):
        from linkml_reference_validator.models import ReferenceContent

        reference = ReferenceContent(reference_id=str(data.get("document")), content=text)
        match = _quote_matcher().find_text_in_reference(data.get("snippet") or "", reference)
        return None if match.found else f"quote not found: {match.error_message or 'no match in the document'}"
    if kind == "schema":
        name = str(data.get("source_slot") or "").split(".")[-1]
        return None if name and _occurs(name, text) else f"'{name}' does not occur in the document"
    if kind == "output":
        name, fields = str(data.get("field") or ""), output_fields(url, text)
        if not name or (name not in fields if fields is not None else not _occurs(name, text)):
            return f"'{name}' is not a field of the output"
        value = data.get("value")
        if value is not None and str(value) not in text:
            return f"value '{value}' does not occur in the output"
        return None
    return f"unknown type '{kind}'"


def check_documents(
    registry: dict[str, dict] | None = None,
    evidence: dict[str, dict] | None = None,
    cache_dir: Path | None = None,
    lock_path: Path | None = None,
) -> CheckResult:
    """Check every item that names a document, and rewrite the lock file."""
    registry = se.load_registry() if registry is None else registry
    evidence = se.load_evidence() if evidence is None else evidence
    cache_dir = Path(cache_dir or CACHE_DIR)
    lock_path = Path(lock_path or se.EVIDENCE_DIR / "evidence.lock.yaml")
    cache_dir.mkdir(parents=True, exist_ok=True)

    result = CheckResult()
    documents: dict[str, tuple[str, str, str] | str] = {}  # id -> (url, text, sha256) or the fetch error
    lock_documents, lock_items = {}, set()
    for item in se.iter_items(evidence):
        document_id = item.data.get("document")
        if not document_id:
            result.skipped.append(item)
            continue
        document = (registry.get(item.source) or {"documents": {}})["documents"].get(document_id)
        if document is None:
            result.failed.append((item, f"unknown document '{document_id}'"))
            continue
        if document_id not in documents:
            try:
                data = fetch(document["url"])
                (cache_dir / document_id).write_bytes(data)
                documents[document_id] = (document["url"], document_text(document["url"], data), hashlib.sha256(data).hexdigest())
            except Exception as error:  # noqa: BLE001 (any fetch or conversion error fails the item)
                documents[document_id] = f"cannot fetch {document['url']}: {error}"
        fetched = documents[document_id]
        if isinstance(fetched, str):
            result.failed.append((item, fetched))
            continue
        url, text, sha256 = fetched
        lock_documents[document_id] = {"sha256": sha256, "checked": datetime.date.today().isoformat()}
        problem = item_problem(item, url, text)
        if problem:
            result.failed.append((item, problem))
        else:
            result.passed.append(item)
            lock_items.add(se.item_hash(item, sha256))

    lock = {"documents": dict(sorted(lock_documents.items())), "items": sorted(lock_items)}
    lock_path.write_text(LOCK_HEADER + yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    return result
