"""Smoke tests for the EnVar microschema set.

These are the tests behind `just _test-python` (which regenerates the Python
datamodel first via `gen-python`). They cover three things:

1. the umbrella schema loads and exposes the expected composite record,
2. the generated Python datamodel imports,
3. every sidecar under tests/data/valid validates and every counter-example
   under tests/data/invalid fails validation (linkml-run-examples does not
   currently pick up the counter-examples, so this is the enforcement point
   for the must-fail gradient).
"""

from pathlib import Path

import pytest
import yaml
from linkml.validator import validate, validate_file
from linkml_runtime import SchemaView

from linkml_microschemas_envar.checker import (
    CONDITIONALLY_CORE,
    CORE,
    RESIDUAL_CONTEXT_PREDICATES,
    CompletenessChecker,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = (
    REPO_ROOT / "src" / "linkml_microschemas_envar" / "schema" / "linkml_microschemas_envar.yaml"
)
VALID_DIR = REPO_ROOT / "tests" / "data" / "valid"
INVALID_DIR = REPO_ROOT / "tests" / "data" / "invalid"
SCENARIOS_DIR = REPO_ROOT / "examples" / "scenarios"

TARGET_CLASS = "EnvironmentalExposureRecord"


def _example_files(directory: Path) -> list[Path]:
    return sorted(directory.glob(f"{TARGET_CLASS}-*.yaml"))


def _yaml_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.yaml"))


@pytest.fixture(scope="module")
def schema_view() -> SchemaView:
    return SchemaView(str(SCHEMA_PATH))


def test_schema_loads_and_has_record(schema_view: SchemaView) -> None:
    record = schema_view.get_class(TARGET_CLASS)
    assert record is not None
    slots = {s.name for s in schema_view.class_induced_slots(TARGET_CLASS)}
    # The readable anatomy names plus the required layout binding.
    for expected in (
        "subject",
        "variable_identity",
        "spatial_reference",
        "temporal_reference",
        "data_layout",
    ):
        assert expected in slots


def test_core_tier_implies_required() -> None:
    """`tier: core` and `required: true` must agree, core-implies-required.

    The checker BLOCKS on a missing Core slot; if that slot is not also
    hard-required, LinkML validation passes a sidecar the checker rejects.
    Induced slots are used so `slot_usage` overrides count. The converse
    (required-implies-core) is not asserted: a conditionally-core slot may
    stay soft in LinkML until SPEC §7.7 encodes its context as a rule.
    """
    checker = CompletenessChecker(schema_path=SCHEMA_PATH)
    sv = checker.schemaview
    offenders = [
        f"{owner}.{name}"
        for name, tier, _module, owner in checker.slot_universe()
        if tier == CORE and not sv.induced_slot(name, owner).required
    ]
    assert not offenders, f"tier: core slots without required: true: {offenders}"


def test_conditionally_core_contexts_are_single_sourced() -> None:
    """Every conditionally-core slot's context lives in the schema.

    A slot is covered when it is (a) hard-required inside its owning class
    (block-presence context), (b) the target of a class rule's postcondition
    on its owner, or (c) explicitly annotated with ``tier_context`` (the
    cross-module residuals evaluated in RESIDUAL_CONTEXT_PREDICATES, and the
    not-machine-decidable cases). A conditionally-core slot covered by none
    of these is a context that exists only in prose — the drift this test
    exists to prevent. Conversely every residual predicate must have its
    ``tier_context`` annotation.
    """
    checker = CompletenessChecker(schema_path=SCHEMA_PATH)
    sv = checker.schemaview
    uncovered, unannotated_residuals = [], []
    for name, tier, _module, owner in checker.slot_universe():
        if tier != CONDITIONALLY_CORE:
            continue
        induced = sv.induced_slot(name, owner)
        required = bool(induced.required)
        rule_covered = any(cls == owner for cls, _ in checker._rule_index.get(name, ()))
        annotated = bool(induced.annotations and "tier_context" in induced.annotations)
        if name in RESIDUAL_CONTEXT_PREDICATES and not annotated:
            unannotated_residuals.append(name)
        if not (required or rule_covered or annotated):
            # the record-root composite slots (e.g. derived_heat_metric) get
            # their conditionality from CONDITIONAL_MODULES, not a context
            if sv.get_slot(name).range in sv.all_classes():
                continue
            uncovered.append(f"{owner}.{name}")
    assert not uncovered, f"conditionally_core slots with no schema-visible context: {uncovered}"
    assert not unannotated_residuals, (
        f"residual predicates missing their tier_context annotation: {unannotated_residuals}"
    )


def test_rule_precondition_values_are_permissible() -> None:
    """Rule preconditions must reference live enum values.

    Renaming a permissible value would otherwise silently kill the rules
    that match on it (both validation and checker read them). Also pins the
    condition vocabulary to what the checker evaluates: equals_string,
    equals_string_in, pattern, value_presence.
    """
    checker = CompletenessChecker(schema_path=SCHEMA_PATH)
    sv = checker.schemaview
    problems = []
    for target, entries in checker._rule_index.items():
        for cls_name, conditions in entries:
            assert conditions, f"rule for {cls_name}.{target} has an empty precondition"
            for cond_slot, expr in conditions:
                values = []
                if expr.equals_string is not None:
                    values = [expr.equals_string]
                elif expr.equals_string_in:
                    values = list(expr.equals_string_in)
                elif expr.pattern is not None:
                    continue  # patterns apply to open ranges (e.g. CURIEs)
                elif getattr(expr, "value_presence", None):
                    continue  # presence checks carry no literal to validate
                else:
                    problems.append(f"{cls_name}.{cond_slot}: unsupported condition kind")
                    continue
                slot_range = sv.induced_slot(cond_slot, cls_name).range
                enum = sv.get_enum(slot_range)
                if enum is None:
                    problems.append(f"{cls_name}.{cond_slot}: equals_string on non-enum range {slot_range}")
                    continue
                for value in values:
                    if value not in enum.permissible_values:
                        problems.append(f"{cls_name}.{cond_slot}: '{value}' not in {slot_range}")
    assert not problems, f"rule preconditions out of sync with the schema: {problems}"


def test_generated_datamodel_imports() -> None:
    from linkml_microschemas_envar.datamodel import linkml_microschemas_envar as dm

    assert hasattr(dm, TARGET_CLASS)


@pytest.mark.parametrize(
    "example", _example_files(VALID_DIR), ids=lambda p: p.stem
)
def test_valid_examples_validate(schema_view: SchemaView, example: Path) -> None:
    # Pass the SchemaView-loaded SchemaDefinition, not the path: the validator
    # resolves the umbrella's sibling imports relative to CWD when handed a
    # path string, so a raw path only works when run from the schema directory.
    report = validate_file(example, schema_view.schema, TARGET_CLASS)
    messages = [r.message for r in report.results]
    assert not messages, f"{example.name} should validate but got: {messages}"


@pytest.mark.parametrize("pct, valid", [(0, True), (66.7, True), (-1, False), (101, False)])
def test_participant_coverage_is_a_percentage(schema_view: SchemaView, pct: float, valid: bool) -> None:
    report = validate({"participant_coverage_pct": pct}, schema_view.schema, "HealthLayerLinkage")
    assert (not report.results) == valid


@pytest.mark.parametrize(
    "counter_example", _example_files(INVALID_DIR), ids=lambda p: p.stem
)
def test_counter_examples_fail_validation(
    schema_view: SchemaView, counter_example: Path
) -> None:
    report = validate_file(counter_example, schema_view.schema, TARGET_CLASS)
    assert report.results, f"{counter_example.name} must FAIL validation but passed"


def _record_with_geometry(geometry: dict | None) -> dict:
    """The pm25 core example with native_geometry replaced (or dropped, if None)."""
    record = yaml.safe_load((VALID_DIR / f"{TARGET_CLASS}-pm25_core.yaml").read_text())
    record["spatial_reference"].pop("native_geometry", None)
    if geometry is not None:
        record["spatial_reference"]["native_geometry"] = geometry
    return record


def _messages(schema_view: SchemaView, record: dict) -> list[str]:
    return [r.message for r in validate(record, schema_view.schema, TARGET_CLASS).results]


@pytest.mark.parametrize(
    "geometry",
    [
        {"geometry_kind": "RegularGrid", "native_spatial_resolution_m": 1000.0},
        {"geometry_kind": "IrregularGrid"},
        {"geometry_kind": "H3Grid", "h3_resolution": 3},
        # Issue #42: polygons used to need an invented number to validate.
        {"geometry_kind": "VectorPolygon"},
        {"geometry_kind": "VectorLine"},
        {"geometry_kind": "VectorPoint"},
    ],
    ids=lambda g: g["geometry_kind"],
)
def test_geometry_validates_with_its_own_slots(schema_view: SchemaView, geometry: dict) -> None:
    assert _messages(schema_view, _record_with_geometry(geometry)) == []


@pytest.mark.parametrize(
    "geometry",
    [
        pytest.param({"geometry_kind": "RegularGrid"}, id="grid-without-metres"),
        pytest.param({"geometry_kind": "H3Grid"}, id="h3-without-resolution"),
        pytest.param({"geometry_kind": "H3Grid", "h3_resolution": 16}, id="h3-resolution-above-15"),
        pytest.param(
            {"geometry_kind": "VectorPolygon", "native_spatial_resolution_m": 1000.0},
            id="polygon-with-metres",
        ),
        pytest.param(
            {"geometry_kind": "H3Grid", "h3_resolution": 3, "native_spatial_resolution_m": 1000.0},
            id="h3-with-metres",
        ),
        pytest.param(
            {"geometry_kind": "RegularGrid", "native_spatial_resolution_m": 1000.0, "h3_resolution": 3},
            id="grid-with-h3-resolution",
        ),
        pytest.param({"geometry_kind": "Banana"}, id="unknown-kind"),
        pytest.param({"geometry_kind": "Geometry"}, id="abstract-parent"),
        pytest.param({"native_spatial_resolution_m": 1000.0}, id="kind-missing"),
    ],
)
def test_geometry_rejects_other_slots(schema_view: SchemaView, geometry: dict) -> None:
    messages = _messages(schema_view, _record_with_geometry(geometry))
    assert len(messages) == 1 and "/spatial_reference/native_geometry" in messages[0], messages


def test_spatial_reference_without_geometry_fails(schema_view: SchemaView) -> None:
    messages = _messages(schema_view, _record_with_geometry(None))
    assert len(messages) == 1 and "'native_geometry' is a required property" in messages[0], messages


def test_datamodel_loads_the_geometry_subclass() -> None:
    from linkml_microschemas_envar.datamodel import linkml_microschemas_envar as dm

    record = dm.EnvironmentalExposureRecord(
        **_record_with_geometry({"geometry_kind": "H3Grid", "h3_resolution": 3})
    )
    assert isinstance(record.spatial_reference.native_geometry, dm.H3Grid)


@pytest.mark.parametrize("target_class", [TARGET_CLASS, "DailyMinTemperatureRecord"])
@pytest.mark.parametrize(
    ("subject_type", "needs_linkage"),
    [(None, True), ("patient", True), ("cohort", True), ("population_geographic_unit", False)],
)
def test_only_geographic_unit_subjects_may_omit_linkage(
    schema_view: SchemaView, subject_type: str | None, needs_linkage: bool, target_class: str
) -> None:
    record = yaml.safe_load((VALID_DIR / f"{TARGET_CLASS}-tmax_core.yaml").read_text())
    del record["linkage_method"]
    if subject_type:
        record["subject_type"] = subject_type
    # The checker's verdict must agree with validation.
    report = CompletenessChecker(SCHEMA_PATH, target_class).check(record)
    missing = "'linkage_method' is a required property in /"
    assert report.validation_messages == ([missing] if needs_linkage else [])
    assert report.blocking == (["linkage_method", "linkage_strategy"] if needs_linkage else [])
    record["linkage_method"] = None  # an explicit null must not pass for a value
    assert needs_linkage == bool(validate(record, schema_view.schema, target_class).results)


@pytest.mark.parametrize(
    "scenario", _yaml_files(SCENARIOS_DIR / "heat_index"), ids=lambda p: p.stem
)
def test_heat_index_scenarios_validate(schema_view: SchemaView, scenario: Path) -> None:
    # The heat-index chain is a complete worked demo (derived metric + two
    # upstream inputs), not a coverage counter-example — it must fully validate.
    # It lives outside tests/data/valid, so this is its only guard against drift.
    report = validate_file(scenario, schema_view.schema, TARGET_CLASS)
    messages = [r.message for r in report.results]
    assert not messages, f"{scenario.name} should validate but got: {messages}"


@pytest.mark.parametrize(
    "scenario", _yaml_files(SCENARIOS_DIR / "standards"), ids=lambda p: p.stem
)
def test_standards_scenarios_only_omit_required(
    schema_view: SchemaView, scenario: Path
) -> None:
    """Standards translations may omit Core fields — but nothing else.

    The standards comparison set (Amadeus / DeGAUSS / GAIA-OMOP) maps only what
    each real pipeline emitted, so slots a pipeline does not supply are
    deliberately absent and the record intentionally fails strict validation
    (the datasets ledger shows this as each standard's true coverage). Full
    validation is therefore the wrong guard. But every *other* kind of error —
    a renamed enum value, an unknown property from a renamed slot, a type
    mismatch — is real schema drift these files must still catch. So: allow
    only ``is a required property`` errors; fail on anything else.
    """
    report = validate_file(scenario, schema_view.schema, TARGET_CLASS)
    drift = [r.message for r in report.results if "is a required property" not in r.message]
    assert not drift, f"{scenario.name} has non-omission schema drift: {drift}"


def test_scenario_examples_exist() -> None:
    # Guard against the silent-empty-directory failure mode: if the scenarios
    # move or are renamed, the parametrized tests above would pass vacuously.
    assert _yaml_files(SCENARIOS_DIR / "heat_index"), "no heat_index scenarios found"
    assert _yaml_files(SCENARIOS_DIR / "standards"), "no standards scenarios found"


def test_counter_examples_exist() -> None:
    # Guard against the silent-empty-directory failure mode: if the
    # counter-examples are renamed away from the ClassName-*.yaml convention,
    # the parametrized test above would pass vacuously.
    assert _example_files(INVALID_DIR), f"no counter-examples found in {INVALID_DIR}"
    assert _example_files(VALID_DIR), f"no examples found in {VALID_DIR}"
