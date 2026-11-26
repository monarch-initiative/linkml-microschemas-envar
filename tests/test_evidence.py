"""Tests for the slot evidence files (specs/2026-11-25-slot-evidence-design.md).

The rule tests build a tiny schema and evidence directory in ``tmp_path``; the
real-data tests at the end run the same checks over the repository's files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from linkml_microschemas_envar import slot_evidence as se

ORCID = "https://orcid.org/0000-0002-1825-0097"
SOURCES = {
    "sources": [
        {
            "id": "alpha",
            "name": "Alpha",
            "kind": "tool",
            "documents": [{"id": "alpha-docs", "title": "Alpha docs", "url": "https://example.org/a"}],
        },
        {
            "id": "beta",
            "name": "Beta",
            "kind": "standard",
            "documents": [{"id": "beta-docs", "title": "Beta docs", "url": "https://example.org/b"}],
        },
    ]
}
SCHEMA = {
    "slots": {
        "a": {"annotations": {"tier": "core"}},
        "b": {"annotations": {"tier": "recommended"}},
        "a_missing_reason": {"annotations": {"tier": "optional"}},
        "untiered": {},
    },
    "classes": {"C": {"attributes": {"x": {"annotations": {"tier": "optional"}}}}},
}
ITEM = {
    "type": "documentation",
    "document": "alpha-docs",
    "snippet": "the tool writes the unit",
    "match": "full",
    "explanation": "States the unit of the value.",
    "status": "unverified",
}


def support(**changes) -> dict:
    item = {**ITEM, **changes}
    return {"supported_by": [{"source": "alpha", "support": [{k: v for k, v in item.items() if v is not None}]}]}


GOOD = {"a": support(), "b": support(), "C.x": support()}


def problems(tmp_path: Path, evidence: dict, unreviewed=(), lock=None, frozen=frozenset()) -> list[str]:
    schema_dir = tmp_path / "schema"
    evidence_dir = tmp_path / "evidence"
    schema_dir.mkdir(exist_ok=True)
    evidence_dir.mkdir(exist_ok=True)
    (schema_dir / "mini.yaml").write_text(yaml.safe_dump(SCHEMA))
    (evidence_dir / "sources.yaml").write_text(yaml.safe_dump(SOURCES))
    (evidence_dir / "mini.evidence.yaml").write_text(yaml.safe_dump(evidence))
    (evidence_dir / "unreviewed.yaml").write_text(yaml.safe_dump(list(unreviewed)))
    (evidence_dir / "evidence.lock.yaml").write_text(yaml.safe_dump(lock or {"documents": {}, "items": []}))
    return se.offline_problems(schema_dir=schema_dir, directory=evidence_dir, frozen_unreviewed=frozen)


def test_valid_evidence_has_no_problems(tmp_path):
    assert problems(tmp_path, GOOD) == []


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ({**GOOD, "nope": support()}, "nope: unknown slot"),
        ({**GOOD, "a": {"supported_by": [{"source": "gamma", "support": [ITEM]}]}}, "unknown source 'gamma'"),
        ({**GOOD, "a": support(document="beta-docs")}, "document 'beta-docs' belongs to source 'beta'"),
        ({**GOOD, "a": support(document="zzz")}, "unknown document 'zzz'"),
        ({**GOOD, "a": support(type="argument")}, "match is not allowed on type argument"),
        ({**GOOD, "a": support(match=None)}, "match is required"),
        ({**GOOD, "a": support(match="partial", explanation=None)}, "explanation is required"),
        ({**GOOD, "a": support(snippet=None)}, "snippet is required"),
        ({**GOOD, "a": support(type="schema")}, "source_slot is required"),
        ({**GOOD, "a": support(type="output")}, "field is required"),
        ({**GOOD, "a": support(status="confirmed")}, "confirmation is required"),
        (
            {**GOOD, "a": support(status="confirmed", confirmation={"by": "Nico", "date": "2026-11-25", "basis": "x"})},
            "orcid",
        ),
        ({**GOOD, "a": support(status="verified", document=None)}, "verified needs a document"),
        ({**GOOD, "a": support(status="verified")}, "no lock entry"),
        ({**GOOD, "a": support(status="proven")}, "proven"),
        ({**GOOD, "a": {**support(), "colour": "red"}}, "colour"),
        ({**GOOD, "a": {"supported_by": [{"source": "alpha"}]}}, "needs support items or a legacy block"),
        (
            {**GOOD, "a": {**support(), "supported_by": support()["supported_by"] * 2}},
            "source 'alpha' appears more than once",
        ),
        (
            {**GOOD, "a": {**support(), "no_support_found": {"by": ORCID, "date": "2026-11-25", "searched": ["alpha"]}}},
            "no_support_found is only allowed without supported_by",
        ),
        (
            {**GOOD, "a": {"no_support_found": {"by": ORCID, "date": "2026-11-25", "searched": ["gamma"]}}},
            "unknown source 'gamma'",
        ),
        ({**GOOD, "a": {"not_supported_by": [{"source": "alpha"}]}}, "reason is required"),
        (
            {**GOOD, "a": {**support(), "not_supported_by": [{"source": "beta", "reason": "implicit", "status": "unverified"}]}},
            "explanation is required",
        ),
        (
            {
                **GOOD,
                "a": {
                    **support(),
                    "not_supported_by": [
                        {"source": "beta", "reason": "implicit", "explanation": "x", "status": "verified"}
                    ],
                },
            },
            "a non-support entry cannot be verified",
        ),
        ({k: v for k, v in GOOD.items() if k != "b"}, "b: no evidence"),
        ({**GOOD, "a": support(type="schema", source_slot="t.srid")}, "snippet is not allowed on type schema"),
        ({**GOOD, "a": support(field="score")}, "field is not allowed on type documentation"),
        ({**GOOD, "a": support(value="1")}, "value is not allowed on type documentation"),
        (
            {**GOOD, "a": {"no_support_found": {"by": ORCID, "date": "2026-11-25", "searched": []}}},
            "searched must name at least one source",
        ),
        (
            {**GOOD, "a": {"no_support_found": {"by": ORCID[:-1] + "8", "date": "2026-11-25", "searched": ["alpha"]}}},
            "not a valid ORCID",
        ),
        (
            {**GOOD, "a": support(status="confirmed", confirmation={"by": "https://orcid.org/0000-0000-0000-0000", "date": "2026-11-25", "basis": "x"})},
            "not a valid ORCID",
        ),
        (
            {**GOOD, "a": support(status="confirmed", confirmation={"by": ORCID, "date": "2026-11-25", "basis": " "})},
            "basis is required",
        ),
        (
            {**GOOD, "a": {"not_supported_by": [{"source": "alpha", "legacy": {"extent": "absent", "status": "asserted"}, "status": "verified"}]}},
            "a non-support entry cannot be verified",
        ),
    ],
)
def test_offline_rules(tmp_path, evidence, expected):
    found = problems(tmp_path, evidence)
    assert any(expected in p for p in found), found


def test_confirmed_item_with_orcid_passes(tmp_path):
    confirmation = {"by": ORCID, "date": "2026-11-25", "basis": "internal database, not public"}
    item = support(status="confirmed", document=None, confirmation=confirmation)
    assert problems(tmp_path, {**GOOD, "a": item}) == []


def test_non_support_entry_with_closest_passes(tmp_path):
    closest = {k: v for k, v in ITEM.items() if k not in ("match", "explanation")}
    entry = {
        "source": "alpha",
        "reason": "different_concept",
        "explanation": "Closest is the resource's own DOI.",
        "closest": [closest],
        "status": "unverified",
    }
    evidence = {**GOOD, "a": {"supported_by": support()["supported_by"][:0], "not_supported_by": [entry]}}
    evidence["a"]["no_support_found"] = {"by": ORCID, "date": "2026-11-25", "searched": ["alpha", "beta"]}
    assert problems(tmp_path, evidence) == []


def test_legacy_entries_count_during_the_migration(tmp_path):
    legacy = {"extent": "absent", "status": "asserted", "where": "no column", "note": "n"}
    evidence = {**GOOD, "a": {"not_supported_by": [{"source": "alpha", "legacy": legacy}]}}
    assert problems(tmp_path, evidence) == []


def test_missing_reason_and_untiered_slots_are_exempt(tmp_path):
    assert not [p for p in problems(tmp_path, GOOD) if "a_missing_reason" in p or "untiered" in p]


def test_unreviewed_list_can_only_shrink(tmp_path):
    without_b = {k: v for k, v in GOOD.items() if k != "b"}
    assert problems(tmp_path, without_b, unreviewed=["b"], frozen=frozenset({"b"})) == []
    assert any("b: listed in unreviewed.yaml but has evidence" in p for p in problems(tmp_path, GOOD, ["b"], frozen=frozenset({"b"})))
    assert any("b: not in the frozen unreviewed list" in p for p in problems(tmp_path, without_b, ["b"]))
    assert any("b: reviewed, remove it from FROZEN_UNREVIEWED" in p for p in problems(tmp_path, GOOD, frozen=frozenset({"b"})))
    assert any("gone: unknown slot" in p for p in problems(tmp_path, GOOD, ["gone"], frozen=frozenset({"gone"})))


def test_verified_item_passes_with_its_lock_entry(tmp_path):
    evidence = {**GOOD, "a": support(status="verified")}
    item = next(i for i in se.iter_items({"a": evidence["a"]}))
    lock = {"documents": {"alpha-docs": {"sha256": "abc"}}, "items": [se.item_hash(item, "abc")]}
    assert problems(tmp_path, evidence, lock=lock) == []
    edited = {**GOOD, "a": support(status="verified", snippet="another quote")}
    assert any("no lock entry" in p for p in problems(tmp_path, edited, lock=lock))


def test_verified_needs_the_document_hash_in_the_lock(tmp_path):
    evidence = {**GOOD, "a": support(status="verified")}
    item = next(se.iter_items({"a": evidence["a"]}))
    lock = {"documents": {}, "items": [se.item_hash(item, "")]}
    assert any("no lock entry" in p for p in problems(tmp_path, evidence, lock=lock))


def _recheck(tmp_path):
    return se.offline_problems(schema_dir=tmp_path / "schema", directory=tmp_path / "evidence", frozen_unreviewed=frozenset())


def test_duplicate_ids_in_the_registry_are_problems(tmp_path):
    problems(tmp_path, GOOD)
    path = tmp_path / "evidence" / "sources.yaml"
    gamma = {"id": "gamma", "name": "G", "kind": "tool", "documents": SOURCES["sources"][0]["documents"]}
    path.write_text(yaml.safe_dump({"sources": [*SOURCES["sources"], gamma]}))
    assert any("document id 'alpha-docs' is used more than once" in p for p in _recheck(tmp_path))
    path.write_text(yaml.safe_dump({"sources": SOURCES["sources"] * 2}))
    assert any("source id 'alpha' is used more than once" in p for p in _recheck(tmp_path))


def test_a_slot_key_used_twice_in_one_file_is_a_problem(tmp_path):
    problems(tmp_path, GOOD)
    path = tmp_path / "evidence" / "mini.evidence.yaml"
    path.write_text(path.read_text() + "a:\n  supported_by: []\n")
    assert any("duplicate key 'a'" in p for p in _recheck(tmp_path))


def test_slot_usage_tiers_count_as_slots(tmp_path):
    (tmp_path / "schema").mkdir()
    usage = {"subject": {"annotations": {"tier": "core"}}, "a": {"required": True}}
    (tmp_path / "schema" / "mini.yaml").write_text(yaml.safe_dump({**SCHEMA, "classes": {"C": {"slot_usage": usage}}}))
    expected = {"a": "core", "b": "recommended", "a_missing_reason": "optional", "untiered": None, "subject": "core"}
    assert se.schema_slots(tmp_path / "schema") == expected


def test_report_counts(tmp_path):
    legacy = {"extent": "full", "status": "asserted", "where": "w", "note": "n"}
    evidence = {**GOOD, "a": {"supported_by": [{"source": "alpha", "legacy": legacy}]}}
    problems(tmp_path, evidence)
    report = se.report(schema_dir=tmp_path / "schema", directory=tmp_path / "evidence")
    assert report["legacy_entries"] == 1
    assert report["items_by_status"] == {"unverified": 2}


# ── The repository's own evidence files ──────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
# covered_by verdicts on main when they were converted (2026-11-25), per source and extent.
CONVERTED = {
    ("amadeus", "absent"): 72, ("amadeus", "full"): 13, ("amadeus", "partial"): 17,
    ("chel", "absent"): 47, ("chel", "full"): 17, ("chel", "partial"): 39,
    ("cher", "absent"): 50, ("cher", "full"): 18, ("cher", "partial"): 35,
    ("codata", "absent"): 1, ("codata", "out_of_layer"): 95, ("codata", "partial"): 6,
    ("degauss", "absent"): 87, ("degauss", "full"): 7, ("degauss", "partial"): 8,
    ("omop_gaia", "absent"): 54, ("omop_gaia", "full"): 23, ("omop_gaia", "partial"): 25,
}  # fmt: skip


def test_repository_evidence_has_no_problems():
    assert se.offline_problems() == []


def test_schema_has_no_covered_by_annotations():
    for path in se.SCHEMA_DIR.glob("*.yaml"):
        assert "covered_by" not in path.read_text(encoding="utf-8"), path.name


def test_no_converted_verdict_was_dropped():
    """Reviewed entries lose their legacy block, so counts may only go down."""
    from collections import Counter

    evidence = se.load_evidence()
    legacy = Counter(
        (entry["source"], entry["legacy"]["extent"])
        for slot in evidence.values()
        for key in ("supported_by", "not_supported_by")
        for entry in slot.get(key) or []
        if entry.get("legacy")
    )
    assert sum(CONVERTED.values()) == 614
    assert set(legacy) <= set(CONVERTED)
    assert all(legacy[key] <= CONVERTED[key] for key in legacy)
    reviewed = {source for source, info in se.load_registry().items() if info.get("reviewed")}
    untouched = {key: count for key, count in CONVERTED.items() if key[0] not in reviewed}
    assert {key: legacy[key] for key in untouched} == untouched


def test_unreviewed_list_is_the_frozen_list_or_smaller():
    unreviewed = set(se.load_yaml(se.EVIDENCE_DIR / "unreviewed.yaml"))
    assert len(se.FROZEN_UNREVIEWED) <= 52  # 51 without a verdict, plus `subject` (tier set through slot_usage)
    assert unreviewed == se.FROZEN_UNREVIEWED


# ── Docs fragments ───────────────────────────────────────────────────


def _fragments():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_evidence_fragments", REPO_ROOT / "scripts" / "gen_evidence_fragments.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fragment_shows_support_non_support_and_legacy():
    registry = {
        "alpha": {"name": "Alpha <tool>", "documents": {"alpha-docs": {"title": "Alpha docs", "url": "https://example.org/a?x=1&y=2"}}},
        "beta": {"name": "Beta", "documents": {}},
    }
    confirmation = {"by": ORCID, "date": "2026-11-25", "basis": "internal"}
    entry = {
        "supported_by": [
            {"source": "alpha", "support": [{**ITEM, "locator": "§2", "snippet": "writes <unit> & more", "match": "partial"}]},
            {"source": "beta", "legacy": {"extent": "full", "status": "asserted", "where": "table x", "note": "old <note>"}},
        ],
        "not_supported_by": [
            {"source": "beta", "reason": "different_concept", "explanation": "Closest is the DOI.", "status": "confirmed", "confirmation": confirmation},
            {"source": "alpha", "legacy": {"extent": "absent", "status": "asserted", "where": "no column", "note": "nothing"}},
        ],
    }
    html = _fragments().render_fragment(entry, registry)
    assert "Evidence: 2 supporting, 2 not supporting" in html
    assert "Alpha &lt;tool&gt;" in html and "writes &lt;unit&gt; &amp; more" in html
    assert 'href="https://example.org/a?x=1&amp;y=2"' in html and "Alpha docs</a>, §2" in html
    assert "documentation, partial match" in html and ">unverified<" in html
    assert "unverified, to be reviewed" in html and "full coverage (old verdict)" in html and "old &lt;note&gt;" in html
    assert "should record it, does not: different concept" in html and "confirmed by 0000-0002-1825-0097" in html
    assert "no column" not in html
    assert "\n\n" not in html  # a blank line would end the HTML block in Markdown


def test_fragment_for_none_found_and_unreviewed_slots():
    module = _fragments()
    none_found = {"no_support_found": {"by": ORCID, "date": "2026-11-25", "searched": ["alpha"], "note": "Nothing states it."}}
    html = module.render_fragment(none_found, {"alpha": {"name": "Alpha", "documents": {}}})
    assert "no support found (2026-11-25; searched Alpha). Nothing states it." in html
    assert "not yet reviewed against any source" in module.render_fragment(None, {})


def test_fragment_text_cannot_be_read_as_jinja():
    import jinja2

    item = {**ITEM, "snippet": "set {{ year }} in the {# URL #} {% template %}"}
    registry = {"alpha": {"name": "A", "documents": {}}}
    html = _fragments().render_fragment({"supported_by": [{"source": "alpha", "support": [item]}]}, registry)
    environment = jinja2.Environment(autoescape=False, keep_trailing_newline=True)  # noqa: S701
    assert environment.from_string(html).render() == html
    assert "{" not in html
