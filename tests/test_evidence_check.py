"""Tests for the quote and field check (`just check-evidence`), with local documents."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from linkml_microschemas_envar import slot_evidence as se

pytest.importorskip("linkml_reference_validator")
from linkml_microschemas_envar import evidence_check as ec  # noqa: E402

DOCS = {
    "guide.md": "# Guide\n\nThe geocoder writes the match type to the `precision` column on every row.\n"
    "Values are interpolated from the four nearest cells of the 1 km grid.\n",
    "schema.sql": "CREATE TABLE working.data_source (\n  srid INTEGER,\n  geom_type TEXT\n);\n",
    "out.csv": "id,precision,score\n91204,range,0.818\n",
    "out.json": '{"units": "K", "axis": {"increment": 1.0}}',
}


def run(tmp_path: Path, items: list[dict], role: str = "support"):
    for name, text in DOCS.items():
        (tmp_path / name).write_text(text)
    documents = [{"id": name.replace(".", "-"), "title": name, "url": (tmp_path / name).as_uri()} for name in DOCS]
    documents.append({"id": "gone", "title": "gone", "url": (tmp_path / "missing.md").as_uri()})
    registry = {"alpha": {"id": "alpha", "name": "Alpha", "kind": "tool", "documents": {d["id"]: d for d in documents}}}
    if role == "support":
        evidence = {"a": {"supported_by": [{"source": "alpha", "support": items}]}}
    else:
        evidence = {"a": {"not_supported_by": [{"source": "alpha", "closest": items}]}}
    lock_path = tmp_path / "evidence.lock.yaml"
    result = ec.check_documents(registry=registry, evidence=evidence, cache_dir=tmp_path / "cache", lock_path=lock_path)
    return result, se.load_lock(lock_path), evidence


def quote(snippet: str, document: str = "guide-md") -> dict:
    return {"type": "documentation", "document": document, "snippet": snippet, "match": "full", "status": "verified"}


@pytest.mark.parametrize(
    "item",
    [
        quote("The geocoder writes the match type to the `precision` column"),
        quote("The geocoder writes the match type ... on every row"),
        quote("the geocoder [3.3.0] writes the match type to the precision column"),
        {"type": "argument", "document": "guide-md", "snippet": "interpolated from the four nearest cells"},
        {"type": "schema", "document": "schema-sql", "source_slot": "data_source.srid"},
        {"type": "output", "document": "out-csv", "field": "precision"},
        {"type": "output", "document": "out-csv", "field": "precision", "value": "range"},
        {"type": "output", "document": "out-json", "field": "increment", "value": "1.0"},
    ],
)
def test_items_that_the_documents_support_pass(tmp_path, item):
    result, lock, evidence = run(tmp_path, [item])
    assert not result.failed, result.failed
    assert len(result.passed) == 1
    document = item["document"]
    assert se.item_hash(next(se.iter_items(evidence)), lock["documents"][document]["sha256"]) in lock["items"]


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (quote("The geocoder writes the match quality to the precision column"), "not found"),
        (quote("..."), ""),
        (quote(""), ""),
        (quote("anything at all here", document="gone"), "cannot fetch"),
        ({"type": "schema", "document": "schema-sql", "source_slot": "data_source.epsg"}, "'epsg' does not occur"),
        ({"type": "schema", "document": "schema-sql", "source_slot": "data_source.geom"}, "'geom' does not occur"),
        ({"type": "output", "document": "out-csv", "field": "range"}, "'range' is not a field"),
        ({"type": "output", "document": "out-csv", "field": "precision", "value": "street"}, "value 'street'"),
    ],
)
def test_items_that_the_documents_do_not_support_fail(tmp_path, item, expected):
    result, lock, _ = run(tmp_path, [item])
    assert len(result.failed) == 1 and not result.passed
    assert expected in result.failed[0][1]
    assert not lock["items"]


def test_items_without_a_document_are_skipped(tmp_path):
    result, _, _ = run(tmp_path, [{"type": "output", "field": "precision", "status": "unverified"}])
    assert len(result.skipped) == 1 and not result.passed and not result.failed


def test_closest_items_are_checked_too(tmp_path):
    result, _, _ = run(tmp_path, [quote("four nearest cells of the 1 km grid")], role="closest")
    assert len(result.passed) == 1


def test_pdf_and_html_documents_are_read_as_text(tmp_path):
    html = b"<html><head><title>t</title></head><body><p>Days end at <b>midnight</b> MST.</p></body></html>"
    assert "Days end at midnight MST." in " ".join(ec.document_text("https://example.org/page.html", html).split())
    assert ec.document_text("https://example.org/a.md", "café".encode()) == "café"


def test_a_verified_item_fails_offline_once_its_snippet_is_edited(tmp_path):
    result, lock, evidence = run(tmp_path, [quote("The geocoder writes the match type")])
    item = next(se.iter_items(evidence))
    sha = lock["documents"]["guide-md"]["sha256"]
    assert se.item_hash(item, sha) in lock["items"]
    item.data["snippet"] = "The geocoder writes the match quality"
    assert se.item_hash(item, sha) not in lock["items"]
    assert yaml.safe_load((tmp_path / "evidence.lock.yaml").read_text())["documents"]["guide-md"]["sha256"] == sha
