# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status — VERY EARLY PROTOTYPE

Everything here is exploratory and will change. Do not treat schemas, examples, or design decisions as stable, normative, or production-ready. Worked examples may be partial; cross-references between modules may not yet be fully consistent.

## Tooling

- Python is managed with `uv`. ALL Python entry-points run inside `uv run` — never invoke `linkml`, `gen-project`, `pytest`, etc. directly from the host environment.
- The command runner is [`just`](https://github.com/casey/just/); project variables (`LINKML_SCHEMA_NAME=linkml_microschemas_envar`, `LINKML_SCHEMA_SOURCE_DIR=src/linkml_microschemas_envar/schema`) load from `config.public.mk`.
- Project-specific recipes go in `project.justfile`. It cannot override recipes defined in the root `justfile` (`just` bug #2540) — an override must be edited into the root file directly.

## Commands

- `just install` — install dev dependencies.
- `just gen-project` — regenerate all artifacts under `project/`. This is what surfaces schema errors.
- `just gen-doc` — regenerate Markdown docs into `docs/elements/`.
- `just site` — `gen-project` + `gen-doc` + `render-schema-overview` + `gen-datasets-ledger` + `standards-index` (all generated pages).
- `just check FILE...` — run the completeness checker (`linkml_microschemas_envar.checker`) over sidecar YAML(s).
- `just lint` — `linkml-lint` over the schema sources.
- `just check-evidence` — fetch the documents cited in the evidence files, check quotes and fields, update `evidence.lock.yaml` (needs network; CI runs the offline checks only).
- `just test` — full suite: schema gen, pytest, and `linkml-run-examples` over `tests/data/valid` (the passing `core`/`recommended`/`ideal` gradient) and `tests/data/invalid` (`core_missing` counter-examples that MUST fail validation).
- `just testdoc` — generate docs and serve locally via `mkdocs serve`.
- `just clean` — remove generated artifacts.
- Single Python test: `uv run pytest tests/path/to/test_file.py::test_name`.

**ALWAYS run `just test` after any change to the schema and/or datasets, and confirm it exits 0 before considering the work done.** It is exactly what CI runs; a single-test run or partial `gen-project` is not sufficient — the suite also cross-checks the datasets ledger, the tier/required invariants, and the standards index.

Gotcha: `tests/test_standards_index.py::test_every_todo_candidate_has_a_verdict` reads the repo-root `todo.md` (gitignored, local-only survey scratch list) and asserts every candidate has a verdict in `docs/standards-index/standards.yaml`; it skips when `todo.md` is absent, so **CI will never catch a missing verdict — only a local `just test` will**.

## Architecture

The substantive content is the LinkML schema set under `src/linkml_microschemas_envar/schema/`; everything else is scaffolding from the `linkml-project-copier` template. `linkml_microschemas_envar.yaml` is an umbrella importing fourteen sibling `envar_*.yaml` modules, one concern each (variable identity, data layout, spatial, temporal, source dataset, exposure model, uncertainty, linkage, tool run/provenance, heat metrics, health-layer/deposit, record composite, example record subclasses). Non-obvious placements: `envar_common.yaml` holds the shared enums/slots and imports the LinkML Microschema Profile; `envar_record.yaml` defines the top composite `EnvironmentalExposureRecord`.

### Readable top-level names, mapped to the profile

- `EnvironmentalExposureRecord` `instantiates: MicroschemaDefinition` from the [LinkML Microschema Profile](https://github.com/linkml/linkml-microschema-profile). `instantiates` is a metaclass relationship and does not constrain slot names, so the record uses readable domain names (`variable_identity`, `spatial_reference`, `temporal_reference`, `exposure_model`) mapped to the profile's `observation_type`/`location`/`temporality`/`methodology` via slot-level `implements` + `exact_mappings` (`msprofile:` prefix). Only `subject` is used verbatim.
- The profile's `observation_result` is deliberately **not** bound: values live in the companion data file (batch sidecar), and the profile marks it required — binding it would force an inline value and breaks `linkml-run-examples` (the Python dataclass does not honour the optional override).
- **Do not rename via the metamodel's `alias` in `slot_usage`** — the 2026-07 spike showed `gen-python` rejects it ("alias not permitted in slot_usage slot") even though validate/json-schema/pydantic accept it; re-declaring the imported profile slot locally fails with "Conflicting URIs"; `aliases` (plural) is documentation-only. Plain rename + `implements`/`exact_mappings` is the only route that survives the whole generator pipeline.
- `variable_name` in `VariableIdentity` is pure identity; column bindings into the companion data file live in the required `data_layout` (`DataLayout.value_column` etc.). Do not fold column names back into `VariableIdentity` — long/tidy layouts need the split (value column is literally `value`, rows selected by `variable_column`/`variable_key`).
- Full rationale and known drawbacks: `src/linkml_microschemas_envar/schema/README.md` — read it before renaming top-level slots or restructuring `EnvironmentalExposureRecord`.

### Tier annotations vs `required:` — keep them aligned

- Every slot carries `annotations.tier` (`core` / `recommended` / `optional` / `conditionally_core`); the completeness checker (`src/linkml_microschemas_envar/checker.py`) reads tiers from the schema and BLOCKS on missing Core slots.
- Invariant: **`tier: core` implies `required: true`** on induced slots (`slot_usage` overrides count). Enforced by `tests/test_schema.py::test_core_tier_implies_required`; the converse is deliberately not asserted.
- If a Core slot cannot honestly be hard-required, do NOT soften it — re-tier to `conditionally_core` with the context encoded in the schema.
- Conditionally-core contexts are **single-sourced from the schema** (SPEC §7.7): either a LinkML class `rule` on the owning class (preconditions restricted to `equals_string` / `equals_string_in` / `pattern` / `value_presence` — the vocabulary the generator pipeline and checker support) or `required: true` inside a conditional block. When adding one, write the rule in the owning module's YAML — never add lambdas to the checker. Only exceptions: the two cross-class contexts in `RESIDUAL_CONTEXT_PREDICATES` and the not-machine-decidable `source_homogenisation_status`, which carry a `tier_context` annotation.
- Pinned by `test_conditionally_core_contexts_are_single_sourced` and `test_rule_precondition_values_are_permissible` (renaming an enum value cannot silently kill a rule).
- The §4 tier tables in SPEC.md re-state the tiers in prose — update them in the same change.

### Edit-vs-generated boundary

- **Edit:** `src/linkml_microschemas_envar/schema/*.yaml` only.
- **Never edit or track:** `project/` (from `just gen-project`), `docs/elements/` and `docs/schema/` (from `just gen-doc`), `docs/schema_overview.md` + `docs/overview/` (`just render-schema-overview`) and `docs/datasets/` (`just gen-datasets-ledger`). The docs deploy regenerates the site pages.
- Generated but **git-tracked** (never hand-edit): `src/linkml_microschemas_envar/datamodel/` except `__init__.py` (`just gen-python`; installs from git need it) and `docs/standards-index/index.md` (`just standards-index`). **SOP: feature PRs do not update these.** They are regenerated for a release only, in a separate PR for just the model updates. `just test` rewrites the datamodel locally, so discard that before committing: `git checkout -- src/linkml_microschemas_envar/datamodel`.
- The canonical worked example is `examples/daymet_tmax_phoenix_2022_07_19.yaml`.

### Slot evidence — why each slot exists

- Evidence lives in `src/linkml_microschemas_envar/evidence/`, not in the schema: one `<module>.evidence.yaml` per schema module (keyed by slot), the source registry `sources.yaml`, and `evidence.schema.yaml` for their shape. Design and vocabulary: `specs/2026-11-25-slot-evidence-design.md`. Never put evidence back into slot annotations.
- A PR that adds a slot (except `*_missing_reason`) checks it against **every** source in `sources.yaml` and adds `supported_by` items, or a `not_supported_by` entry where the source should have the information and does not (never for "out of scope"). The slot ends with at least one support item or a `no_support_found` entry. This outranks diff size. `unreviewed.yaml` is frozen and not open to new slots.
- Public evidence only, with the document registered in `sources.yaml` at a fixed version. Run `just check-evidence`; only items it passed may say `status: verified` (the lock file enforces this). `confirmed` needs a person's ORCID, date and basis, and means "correct, and may be public". Everything else is `unverified`.
- `legacy` blocks are the old `covered_by` verdicts, copied word for word. They are replaced source by source in review PRs; do not add new ones.
- Offline rules: `tests/test_evidence.py` (`slot_evidence.offline_problems`). Class pages show the evidence through fragments from `scripts/gen_evidence_fragments.py`.

### Keep PR diffs small, without compromising function

- Optimise for few **added/changed** lines; deleted lines do not count. Never drop functionality, tests, validation or required annotations to get there.
- Before committing, run `git diff --stat <base>...` including generated files, find the cause of every large entry, and remove what is avoidable.
- Generators repeat every inherited slot, with all its annotations, for each class and subclass. Keep long text out of annotations on such slots (a duplicated block on `geometry_kind` added about 1800 lines to #52).
- When choosing between designs, measure the generated diff of each and state it with the recommendation.
- Do not track new generated files unless something consumes them from git. Keep unrelated cleanups out of the PR.

## Other context

- Codespell / typos ignore lists live in `pyproject.toml` — add new generated paths to both if you add generators.
- The published Pages site deliberately mixes mkdocs-material pages with standalone HTML copied verbatim from `docs/` (`docs/slides/*.html`, `docs/overview/index.html`, `docs/datasets/index.html`). The visual inconsistency is known and deliberate — do not try to "fix" them into the mkdocs theme.
- The hand-embedded completeness dashboard was retired (2026-07) in favour of the computed datasets ledger; it survives only as a design artefact at `specs/dashboard/index.html` next to `specs/SPEC_DASHBOARD.md`. Do not re-add it to the mkdocs nav or wire it to checker JSON — one completeness page only, so they cannot drift.
- The **standards index** (`docs/standards-index/`): `standards.yaml` is the hand-curated source of truth, validated against the standalone `standards_index.schema.yaml` (deliberately NOT imported into the umbrella). `docs/standards-index/index.md` is generated by `just standards-index` — regenerated at release (see SOP above), never hand-edit. Distinct from `docs/related-approaches.md` (narrative deep-dives). The populating survey lives under `surveys/study-env-exposure-metadata-standards/` (rerun via its `DESIGN.md`; deep-research at concurrency <= 2 to avoid Perplexity rate limits).
