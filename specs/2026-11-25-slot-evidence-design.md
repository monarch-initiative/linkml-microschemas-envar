# Slot evidence design: `supported_by`, `not_supported_by` and a source registry

**Date:** 2026-11-25
**Status:** Approved 2026-11-25. PR 1 (foundation and conversion) implemented.
**Issue:** #58 (also closes the design question in #34)
**Supersedes:** the `covered_by` data model in `specs/2026-07-03-standard-coverage-design.md` (§3, §10)

## 1. Intent

Every slot in the schema should show why it exists, with evidence that someone
outside the project can check. Justifying each slot may be the most important
part of the schema in the end.

Today a slot can have a `covered_by` annotation with one verdict per source
(`extent`, `status`, `where`, `evidence`, `note`). On `main` there are 614
entries on 103 slots. They have three problems:

- The evidence is free text. 1 of the 208 positive entries has a URL or DOI,
  2 contain quoted text. Nothing can be checked by a machine.
- The source keys (`clad`, `omop_gaia`, ...) are bare strings with no metadata.
- Some entries cite details that are in no public document (for example C-HER
  database column names).

The new system replaces `covered_by`. Nothing useful in the 614 entries may be
lost on the way.

## 2. Goals, non-goals, anti-goals

**Goals**

- Positive evidence per slot as a list of evidence items with a checkable
  pointer: a field in a source schema, a quote from documentation, a field in
  a real output, or an argument from the literature.
- Negative evidence only where it says something: the source should have the
  information and does not. Each entry gives a reason and the closest thing
  the source has.
- A registry of sources and their documents, each document fixed to a version.
- Three trust levels per item: checked automatically, confirmed by a named
  person from a private source, or not yet verified.
- A lossless migration of the 614 entries, reviewable in pieces.

**Non-goals**

- The coverage matrix and the "why not X?" scorecards from the 2026-07-03
  spec. They were never built. The evidence files make them possible later,
  but negatives are no longer exhaustive, so their scoring needs its own
  design.
- Crosswalks or mappings (SSSOM, linkml-map). `match: full | partial` is
  enough for now.
- Filling in paper evidence (#34) during the migration. The type exists, the
  content comes in a later pass.
- Publishing the GAIA and amadeus example outputs in `monarch-initiative/envar`.
  That is work in the other repo.

**Anti-goals**

- Hundreds of low-value "out of scope" entries. Out-of-scope is never
  recorded per slot.
- A claim that looks verified but is not. `verified` can only be set by the
  checking tool.
- Non-public details moved into the new system without a person vouching
  for them.
- Evidence copied into generated code. Annotations are part of the schema, so
  the generators write each `covered_by` block into every generated class that
  uses the slot (this is most of the 33,632 lines of the Pydantic model). The
  evidence must live in one place, outside what the generators read.

## 3. Decisions made with Nico (2026-11-25)

| # | Question | Decision |
|---|---|---|
| 1 | Negative verdicts | Separate list `not_supported_by`. `supported_by` is positive only. |
| 2 | "The closest the source has" | Explanation in prose, plus an optional evidence item (`closest`) in the same shape as a support item, so it can be checked. |
| 3 | Which negatives to record | Only where the source should have the information "in some vague sense of should". Working rule: the source does the step, or holds the thing, that the slot is about. A tool that passes on someone else's data should have passed on everything the producer stated about it (model skill, biases, licence, DOI, uncertainty). Out of scope is never recorded. |
| 4 | Evidence from real runs | Third support type `output`: a public file at a fixed version, the field and optionally an example value. Only the source's own output counts, not columns written by our example scripts. |
| 5 | `partial` | An entry is support only if the source states at least part of what the slot asks for. Then `match: full` or `match: partial` on the support item; `partial` must say what is missing. Entries that are a different concept, an unused carrier or only inferable move to `not_supported_by`. |
| 6 | Where evidence lives | Side files, one per schema module, with their own LinkML schema. Not in slot annotations. |
| 7 | Source registry | A separate `sources.yaml`, with an optional link to the entry in `docs/standards-index/standards.yaml`. Ids may be renamed freely (pre-alpha). |
| 8 | How a quote points to its document | Documents are registered once under their source (id, fixed URL, version, retrieved date). A support item cites the document id and an optional locator. |
| 9 | Papers (#34) | Fourth support type `argument`: a paper or document argues that the information is needed. Sources of kind `paper`. No `match`. Filled in a later pass. |
| 10 | Claims without a checkable public quote | They stay on their slot with `status: unverified`, shown with a flag, never counted as verified. Details with no public source are rewritten against a public document or removed, unless a person confirms them (11). |
| 11 | Manual confirmation | `status: confirmed` with the confirmer's ORCID, the date and the basis. A confirmation asserts that the item is correct **and** that the details shown may be public. |
| 12 | When a slot counts as justified | At least one support item, or an explicit `no_support_found` entry (who looked, when, where). |
| 13 | Migration | Convert all entries first (lossless, as unverified), then verify source by source in separate PRs. |

## 4. Approaches considered for the migration

1. **Convert everything first, then verify source by source (chosen).** One PR
   builds the schemas, the registry and the tooling, and a script moves all
   614 entries into the side files with their old text word for word.
   `covered_by` leaves the schema in that PR. Then one PR per source does the
   judgment work. Nothing is lost at any step and each review is about 100
   entries. Cost: for a while most items are unverified.
2. **Both systems side by side.** `covered_by` stays and loses one source at a
   time. No unverified backlog in the new files, but two systems for weeks and
   docs that have to show both.
3. **One PR for everything.** No in-between state, but 614 judgment calls in
   one review.

Chosen: 1, because the lossless part is mechanical and the judgment calls
arrive in pieces small enough to check.

## 5. Data model

### 5.1 Files

My call (differs slightly from "next to the module"): a sibling directory, not
the schema directory itself, because `just lint` runs `linkml-lint` over every
YAML file in `src/linkml_microschemas_envar/schema/` and would treat data
files as schemas.

```
src/linkml_microschemas_envar/evidence/
  evidence.schema.yaml          # LinkML schema for the files below (not imported by the umbrella)
  sources.yaml                  # registry of sources and documents
  envar_spatial.evidence.yaml   # one per schema module that has slots
  envar_temporal.evidence.yaml
  ...
  evidence.lock.yaml            # written by the checker (§6.2): document hashes and item fingerprints
  unreviewed.yaml               # shrinking baseline (§6.3)
```

### 5.2 Registry: `sources.yaml`

```yaml
sources:
  - id: chel
    name: CHEL
    kind: dataset_repository      # standard | tool | dataset_repository | paper
    url: https://github.com/cladteam/CHEL
    standards_index_id: null      # id in docs/standards-index/standards.yaml, if any
    reviewed:                     # last time all slots were checked against this source
      date: 2026-11-25
      unchecked_slots: []         # slots not yet checked against this source
    documents:
      - id: chel-documentation
        title: CHEL Documentation.md
        url: https://raw.githubusercontent.com/cladteam/CHEL/4dd219e256ba664a9151d4d8d7aefac65ef2ce28/Documentation.md
        version: "4dd219e (2026-10-28)"
        retrieved: 2026-11-25
```

- A document URL should be fixed to a version (commit, tag, DOI of a versioned
  report). The checker records the `sha256` of the fetched bytes in
  `evidence.lock.yaml`, so a changed document is detected either way.
- `reviewed` is absent until a source's verification PR is merged. Slots not
  yet checked against the source are listed in `unchecked_slots`.
- Ids (my call): `chel` (was `clad`; every entry cites CHEL documents),
  `omop_gaia`, `degauss`, `amadeus`, `cher`, `codata`. Lower-case snake case.
  `codata` links to `codata-ev`, `degauss` to `degauss`, `omop_gaia` to
  `omop-cdm` in the standards index.

### 5.3 Evidence files

Keyed by slot name. A class-local attribute uses `ClassName.attribute_name`.

```yaml
crs:
  supported_by:
    - source: omop_gaia
      support:
        - type: schema
          document: gaiadb-init-schema
          locator: "working.data_source"
          source_slot: data_source.srid
          source_label: SRID                  # optional
          match: full
          explanation: "SRID of the source geometry, stored per data source."
          status: verified
    - source: amadeus
      support:
        - type: output                          # no document: the file is not public yet
          field: coordinate_system
          value: "WGS84,EPSG:4326"            # optional
          match: full
          explanation: "..."
          status: unverified
  not_supported_by:
    - source: cher
      reason: not_recorded
      explanation: >-
        The resource fields give spatial extent and resolution codes but no
        CRS. Closest is the spatial resolution code.
      closest:                                 # optional, same shape as a support item, no match
        - type: documentation
          document: cher-metadata-report
          locator: "p. 7"
          snippet: "Spatial resolution ... c00 ... County-level data"
          status: verified
      status: confirmed
      confirmation:
        by: https://orcid.org/0000-0002-1825-0097
        date: 2026-11-25
        basis: "C-HER internal metadata database, not public"

day_boundary_convention:
  no_support_found:
    by: https://orcid.org/0000-0002-1825-0097
    date: 2026-11-25
    searched: [chel, omop_gaia, degauss, amadeus, cher, codata]
    note: "No source states where its day starts. Argument from literature still to add."
```

**Evidence entry** (one per slot and source in `supported_by`): `source`,
`support` (one or more items).

**Support item**

| Field | Types | Notes |
|---|---|---|
| `type` | all | `schema`, `documentation`, `output`, `argument` |
| `document` | all | id of a document of that source in `sources.yaml`. Required for `verified`; optional for `unverified` and `confirmed` (my call), because private material and unpublished outputs have no public document. A registered document always has a public URL. |
| `locator` | all, optional | section, page, table, line |
| `source_slot`, `source_label` (optional) | `schema` | the cited field in the source |
| `snippet` | `documentation`, `argument` | abbreviated but accurate quote; `...` marks omitted text, `[...]` an editorial insertion (linkml-reference-validator conventions) |
| `field`, `value` (optional) | `output` | the field in the output file and an example value |
| `match` | `schema`, `documentation`, `output` | `full` or `partial`; not allowed on `argument` |
| `explanation` | all | for `schema`: how `source_slot` relates to our slot. For the others: how the quote or field was read as support. Required when `match: partial`, and must say what is missing. |
| `status` | all | `verified`, `confirmed`, `unverified` |
| `confirmation` | when `confirmed` | `by` (ORCID URL), `date`, `basis` (names the private source without quoting it). The key is `date`, not `on`: YAML 1.1 reads a bare `on` as the boolean true. |

**Non-support entry** (one per slot and source in `not_supported_by`):
`source`, `reason`, `explanation` (must name the closest thing the source has,
or say that nothing close was found and where we looked), optional `closest`
(list of support-shaped items without `match`), `status`, `confirmation`.

`reason` values:

| Value | Meaning | Example |
|---|---|---|
| `not_recorded` | In scope, but nothing states it | C-HER: no CRS field |
| `implicit` | True, but must be inferred | DeGAUSS: daily, from one row per day |
| `different_granularity` | Stated at another level | C-HER: dataset time span, not the run's window |
| `different_concept` | Looks similar, is something else | C-HER: the resource's DOI, not the model paper's |
| `not_sure` | Not checked well enough to say | GAIA entries that only describe our Tmax example |

There is no `out_of_scope` value. A negative entry may be `verified` only
through its `closest` items; the absence itself can only be `confirmed` or
`unverified`.

**`no_support_found`**: `by` (ORCID of the person who answers for the search),
`date`, `searched` (source ids), `note`. Allowed only when `supported_by` is
empty. It is written by a reviewer in a verification PR, never by the
conversion script. `searched` may list fewer than all sources while other
sources are still unreviewed; it is extended as they are done.

**Migration-only field `legacy`** on an evidence or non-support entry:
`{extent, status, where, evidence, note}` copied word for word from the old
annotation. While `legacy` is present, `support`, `reason` and `explanation`
may be missing and the entry counts as unverified. The verification PRs
replace `legacy` blocks; the goal is zero.

## 6. Checks

### 6.1 Offline (part of `just test`, no network)

- Evidence files and `sources.yaml` validate against `evidence.schema.yaml`
  (enums for type, match, status, reason, kind).
- Every key is a slot (or `Class.attribute`) in the schema. Every `source` and
  `document` id resolves, and the document belongs to that source.
- Per-type required fields (table above). `match` absent on `argument`.
- `confirmed` requires `by` (an ORCID URL with a correct check digit), `date`
  and a non-empty `basis`. The examples here use ORCID's own sample id.
- Fields of another evidence type are rejected (a `snippet` on a `schema`
  item would be shown but never checked). Source ids and document ids are
  unique across the registry. A slot key may appear once.
- `verified` requires a `document` and a matching entry in
  `evidence.lock.yaml` (§6.2).
- Completeness (§6.3).
- No `covered_by` annotation anywhere in the schema.

### 6.2 Quote and field check (`just check-evidence`, needs network)

Correction to what was said in the design conversation: document copies are
**not** committed. CHEL, gaiaDB, degauss/daymet and monarch-initiative/envar
have no licence, so their text may not be redistributed in this repo.

- Items without a `document` are skipped and reported. An unfetchable
  registered document is a failure.
- The checker fetches each document from its registered URL (a copy goes to
  the gitignored `.evidence_cache/` for inspection) and records its `sha256`
  in `evidence.lock.yaml`.
- `documentation` and `argument`: the snippet must appear in the document
  text, using linkml-reference-validator's matching (`...`, `[...]`). Every
  part between `...` needs at least two words. Known limit of the library:
  the parts may match in any order, anywhere in the document, so a quote with
  `...` proves less than a continuous one.
- `schema`: `source_slot` (its last path segment) must appear in the document.
- `output`: `field` must be a column or key of the file; `value`, if given,
  must occur in that column or under that key.
- For each passing item the checker writes an entry to `evidence.lock.yaml`:
  a hash of the item's checkable fields plus the document `sha256`. The
  checker never rewrites the hand-edited files: the author writes
  `status: verified`, and the offline test accepts it only with a lock entry.
  Editing a verified snippet, or a changed document, breaks the lock entry
  and the offline test fails until the checker runs again.
- When a document cannot be fetched, the lock file is left as it was.
- CI runs the offline checks only. The network check is run locally and can
  later become a scheduled workflow.
- PDFs (the ORNL reports): text is extracted for matching. Closed papers are
  handled in the paper pass (signed excerpts or `confirmed`).

### 6.3 Completeness

Of 199 tiered slots, 45 are `*_missing_reason` (exempt), 103 have `covered_by`
today and 51 have none.

- Every non-exempt slot needs at least one `supported_by` entry or a
  `no_support_found` entry, or it must be listed in `unreviewed.yaml`.
- During the migration any entry with a `legacy` block counts, positive or
  negative (my call). 27 of the 103 slots have only negative entries today;
  they pass through their legacy entries until their sources are reviewed,
  and then need support or `no_support_found`.
- `unreviewed.yaml` starts with the 51 slots nobody has looked at, plus
  `subject` (the profile's slot, which gets its tier through `slot_usage` on
  the record and was not counted in the 199). The test
  fails if a slot in it has any entry, and fails if the file names a slot
  outside that frozen list, so it can only shrink. A reviewed slot is removed
  from the file and from the frozen list together. It is not open to new
  slots.
- A report (part of `just check-evidence`, printed, not committed) gives:
  items by status, `legacy` blocks left, slots with `no_support_found`, slots
  in `unreviewed.yaml`.

## 7. Docs

The class pages show a "Covered by" block per slot today, read from the
annotation by `docs/templates-linkml/class.md.jinja2`. After the change each
slot's entry on the class page shows: support items by source (type, match,
status flag, explanation, link to the document), non-support entries (reason,
explanation), and `no_support_found`. `unverified` and `confirmed` are visibly
marked. `legacy` entries are shown with the old text and an "unverified,
to be reviewed" flag.

## 8. Migration

### PR 1: foundation and lossless conversion

- `evidence.schema.yaml`, `sources.yaml` (six sources, no documents needed
  yet), offline checks, `just check-evidence`, docs.
- A conversion script moves every `covered_by` entry into the evidence file of
  its module:
  - `full`, `partial` → `supported_by` entry with `legacy`.
  - `absent`, `out_of_layer` → `not_supported_by` entry with `legacy`.
  - `clad` → `chel`.
- `covered_by` is removed from the schema. `tests/test_coverage.py` is
  replaced. The 2026-07-03 spec gets a "superseded by" line. CLAUDE.md's
  `covered_by` rules are rewritten for the new system.
- Acceptance: the number of converted entries per source and extent equals
  the number in the schema before (asserted by the script), every old field
  value is present verbatim, `just test` exits 0.
- Per the repo SOP, the generated datamodel is not updated in this PR.

### PRs 2 to 7: one per source

Order: `chel` (public docs), `degauss` (public outputs), `omop_gaia`,
`amadeus`, `cher`, `codata`.

For every `legacy` entry of that source:

1. Register the documents it needs.
2. Positive entries: apply decision 5. Support → write the items, run the
   checker. Otherwise → move to `not_supported_by` with reason and closest.
3. Negative entries: apply decision 3. Should have it → reason, explanation,
   closest. Out of scope → remove.
4. No public source → rewrite against a public document, or keep the item as
   `unverified` (without `document`) for a confirmer, or remove. The
   `omop_gaia` and `amadeus` PRs do not wait for the example outputs to be
   published: items that need them stay `unverified`. Details from private material stay
   only as `unverified` awaiting confirmation; if a confirmer says they may
   not be public, they are removed.
5. Set `reviewed` on the source.

The PR text lists every removed entry with its old note, so each removal can
be vetoed. Known cases to look at:

- CODATA: 95 of 96 negatives are `out_of_layer`. A few hold real content
  (`variable_identity` reads like support; `variable_label` names I-ADOPT
  Object/Property as the closest thing).
- GAIA: at least eight negatives describe our Tmax example, not GAIA
  (`not_sure`). One `partial` on `time_column` may be stale since
  OHDSI/gaiaDB#48.
- amadeus: `person_id`, `value_kelvin`, `value_celsius` are written by our
  `amadeus_extract.R`, and 21 entries cite the gridMET THREDDS response, which
  is the data server's, not amadeus's.
- C-HER: `table_column_dictionary`, `column_tag`, `dataset_lineage` and
  similar names do not appear in the public report (ORNL/TM-2026/4743).
- `verified` entries (42) cite `COMPARISON.md`; the DeGAUSS outputs are public
  in monarch-initiative/envar, the GAIA and amadeus outputs are not.

### Later

- Review the 51 slots in `unreviewed.yaml`.
- Paper pass (#34): `argument` items, starting with the `no_support_found` slots.
- Confirmations from the source teams.
- Open PRs that add slots (#54, #55, #56) add evidence in the new format
  once PR 1 is merged (see below).

### New slots after PR 1 (my call, replaces the CLAUDE.md `covered_by` rule)

A PR that adds a slot (except `*_missing_reason`):

- checks the slot against every source in the registry, and adds support
  items, or a non-support entry where the source should have the information;
- ends with at least one support item or a `no_support_found` entry;
- runs `just check-evidence`, so that everything with a public document is
  `verified`. `unverified` is allowed only where no public document exists,
  and the explanation says so;
- may not add the slot to `unreviewed.yaml`.

If a source cannot be checked in that PR, the slot is listed under that
source's `reviewed.unchecked_slots` in `sources.yaml`. `reviewed` is informational:
no test reads it.

## 9. Left to the builder

- How the class pages get the evidence (a doc-only schema copy with the
  evidence injected as annotations, which a spike showed the generators
  accept, or generated pages linked from the template).
- Exact class and slot names in `evidence.schema.yaml`, as long as the YAML
  shape in §5 holds.
- The hash recipe for `evidence.lock.yaml`.
- Whether the checker calls linkml-reference-validator as a library or CLI,
  and how PDFs are converted to text.
- File names of the scripts and recipes.

## 10. Risks

- Unverified items stay for a long time. The report in §6.3 makes the number
  visible; no deadline is set.
- Sources without a licence cannot be mirrored, so the quote check depends on
  their URLs staying up. Fixed commits on GitHub are stable; the OSTI PDFs are
  less certain.
- "Should have" (decision 3) is a judgment. The per-source PRs make each call
  reviewable, and `not_sure` exists for the unclear ones.
