#!/usr/bin/env python3
"""Render one HTML fragment per slot from the evidence files.

Writes ``docs/templates-linkml/_evidence/<slot>.html`` (gitignored). The class
page template includes the fragment of each slot, so ``gen-doc`` shows the
evidence without the schema containing it. Run by ``just gen-doc``.
"""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

from linkml_microschemas_envar import slot_evidence as se

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "docs" / "templates-linkml" / "_evidence"
EXTENT_LABEL = {"full": "full coverage", "partial": "partial coverage", "absent": "absent", "out_of_layer": "out of layer"}


def _row(key: str, html: str, css: str = "") -> str:
    return f'<div class="envar-cov-row{" " + css if css else ""}"><span class="k">{key}</span> {html}</div>'


def _badge(status: str, css: str) -> str:
    return f'<span class="envar-cov-status st-{css}">{escape(status)}</span>'


def _status(data: dict) -> tuple[str, str]:
    """Badge text and colour class for an item or non-support entry."""
    status = data.get("status") or "unverified"
    if status == "confirmed":
        by = (data.get("confirmation") or {}).get("by", "")
        return f"confirmed by {by.rsplit('/', 1)[-1]}", "verified"
    return status, "verified" if status == "verified" else "partial"


def _document(item: dict, source: dict) -> str:
    document = source.get("documents", {}).get(item.get("document") or "")
    if not document:
        return ""
    link = f'<a href="{escape(document["url"], quote=True)}">{escape(document["title"])}</a>'
    return _row("where", link + (f", {escape(item['locator'])}" if item.get("locator") else ""), "envar-cov-where")


def _item(item: dict, source: dict) -> str:
    rows = []
    if item.get("snippet"):
        rows.append(_row("quote", f"&ldquo;{escape(item['snippet'])}&rdquo;"))
    if item.get("source_slot"):
        label = f" ({escape(item['source_label'])})" if item.get("source_label") else ""
        rows.append(_row("field", f"<code>{escape(item['source_slot'])}</code>{label}"))
    if item.get("field"):
        value = f" = <code>{escape(str(item['value']))}</code>" if item.get("value") is not None else ""
        rows.append(_row("output", f"<code>{escape(item['field'])}</code>{value}"))
    rows.append(_document(item, source))
    if item.get("explanation"):
        rows.append(f'<div class="envar-cov-note">{escape(item["explanation"])}</div>')
    return "".join(rows)


def _legacy(legacy: dict) -> str:
    rows = []
    if legacy.get("where") and legacy["where"].strip().lower() != "no column":
        rows.append(_row("where", escape(legacy["where"]), "envar-cov-where"))
    if legacy.get("note"):
        rows.append(f'<div class="envar-cov-note">{escape(legacy["note"])}</div>')
    return "".join(rows)


def _block(css: str, name: str, badge: str, detail: str, body: str) -> str:
    head = f'<div class="envar-cov-head"><span class="envar-cov-std">{escape(name)}</span>{badge}<span class="envar-cov-extent">{escape(detail)}</span></div>'
    return f'<div class="envar-cov st-{css}">{head}{body}</div>'


def render_fragment(entry: dict | None, registry: dict[str, dict]) -> str:
    """The evidence block of one slot; ``entry`` is None for a slot nobody has reviewed."""
    if entry is None:
        return '<div class="envar-cov-row"><span class="k">evidence</span> not yet reviewed against any source</div>\n'
    blocks = []
    for supported in entry.get("supported_by") or []:
        source = registry.get(supported["source"], {})
        name = source.get("name", supported["source"])
        if supported.get("legacy"):
            legacy = supported["legacy"]
            detail = f"{EXTENT_LABEL.get(legacy['extent'], legacy['extent'])} (old verdict)"
            blocks.append(_block("partial", name, _badge("unverified, to be reviewed", "partial"), detail, _legacy(legacy)))
        for item in supported.get("support") or []:
            text, css = _status(item)
            detail = item["type"] + (f", {item['match']} match" if item.get("match") else "")
            blocks.append(_block(css, name, _badge(text, css), detail, _item(item, source)))
    for unsupported in entry.get("not_supported_by") or []:
        source = registry.get(unsupported["source"], {})
        name = source.get("name", unsupported["source"])
        if unsupported.get("legacy"):
            legacy = unsupported["legacy"]
            detail = f"{EXTENT_LABEL.get(legacy['extent'], legacy['extent'])} (old verdict)"
            blocks.append(_block("absent", name, _badge("unverified, to be reviewed", "absent"), detail, _legacy(legacy)))
            continue
        text, _ = _status(unsupported)
        body = f'<div class="envar-cov-note">{escape(unsupported.get("explanation") or "")}</div>'
        body += "".join(_row("closest", "") + _item(item, source) for item in unsupported.get("closest") or [])
        detail = f"should record it, does not: {(unsupported.get('reason') or '').replace('_', ' ')}"
        blocks.append(_block("absent", name, _badge(text, "absent"), detail, body))
    none_found = entry.get("no_support_found")
    if none_found:
        searched = ", ".join(registry.get(s, {}).get("name", s) for s in none_found.get("searched") or [])
        note = f" {escape(none_found['note'])}" if none_found.get("note") else ""
        blocks.append(_row("evidence", f"no support found ({escape(none_found.get('date', ''))}; searched {escape(searched)}).{note}"))

    supporting = len(entry.get("supported_by") or [])
    against = len(entry.get("not_supported_by") or [])
    summary = f"Evidence: {supporting} supporting, {against} not supporting"
    return f'<details class="envar-cov-details">\n<summary>{summary}</summary>\n' + "\n".join(blocks) + "\n</details>\n"


def main() -> None:
    registry, evidence = se.load_registry(), se.load_evidence()
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir(parents=True)
    for slot, entry in evidence.items():
        (OUTPUT_DIR / f"{slot}.html").write_text(render_fragment(entry, registry), encoding="utf-8")
    unreviewed = se.load_yaml(se.EVIDENCE_DIR / "unreviewed.yaml") or []
    for slot in unreviewed:
        (OUTPUT_DIR / f"{slot}.html").write_text(render_fragment(None, registry), encoding="utf-8")
    print(f"wrote {len(evidence) + len(unreviewed)} evidence fragments to {OUTPUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
