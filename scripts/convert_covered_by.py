"""One-off: move the `covered_by` slot annotations into evidence side files.

Every verdict is copied word for word into a `legacy` block
(specs/2026-11-25-slot-evidence-design.md, §8 PR 1), then the annotation is
deleted from the schema module by removing its lines (no YAML rewrite, so the
schema files only lose lines). Deleted from the repository once it has run.
"""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "src" / "linkml_microschemas_envar" / "schema"
EVIDENCE_DIR = ROOT / "src" / "linkml_microschemas_envar" / "evidence"
RENAMED = {"clad": "chel"}
POSITIVE = {"full", "partial"}
FIELDS = ("extent", "status", "where", "evidence", "note")
BLOCK_LINE = "      covered_by:"
HEADER = (
    "# Evidence for the slots of {module}.\n"
    "# Shape: evidence.schema.yaml (EvidenceFile). Design: specs/2026-11-25-slot-evidence-design.md\n"
    "# `legacy` blocks are covered_by verdicts copied word for word; they are unverified until reviewed.\n"
)


class Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, value: str):
    style = ">" if len(value) > 70 else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _represent_str)


def convert(slot: dict) -> dict:
    entry: dict = {}
    for source, verdict in slot["annotations"]["covered_by"]["annotations"].items():
        fields = verdict["annotations"]
        assert set(fields) <= set(FIELDS), fields
        legacy = {name: fields[name] for name in FIELDS if name in fields}
        key = "supported_by" if legacy["extent"] in POSITIVE else "not_supported_by"
        entry.setdefault(key, []).append({"source": RENAMED.get(source, source), "legacy": legacy})
    return {key: entry[key] for key in ("supported_by", "not_supported_by") if key in entry}


def dump(module: str, evidence: dict) -> str:
    body = yaml.dump(evidence, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=88, default_flow_style=False)
    lines, out = body.splitlines(), []
    for line in lines:
        if out and line[:1] not in (" ", "-", ""):
            out.append("")
        out.append(line)
    text = HEADER.format(module=module) + "\n" + "\n".join(out) + "\n"
    assert yaml.safe_load(text) == evidence, f"{module}: evidence changed when dumped"
    return text


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def remove_blocks(text: str) -> tuple[str, int]:
    lines, out, removed, i = text.split("\n"), [], 0, 0
    while i < len(lines):
        if lines[i].rstrip() != BLOCK_LINE:
            out.append(lines[i])
            i += 1
            continue
        removed += 1
        i += 1
        while i < len(lines):
            if lines[i].strip():
                if indent(lines[i]) <= 6:
                    break
            else:
                following = next((line for line in lines[i:] if line.strip()), "")
                if indent(following) <= 6:
                    break
            i += 1
    return "\n".join(out), removed


def main() -> None:
    counts: Counter[tuple[str, str]] = Counter()
    blocks, unreviewed = 0, []
    for path in sorted(SCHEMA_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        module = yaml.safe_load(text)
        expected = copy.deepcopy(module)
        evidence = {}
        for name, slot in (module.get("slots") or {}).items():
            annotations = (slot or {}).get("annotations") or {}
            if "covered_by" in annotations:
                evidence[name] = convert(slot)
                del expected["slots"][name]["annotations"]["covered_by"]
                for key in ("supported_by", "not_supported_by"):
                    for item in evidence[name].get(key, []):
                        counts[(item["source"], item["legacy"]["extent"])] += 1
            elif annotations.get("tier") and not name.endswith("_missing_reason"):
                unreviewed.append(name)
        if not evidence:
            continue
        new_text, removed = remove_blocks(text)
        assert removed == len(evidence), (path.name, removed, len(evidence))
        assert yaml.safe_load(new_text) == expected, f"{path.name}: schema changed beyond covered_by"
        path.write_text(new_text, encoding="utf-8")
        (EVIDENCE_DIR / f"{path.stem}.evidence.yaml").write_text(dump(path.name, evidence), encoding="utf-8")
        blocks += removed

    (EVIDENCE_DIR / "unreviewed.yaml").write_text(
        "# Slots that had no covered_by verdict when the evidence files were created.\n"
        "# Nobody has checked them against any source yet. This list can only shrink\n"
        "# (FROZEN_UNREVIEWED in slot_evidence.py); new slots need evidence.\n"
        + "".join(f"- {name}\n" for name in unreviewed),
        encoding="utf-8",
    )
    print(f"{sum(counts.values())} verdicts on {blocks} slots; {len(unreviewed)} unreviewed slots")
    for (source, extent), count in sorted(counts.items()):
        print(f"  {source:10s} {extent:13s} {count}")
    print("FROZEN_UNREVIEWED =", sorted(unreviewed))


if __name__ == "__main__":
    main()
