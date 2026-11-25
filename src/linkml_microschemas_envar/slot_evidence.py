"""Slot evidence: load the evidence files and check them without network.

Evidence for why each slot exists lives in ``evidence/*.evidence.yaml`` next to
a source registry (``evidence/sources.yaml``); the shape is defined by
``evidence/evidence.schema.yaml``. Design: specs/2026-11-25-slot-evidence-design.md.

``python -m linkml_microschemas_envar.slot_evidence`` prints a report and the
offline problems; ``--online`` also fetches the cited documents and checks the
quotes and fields against them (see ``evidence_check``).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
EVIDENCE_DIR = PACKAGE_DIR / "evidence"
SCHEMA_DIR = PACKAGE_DIR / "schema"
EVIDENCE_SCHEMA = EVIDENCE_DIR / "evidence.schema.yaml"

# Slots that had no covered_by verdict when the evidence files were created.
# unreviewed.yaml may only name slots from this list, so it can only shrink.
FROZEN_UNREVIEWED: frozenset[str] = frozenset({
    "cf_cell_methods", "chain_compatibility_assertions", "clinical_date_assignment_convention",
    "cohort_size_anchored", "concept_mappings", "dcat_distribution_url", "deposit_doi",
    "deposit_license_spdx", "deposit_metadata", "deposit_redistribution_constraints_inherited",
    "deposit_repository", "derived_heat_metric", "equation_inputs", "equation_validity_range",
    "equation_variant", "exposure_model_ensemble_member_count", "extraction_buffer_m", "geometry_kind",
    "heat_wave_min_consecutive_days", "heat_wave_threshold_definition", "heat_wave_threshold_specifier",
    "indoor_outdoor", "input_provenance_id", "input_role", "lag_alignment_specifier",
    "linkage_buffer_aggregation_method", "linkage_buffer_radius_m", "linkage_max_distance_to_station_m",
    "linkage_working_crs", "missing_reason", "missing_value_sentinel", "native_value_column",
    "native_value_offset", "native_value_scale_factor", "percentile_reference_period_end",
    "percentile_reference_period_start", "population_weighting_source", "quality_flag_column",
    "quality_flag_vocabulary", "recommended_citation", "run_duration_seconds", "run_environment",
    "run_log_excerpt", "source_acdd_attributes", "source_citation_bibtex", "source_homogenisation_status",
    "tool_description", "unit_conversion_formula", "units_display", "variable_column", "variable_key",
})

REQUIRED_BY_TYPE = {"schema": "source_slot", "documentation": "snippet", "argument": "snippet", "output": "field"}
HASHED_FIELDS = ("type", "document", "snippet", "source_slot", "field", "value")


@dataclass(frozen=True, eq=False)
class Item:
    """One support item (role ``support``) or closest item (role ``closest``)."""

    slot: str
    source: str
    role: str
    data: dict

    @property
    def label(self) -> str:
        return f"{self.slot}: {self.source} {self.role} item ({self.data.get('type')})"


def _plain(value: Any) -> Any:
    """PyYAML turns ISO dates into date objects; the validator wants strings."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def load_yaml(path: Path) -> Any:
    return _plain(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def evidence_files(directory: Path = EVIDENCE_DIR) -> list[Path]:
    return sorted(Path(directory).glob("*.evidence.yaml"))


def load_registry(path: Path = EVIDENCE_DIR / "sources.yaml") -> dict[str, dict]:
    """Source id -> source, with its documents indexed by id."""
    registry = {}
    for source in (load_yaml(path) or {}).get("sources") or []:
        documents = {doc["id"]: doc for doc in source.get("documents") or []}
        registry[source["id"]] = {**source, "documents": documents}
    return registry


def load_evidence(directory: Path = EVIDENCE_DIR) -> dict[str, dict]:
    """Slot key -> evidence, merged over all files; ``module`` names the file."""
    evidence: dict[str, dict] = {}
    for path in evidence_files(directory):
        for slot, entry in (load_yaml(path) or {}).items():
            if slot in evidence:
                raise ValueError(f"{slot}: in both {evidence[slot]['module']} and {path.name}")
            evidence[slot] = {**(entry or {}), "module": path.name}
    return evidence


def load_lock(path: Path = EVIDENCE_DIR / "evidence.lock.yaml") -> dict:
    lock = (load_yaml(path) if Path(path).exists() else None) or {}
    return {"documents": lock.get("documents") or {}, "items": set(lock.get("items") or [])}


def schema_slots(schema_dir: Path = SCHEMA_DIR) -> dict[str, str | None]:
    """Slot key -> tier, for every slot and class-local attribute in the schema modules."""
    slots: dict[str, str | None] = {}
    for path in sorted(Path(schema_dir).glob("*.yaml")):
        module = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, slot in (module.get("slots") or {}).items():
            slots[name] = ((slot or {}).get("annotations") or {}).get("tier")
        for class_name, cls in (module.get("classes") or {}).items():
            for name, slot in ((cls or {}).get("attributes") or {}).items():
                slots[f"{class_name}.{name}"] = ((slot or {}).get("annotations") or {}).get("tier")
    return slots


def iter_items(evidence: dict[str, dict]) -> Iterator[Item]:
    for slot, entry in evidence.items():
        for supported in entry.get("supported_by") or []:
            for data in supported.get("support") or []:
                yield Item(slot, supported.get("source"), "support", data)
        for unsupported in entry.get("not_supported_by") or []:
            for data in unsupported.get("closest") or []:
                yield Item(slot, unsupported.get("source"), "closest", data)


def item_hash(item: Item, document_sha256: str) -> str:
    """Fingerprint of everything the checker looked at, plus the document version."""
    payload = {
        "slot": item.slot,
        "source": item.source,
        "role": item.role,
        "document_sha256": document_sha256,
        **{name: item.data.get(name) for name in HASHED_FIELDS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@lru_cache(maxsize=1)
def _validator():
    from linkml.validator import Validator
    from linkml.validator.plugins import JsonschemaValidationPlugin

    return Validator(str(EVIDENCE_SCHEMA), validation_plugins=[JsonschemaValidationPlugin(closed=True)])


def _shape_problems(instance: dict, target_class: str, name: str) -> list[str]:
    return [f"{name}: {result.message}" for result in _validator().validate(instance, target_class).results]


def _item_problems(item: Item, registry: dict[str, dict], lock: dict) -> list[str]:
    data, found = item.data, []
    kind = data.get("type")
    required = REQUIRED_BY_TYPE.get(kind)
    if required and not data.get(required):
        found.append(f"{required} is required for type {kind}")
    if item.role == "closest" or kind == "argument":
        if data.get("match"):
            found.append(f"match is not allowed on {'a closest item' if item.role == 'closest' else 'type argument'}")
    elif not data.get("match"):
        found.append(f"match is required for type {kind}")
    if item.role == "support" and not data.get("explanation"):
        found.append("explanation is required" + (" and must say what is missing" if data.get("match") == "partial" else ""))

    document = data.get("document")
    source = registry.get(item.source) or {"documents": {}}
    if document and document not in source["documents"]:
        owner = next((sid for sid, other in registry.items() if document in other["documents"]), None)
        found.append(f"document '{document}' belongs to source '{owner}'" if owner else f"unknown document '{document}'")

    status = data.get("status")
    if status == "confirmed" and not data.get("confirmation"):
        found.append("confirmation is required for status confirmed")
    if status == "verified":
        if not document:
            found.append("verified needs a document")
        else:
            sha = (lock["documents"].get(document) or {}).get("sha256", "")
            if item_hash(item, sha) not in lock["items"]:
                found.append("no lock entry, run `just check-evidence`")
    return [f"{item.label}: {problem}" for problem in found]


def _entry_problems(slot: str, entry: dict, registry: dict[str, dict]) -> list[str]:
    found = []
    seen: Counter[str] = Counter()
    for supported in entry.get("supported_by") or []:
        source = supported.get("source")
        seen[source] += 1
        if source not in registry:
            found.append(f"{slot}: unknown source '{source}'")
        if not supported.get("support") and not supported.get("legacy"):
            found.append(f"{slot}: {source} needs support items or a legacy block")
    for unsupported in entry.get("not_supported_by") or []:
        source = unsupported.get("source")
        seen[source] += 1
        if source not in registry:
            found.append(f"{slot}: unknown source '{source}'")
        if unsupported.get("legacy"):
            continue
        for name in ("reason", "explanation", "status"):
            if not unsupported.get(name):
                found.append(f"{slot}: {source} non-support entry: {name} is required")
        if unsupported.get("status") == "verified":
            found.append(f"{slot}: {source}: a non-support entry cannot be verified, only confirmed or unverified")
        if unsupported.get("status") == "confirmed" and not unsupported.get("confirmation"):
            found.append(f"{slot}: {source} non-support entry: confirmation is required for status confirmed")
    found += [f"{slot}: source '{source}' appears more than once" for source, count in seen.items() if count > 1]

    none_found = entry.get("no_support_found")
    if none_found:
        if entry.get("supported_by"):
            found.append(f"{slot}: no_support_found is only allowed without supported_by")
        found += [f"{slot}: no_support_found: unknown source '{s}'" for s in none_found.get("searched") or [] if s not in registry]
    return found


def _has_evidence(entry: dict | None) -> bool:
    if not entry:
        return False
    legacy_negative = any(unsupported.get("legacy") for unsupported in entry.get("not_supported_by") or [])
    return bool(entry.get("supported_by") or entry.get("no_support_found") or legacy_negative)


def _needs_evidence(slot: str, tier: str | None) -> bool:
    return bool(tier) and not slot.endswith("_missing_reason")


def offline_problems(
    schema_dir: Path = SCHEMA_DIR,
    directory: Path = EVIDENCE_DIR,
    frozen_unreviewed: frozenset[str] | None = None,
) -> list[str]:
    """Everything that is wrong with the evidence files, checked without network."""
    directory = Path(directory)
    frozen = FROZEN_UNREVIEWED if frozen_unreviewed is None else frozen_unreviewed
    found = _shape_problems(load_yaml(directory / "sources.yaml") or {}, "SourceRegistry", "sources.yaml")
    for path in evidence_files(directory):
        found += _shape_problems({"entries": load_yaml(path) or {}}, "EvidenceFile", path.name)
    if found:
        return found

    try:
        evidence = load_evidence(directory)
    except ValueError as error:
        return [str(error)]
    registry, lock, slots = load_registry(directory / "sources.yaml"), load_lock(directory / "evidence.lock.yaml"), schema_slots(schema_dir)
    unreviewed = load_yaml(directory / "unreviewed.yaml") or []

    for slot, entry in evidence.items():
        if slot not in slots:
            found.append(f"{slot}: unknown slot (not in the schema)")
        found += _entry_problems(slot, entry, registry)
    for item in iter_items(evidence):
        found += _item_problems(item, registry, lock)

    for slot in unreviewed:
        if slot not in slots:
            found.append(f"{slot}: unknown slot (listed in unreviewed.yaml)")
        elif slot not in frozen:
            found.append(f"{slot}: not in the frozen unreviewed list, new slots need evidence")
        if slot in evidence:
            found.append(f"{slot}: listed in unreviewed.yaml but has evidence, remove it from the list")
    for slot, tier in slots.items():
        if _needs_evidence(slot, tier) and slot not in unreviewed and not _has_evidence(evidence.get(slot)):
            found.append(f"{slot}: no evidence (needs a supported_by entry or no_support_found)")
    return found


def report(schema_dir: Path = SCHEMA_DIR, directory: Path = EVIDENCE_DIR) -> dict:
    """Numbers that show how far the evidence is from fully verified."""
    evidence = load_evidence(directory)
    entries = [e for entry in evidence.values() for key in ("supported_by", "not_supported_by") for e in entry.get(key) or []]
    return {
        "slots_with_evidence": len(evidence),
        "items_by_status": dict(Counter(item.data.get("status") for item in iter_items(evidence))),
        "legacy_entries": sum(1 for e in entries if e.get("legacy")),
        "no_support_found": sorted(slot for slot, entry in evidence.items() if entry.get("no_support_found")),
        "unreviewed": sorted(load_yaml(Path(directory) / "unreviewed.yaml") or []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--online", action="store_true", help="fetch the cited documents and check quotes and fields")
    args = parser.parse_args(argv)

    summary = report()
    print(f"slots with evidence: {summary['slots_with_evidence']}")
    print(f"items by status: {summary['items_by_status'] or 'none yet'}")
    print(f"legacy entries still to review: {summary['legacy_entries']}")
    print(f"slots with no support found: {len(summary['no_support_found'])}")
    print(f"slots never reviewed: {len(summary['unreviewed'])}")

    failed = False
    if args.online:
        from linkml_microschemas_envar.evidence_check import check_documents

        result = check_documents()
        print(f"checked: {len(result.passed)} passed, {len(result.failed)} failed, {len(result.skipped)} skipped (no document)")
        for item, problem in result.failed:
            print(f"FAILED {item.label}: {problem}")
        failed = bool(result.failed)

    found = offline_problems()
    for problem in found:
        print(f"PROBLEM {problem}")
    return 1 if found or failed else 0


if __name__ == "__main__":
    sys.exit(main())
