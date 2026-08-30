"""Deterministic Part 4 source materialization and provenance validation."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import struct
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .canonical import canonical_json, digest, digest_records
from .generator import generate_batch, with_broken_total, with_overlapping_dimension
from .manifest import build_manifest, manifest_from_dict

REPOSITORY = "bhuvaneshwaranmurugan21/atlasretail-lakehouse-platform"
CATALOG_RELATIVE_PATH = Path("contracts/part4/scenario-sources.json")
PROVENANCE_SCHEMA_RELATIVE_PATH = Path("contracts/part4/source-provenance.schema.json")
SOURCE_MANIFEST_SCHEMA_RELATIVE_PATH = Path("contracts/part4/source-manifest.schema.json")
MANAGED_MANIFEST_SCHEMA_RELATIVE_PATH = Path("contracts/retail-v2.schema.json")
CONTRACT_RELATIVE_PATH = Path("contracts/part4/run-contract.json")
TARGET_RELATIVE_PATH = Path(".github/atlas-target.json")
FORMAT_VERSION = "1.0.0"
TABLES = (
    "inventory_movements",
    "order_lines",
    "orders",
    "payments",
    "products",
    "returns",
)
FAULTS = {"none", "financial", "temporal-overlap"}
SOURCE_FAMILIES = {"failure_recovery", "financial", "success", "tamper", "temporal"}
SCENARIO_BINDINGS = {
    "athena_verification": ("failure_recovery", "VERIFY_ACTIVE_RECOVERED_SOURCE"),
    "conflict": ("success", "CONTRADICT_IDENTITY"),
    "failure": ("failure_recovery", "INJECT_RUNTIME_FAILURE"),
    "financial": ("financial", "EXECUTE_SOURCE"),
    "recovery": ("failure_recovery", "REUSE_EXACT_FAILURE_SOURCE"),
    "replay": ("success", "REUSE_EXACT_REGISTRATION"),
    "stale_publisher": ("success", "REUSE_PUBLISHED_WINNER"),
    "success": ("success", "EXECUTE_SOURCE"),
    "tamper": ("tamper", "MUTATE_ONE_REGISTERED_OBJECT_VERSION"),
    "temporal": ("temporal", "EXECUTE_SOURCE"),
}
EXPECTED_GENERATOR = {
    "canonical_json": {
        "encoding": "utf-8",
        "ensure_ascii": True,
        "key_order": "SORTED",
        "line_ending": "LF",
        "separators": [",", ":"],
    },
    "compression": {
        "algorithm": "gzip",
        "compresslevel": 9,
        "filename": "",
        "mtime": 0,
        "os_byte": 255,
    },
    "format_version": FORMAT_VERSION,
}
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
TAMPER_REPLACEMENT = b"deliberately-corrupted-object"


class ProvenanceError(ValueError):
    """Raised when source provenance is incomplete, ambiguous, or contradictory."""


@dataclass(frozen=True)
class CatalogValidation:
    contract_sha256: str
    target_sha256: str
    catalog_sha256: str
    source_family_count: int
    scenario_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "catalog_sha256": self.catalog_sha256,
            "contract_sha256": self.contract_sha256,
            "result": "PASS",
            "scenario_count": self.scenario_count,
            "source_family_count": self.source_family_count,
            "target_sha256": self.target_sha256,
        }


def _fail(path: str, observed: object, required: object) -> NoReturn:
    raise ProvenanceError(f"{path}: observed {observed!r}; required {required!r}")


def _require_equal(path: str, observed: object, required: object) -> None:
    if observed != required:
        _fail(path, observed, required)


def _require_keys(path: str, value: dict[str, Any], required: set[str]) -> None:
    _require_equal(f"{path}.keys", set(value), required)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"{path}: unable to load JSON: {error}") from error
    if not isinstance(value, dict):
        _fail(str(path), type(value).__name__, "JSON object")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def validate_order_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("order_count", value, "integer from 100 through 2000")
    if not 100 <= value <= 2000:
        _fail("order_count", value, "integer from 100 through 2000")
    return value


def _validate_parameters(
    parameters: dict[str, object], *, source_family: str, catalog: dict[str, Any]
) -> None:
    _require_keys(
        "parameters",
        parameters,
        {"order_count", "seed", "fault", "produced_at", "as_of_knowledge_time"},
    )
    validate_order_count(parameters["order_count"])
    if source_family not in SOURCE_FAMILIES:
        _fail("source_family", source_family, sorted(SOURCE_FAMILIES))
    specification = catalog["source_families"][source_family]
    _require_equal("parameters.seed", parameters["seed"], specification["seed"])
    _require_equal("parameters.fault", parameters["fault"], specification["fault"])
    _require_equal(
        "parameters.produced_at", parameters["produced_at"], specification["produced_at"]
    )
    _require_equal(
        "parameters.as_of_knowledge_time",
        parameters["as_of_knowledge_time"],
        specification["as_of_knowledge_time"],
    )


def validate_catalog(catalog: dict[str, Any], *, repo_root: Path) -> CatalogValidation:
    """Validate the complete source catalogue against the frozen Stage 1 contract."""

    _require_keys(
        "catalog",
        catalog,
        {
            "schema_version",
            "contract_sha256",
            "target_sha256",
            "generator",
            "source_families",
            "scenario_bindings",
        },
    )
    _require_equal("catalog.schema_version", catalog["schema_version"], "1.0")
    _require_equal("catalog.generator", catalog["generator"], EXPECTED_GENERATOR)

    contract = _load_object(repo_root / CONTRACT_RELATIVE_PATH)
    contract_sha256 = _canonical_sha256(contract)
    _require_equal("catalog.contract_sha256", catalog["contract_sha256"], contract_sha256)
    target_sha256 = _file_sha256(repo_root / TARGET_RELATIVE_PATH)
    _require_equal("catalog.target_sha256", catalog["target_sha256"], target_sha256)

    contract_scenarios = {item["name"] for item in contract.get("scenarios", [])}
    _require_equal("contract.scenarios", contract_scenarios, set(SCENARIO_BINDINGS))
    bindings = catalog["scenario_bindings"]
    if not isinstance(bindings, dict):
        _fail("catalog.scenario_bindings", type(bindings).__name__, "JSON object")
    _require_equal("catalog.scenario_bindings.names", set(bindings), contract_scenarios)
    for scenario, (family, operation) in SCENARIO_BINDINGS.items():
        _require_equal(
            f"catalog.scenario_bindings.{scenario}",
            bindings[scenario],
            {"operation": operation, "source_family": family},
        )

    families = catalog["source_families"]
    if not isinstance(families, dict):
        _fail("catalog.source_families", type(families).__name__, "JSON object")
    _require_equal("catalog.source_families.names", set(families), SOURCE_FAMILIES)
    seeds: set[int] = set()
    prefixes: set[str] = set()
    for name, raw_specification in families.items():
        if not isinstance(raw_specification, dict):
            _fail(f"catalog.source_families.{name}", type(raw_specification).__name__, "object")
        specification: dict[str, Any] = raw_specification
        _require_keys(
            f"catalog.source_families.{name}",
            specification,
            {"seed", "fault", "batch_prefix", "produced_at", "as_of_knowledge_time"},
        )
        seed = specification["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            _fail(f"catalog.source_families.{name}.seed", seed, "non-negative integer")
        if seed in seeds:
            _fail(f"catalog.source_families.{name}.seed", seed, "unique seed")
        seeds.add(seed)
        fault = specification["fault"]
        if fault not in FAULTS:
            _fail(f"catalog.source_families.{name}.fault", fault, sorted(FAULTS))
        prefix = specification["batch_prefix"]
        if not isinstance(prefix, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", prefix):
            _fail(f"catalog.source_families.{name}.batch_prefix", prefix, "safe prefix")
        if prefix in prefixes:
            _fail(f"catalog.source_families.{name}.batch_prefix", prefix, "unique prefix")
        prefixes.add(prefix)
        for field in ("produced_at", "as_of_knowledge_time"):
            timestamp = specification[field]
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
                _fail(f"catalog.source_families.{name}.{field}", timestamp, "non-negative integer")

    _require_equal(
        "failure/recovery source",
        bindings["failure"],
        {"operation": "INJECT_RUNTIME_FAILURE", "source_family": "failure_recovery"},
    )
    _require_equal(
        "recovery exact source",
        bindings["recovery"],
        {"operation": "REUSE_EXACT_FAILURE_SOURCE", "source_family": "failure_recovery"},
    )
    _require_equal(
        "replay exact registration",
        bindings["replay"],
        {"operation": "REUSE_EXACT_REGISTRATION", "source_family": "success"},
    )
    return CatalogValidation(
        contract_sha256=contract_sha256,
        target_sha256=target_sha256,
        catalog_sha256=_canonical_sha256(catalog),
        source_family_count=len(families),
        scenario_count=len(bindings),
    )


def validate_catalog_file(path: Path, *, repo_root: Path) -> CatalogValidation:
    return validate_catalog(_load_object(path), repo_root=repo_root)


def validate_provenance_schema_file(path: Path) -> str:
    """Fail closed if the checked-in receipt schema no longer describes the emitted envelope."""

    schema = _load_object(path)
    _require_equal(
        "provenance_schema.$schema",
        schema.get("$schema"),
        "https://json-schema.org/draft/2020-12/schema",
    )
    _require_equal("provenance_schema.type", schema.get("type"), "object")
    _require_equal(
        "provenance_schema.additionalProperties", schema.get("additionalProperties"), False
    )
    required = schema.get("required")
    if not isinstance(required, list):
        _fail("provenance_schema.required", type(required).__name__, "JSON array")
    _require_equal(
        "provenance_schema.required",
        set(required),
        {
            "batch_id",
            "bundle_content_sha256",
            "contract_sha256",
            "expected_results_sha256",
            "files",
            "generator",
            "managed_manifest_schema_sha256",
            "manifest_sha256",
            "parameters",
            "provenance_schema_sha256",
            "receipt_sha256",
            "repository",
            "source_manifest_schema_sha256",
            "scenario_catalog_sha256",
            "schema_version",
            "source_commit",
            "source_family",
            "target_sha256",
        },
    )
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        _fail("provenance_schema.properties", type(properties).__name__, "JSON object")
    _require_equal("provenance_schema.properties", set(properties), set(required))
    return _file_sha256(path)


def validate_manifest_schemas(*, repo_root: Path) -> tuple[str, str]:
    """Prove that source and managed manifests have distinct object-identity boundaries."""

    source_path = repo_root / SOURCE_MANIFEST_SCHEMA_RELATIVE_PATH
    managed_path = repo_root / MANAGED_MANIFEST_SCHEMA_RELATIVE_PATH
    source = _load_object(source_path)
    managed = _load_object(managed_path)
    for name, schema in (("source", source), ("managed", managed)):
        _require_equal(
            f"{name}_manifest_schema.$schema",
            schema.get("$schema"),
            "https://json-schema.org/draft/2020-12/schema",
        )
        _require_equal(f"{name}_manifest_schema.type", schema.get("type"), "object")
        _require_equal(
            f"{name}_manifest_schema.additionalProperties",
            schema.get("additionalProperties"),
            False,
        )
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            _fail(f"{name}_manifest_schema.properties", type(properties).__name__, "object")
        contract = properties.get("contract_version")
        if not isinstance(contract, dict):
            _fail(f"{name}_manifest_schema.contract_version", type(contract).__name__, "object")
        _require_equal(
            f"{name}_manifest_schema.contract_version", contract.get("const"), "retail-v2"
        )
    source_definitions = source.get("$defs")
    managed_definitions = managed.get("$defs")
    if not isinstance(source_definitions, dict) or not isinstance(managed_definitions, dict):
        _fail("manifest_schema.$defs", "missing", "JSON objects")
    source_table = source_definitions.get("tableProof")
    managed_table = managed_definitions.get("tableProof")
    if not isinstance(source_table, dict) or not isinstance(managed_table, dict):
        _fail("manifest_schema.tableProof", "missing", "JSON objects")
    source_objects = source_table.get("properties", {}).get("objects", {})
    managed_objects = managed_table.get("properties", {}).get("objects", {})
    _require_equal("source_manifest_schema.objects.maxItems", source_objects.get("maxItems"), 0)
    _require_equal("managed_manifest_schema.objects.minItems", managed_objects.get("minItems"), 1)
    return _file_sha256(source_path), _file_sha256(managed_path)


def deterministic_gzip(payload: bytes) -> bytes:
    """Create a gzip member with no clock, path, host, or platform-dependent header fields."""

    compressor = zlib.compressobj(
        level=9,
        method=zlib.DEFLATED,
        wbits=-zlib.MAX_WBITS,
        memLevel=zlib.DEF_MEM_LEVEL,
        strategy=zlib.Z_DEFAULT_STRATEGY,
    )
    deflated = compressor.compress(payload) + compressor.flush()
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload) & 0xFFFFFFFF)
    return header + deflated + trailer


def canonical_ndjson(rows: Iterable[dict[str, Any]]) -> bytes:
    return ("".join(f"{canonical_json(row)}\n" for row in rows)).encode("utf-8")


def _write_bytes_atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _write_bytes_atomic(
        path,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def generate_source_data(
    output: Path,
    *,
    orders: int,
    seed: int,
    batch_id: str,
    fault: str,
    produced_at: int = 1_700_100_000,
    as_of_knowledge_time: int = 1_700_100_000,
) -> None:
    """Generate one deterministic source directory without creating its provenance receipt."""

    if fault not in FAULTS:
        _fail("fault", fault, sorted(FAULTS))
    batch = generate_batch(order_count=orders, seed=seed)
    if fault == "financial":
        batch = with_broken_total(batch)
    elif fault == "temporal-overlap":
        batch = with_overlapping_dimension(batch)
    manifest = build_manifest(
        batch,
        batch_id=batch_id,
        produced_at=produced_at,
        as_of_knowledge_time=as_of_knowledge_time,
    )
    for table, rows in sorted(batch.tables().items()):
        payload = canonical_ndjson(rows)
        _write_bytes_atomic(
            output / table / f"{batch_id}.jsonl.gz",
            deterministic_gzip(payload),
        )
    _write_json(output / "manifest.json", manifest.to_dict())
    _write_json(
        output / "expected-results.json",
        {
            "gross_cents": sum(order.total_cents for order in batch.orders),
            "orders": len(batch.orders),
        },
    )


def _records_from_payload(payload: bytes, path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in payload.decode("utf-8").splitlines():
        value: object = json.loads(line)
        if not isinstance(value, dict):
            _fail(str(path), type(value).__name__, "NDJSON object")
        records.append(value)
    return records


def build_receipt(
    directory: Path,
    *,
    repo_root: Path,
    source_commit: str,
    source_family: str,
    batch_id: str,
    parameters: dict[str, object],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    if not COMMIT_PATTERN.fullmatch(source_commit):
        _fail("source_commit", source_commit, "40-character lowercase commit SHA")
    catalog_result = validate_catalog(catalog, repo_root=repo_root)
    _validate_parameters(parameters, source_family=source_family, catalog=catalog)
    source_schema_sha256, managed_schema_sha256 = validate_manifest_schemas(repo_root=repo_root)
    manifest_path = directory / "manifest.json"
    expected_path = directory / "expected-results.json"
    if directory.is_symlink():
        _fail("source.directory", str(directory), "non-symlink directory")
    for observed in directory.rglob("*"):
        if observed.is_symlink():
            _fail("source.symlink", observed.relative_to(directory).as_posix(), "regular file")
    manifest = manifest_from_dict(_load_object(manifest_path))
    _require_equal("manifest.batch_id", manifest.batch_id, batch_id)
    _require_equal("manifest.tables", set(manifest.tables), set(TABLES))
    for table, proof in manifest.tables.items():
        _require_equal(f"manifest.tables.{table}.objects", proof.objects, ())
    files: list[dict[str, object]] = []
    records_by_table: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:
        paths = sorted((directory / table).glob("*.jsonl.gz"))
        _require_equal(f"source.{table}.file_count", len(paths), 1)
        path = paths[0]
        relative = path.relative_to(directory).as_posix()
        compressed = path.read_bytes()
        try:
            uncompressed = zlib.decompress(compressed, wbits=31)
        except zlib.error as error:
            raise ProvenanceError(f"{relative}: invalid gzip payload: {error}") from error
        records = _records_from_payload(uncompressed, path)
        records_by_table[table] = records
        rows, logical_sha256 = digest_records(records)
        proof = manifest.tables[table]
        _require_equal(f"manifest.tables.{table}.rows", proof.rows, rows)
        _require_equal(f"manifest.tables.{table}.sha256", proof.sha256, logical_sha256)
        files.append(
            {
                "compressed_sha256": _sha256_bytes(compressed),
                "logical_records_sha256": logical_sha256,
                "path": relative,
                "rows": rows,
                "size_bytes": len(compressed),
                "table": table,
                "uncompressed_sha256": _sha256_bytes(uncompressed),
            }
        )
    manifest_sha256 = _file_sha256(manifest_path)
    expected_results = _load_object(expected_path)
    _require_keys("expected_results", expected_results, {"gross_cents", "orders"})
    orders = records_by_table["orders"]
    calculated_expected_results = {
        "gross_cents": sum(int(order["total_cents"]) for order in orders),
        "orders": len(orders),
    }
    _require_equal("expected_results", expected_results, calculated_expected_results)
    expected_results_sha256 = _file_sha256(expected_path)
    bundle_content_sha256 = digest(
        {
            "expected_results_sha256": expected_results_sha256,
            "files": files,
            "manifest_sha256": manifest_sha256,
        }
    )
    payload: dict[str, Any] = {
        "batch_id": batch_id,
        "bundle_content_sha256": bundle_content_sha256,
        "contract_sha256": catalog_result.contract_sha256,
        "expected_results_sha256": expected_results_sha256,
        "files": files,
        "generator": {
            "canonical_json": "UTF8_SORTED_COMPACT_NDJSON_LF",
            "compression": "GZIP_LEVEL_9_MTIME_0_NO_FILENAME_OS_255",
            "format_version": FORMAT_VERSION,
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "zlib_version": zlib.ZLIB_RUNTIME_VERSION,
        },
        "managed_manifest_schema_sha256": managed_schema_sha256,
        "manifest_sha256": manifest_sha256,
        "parameters": parameters,
        "provenance_schema_sha256": _file_sha256(repo_root / PROVENANCE_SCHEMA_RELATIVE_PATH),
        "repository": REPOSITORY,
        "source_manifest_schema_sha256": source_schema_sha256,
        "scenario_catalog_sha256": catalog_result.catalog_sha256,
        "schema_version": "1.0",
        "source_commit": source_commit,
        "source_family": source_family,
        "target_sha256": catalog_result.target_sha256,
    }
    return {**payload, "receipt_sha256": digest(payload)}


def verify_receipt(
    receipt: dict[str, Any],
    *,
    directory: Path,
    repo_root: Path,
    catalog: dict[str, Any],
) -> None:
    required = {
        "batch_id",
        "bundle_content_sha256",
        "contract_sha256",
        "expected_results_sha256",
        "files",
        "generator",
        "managed_manifest_schema_sha256",
        "manifest_sha256",
        "parameters",
        "provenance_schema_sha256",
        "receipt_sha256",
        "repository",
        "source_manifest_schema_sha256",
        "scenario_catalog_sha256",
        "schema_version",
        "source_commit",
        "source_family",
        "target_sha256",
    }
    _require_keys("receipt", receipt, required)
    supplied_digest = receipt["receipt_sha256"]
    if not isinstance(supplied_digest, str) or not SHA256_PATTERN.fullmatch(supplied_digest):
        _fail("receipt.receipt_sha256", supplied_digest, "lowercase SHA-256")
    identity_payload = dict(receipt)
    identity_payload.pop("receipt_sha256")
    _require_equal("receipt.receipt_sha256", supplied_digest, digest(identity_payload))
    source_family = receipt["source_family"]
    if source_family not in SOURCE_FAMILIES:
        _fail("receipt.source_family", source_family, sorted(SOURCE_FAMILIES))
    parameters = receipt["parameters"]
    if not isinstance(parameters, dict):
        _fail("receipt.parameters", type(parameters).__name__, "JSON object")
    _validate_parameters(parameters, source_family=str(source_family), catalog=catalog)
    rebuilt = build_receipt(
        directory,
        repo_root=repo_root,
        source_commit=str(receipt["source_commit"]),
        source_family=str(source_family),
        batch_id=str(receipt["batch_id"]),
        parameters=parameters,
        catalog=catalog,
    )
    _require_equal("receipt", receipt, rebuilt)


def build_tamper_mutation_receipt(
    directory: Path, *, source_receipt: dict[str, Any], catalog_sha256: str
) -> dict[str, Any]:
    """Create evidence for the one declared post-registration object mutation."""

    order_files = [item for item in source_receipt["files"] if item["table"] == "orders"]
    _require_equal("tamper.orders_source_count", len(order_files), 1)
    original = order_files[0]
    replacement_path = directory / "tamper-replacement.bin"
    _write_bytes_atomic(replacement_path, TAMPER_REPLACEMENT)
    payload = {
        "catalog_sha256": catalog_sha256,
        "expected_failure_signal": "QUALITY_GATE:OBJECT_IDENTITY",
        "mutation": "REPLACE_ONE_REGISTERED_S3_OBJECT_VERSION_BYTES",
        "original_compressed_sha256": original["compressed_sha256"],
        "original_path": original["path"],
        "replacement_path": replacement_path.relative_to(directory).as_posix(),
        "replacement_sha256": _sha256_bytes(TAMPER_REPLACEMENT),
        "replacement_size_bytes": len(TAMPER_REPLACEMENT),
        "schema_version": "1.0",
        "source_bundle_content_sha256": source_receipt["bundle_content_sha256"],
        "unchanged_source_file_count": len(source_receipt["files"]) - 1,
    }
    return {**payload, "mutation_receipt_sha256": digest(payload)}


def verify_tamper_mutation_receipt(
    directory: Path,
    *,
    mutation_receipt: dict[str, Any],
    source_receipt: dict[str, Any],
    catalog_sha256: str,
) -> None:
    required = {
        "catalog_sha256",
        "expected_failure_signal",
        "mutation",
        "mutation_receipt_sha256",
        "original_compressed_sha256",
        "original_path",
        "replacement_path",
        "replacement_sha256",
        "replacement_size_bytes",
        "schema_version",
        "source_bundle_content_sha256",
        "unchanged_source_file_count",
    }
    _require_keys("tamper_mutation", mutation_receipt, required)
    supplied = mutation_receipt["mutation_receipt_sha256"]
    payload = dict(mutation_receipt)
    payload.pop("mutation_receipt_sha256")
    _require_equal("tamper_mutation.mutation_receipt_sha256", supplied, digest(payload))
    _require_equal(
        "tamper_mutation.catalog_sha256", mutation_receipt["catalog_sha256"], catalog_sha256
    )
    _require_equal(
        "tamper_mutation.expected_failure_signal",
        mutation_receipt["expected_failure_signal"],
        "QUALITY_GATE:OBJECT_IDENTITY",
    )
    _require_equal(
        "tamper_mutation.mutation",
        mutation_receipt["mutation"],
        "REPLACE_ONE_REGISTERED_S3_OBJECT_VERSION_BYTES",
    )
    _require_equal(
        "tamper_mutation.source_bundle_content_sha256",
        mutation_receipt["source_bundle_content_sha256"],
        source_receipt["bundle_content_sha256"],
    )
    order_files = [item for item in source_receipt["files"] if item["table"] == "orders"]
    _require_equal("tamper_mutation.orders_source_count", len(order_files), 1)
    original = order_files[0]
    _require_equal(
        "tamper_mutation.original_path", mutation_receipt["original_path"], original["path"]
    )
    _require_equal(
        "tamper_mutation.original_compressed_sha256",
        mutation_receipt["original_compressed_sha256"],
        original["compressed_sha256"],
    )
    replacement_path = directory / str(mutation_receipt["replacement_path"])
    if replacement_path.is_symlink() or replacement_path.parent != directory:
        _fail("tamper_mutation.replacement_path", replacement_path, "direct regular child")
    replacement = replacement_path.read_bytes()
    _require_equal(
        "tamper_mutation.replacement_sha256",
        mutation_receipt["replacement_sha256"],
        _sha256_bytes(replacement),
    )
    _require_equal(
        "tamper_mutation.replacement_size_bytes",
        mutation_receipt["replacement_size_bytes"],
        len(replacement),
    )
    if mutation_receipt["replacement_sha256"] == mutation_receipt["original_compressed_sha256"]:
        _fail(
            "tamper_mutation.replacement_sha256",
            mutation_receipt["replacement_sha256"],
            "changed bytes",
        )
    _require_equal(
        "tamper_mutation.unchanged_source_file_count",
        mutation_receipt["unchanged_source_file_count"],
        len(source_receipt["files"]) - 1,
    )


def verify_materialized_sources(output: Path, *, repo_root: Path) -> dict[str, Any]:
    """Independently validate a complete materialized source directory and its summary."""

    catalog = _load_object(repo_root / CATALOG_RELATIVE_PATH)
    catalog_result = validate_catalog(catalog, repo_root=repo_root)
    validate_provenance_schema_file(repo_root / PROVENANCE_SCHEMA_RELATIVE_PATH)
    receipts: dict[str, dict[str, str]] = {}
    order_counts: set[int] = set()
    source_commits: set[str] = set()
    expected_directories = {
        str(specification["batch_prefix"]) for specification in catalog["source_families"].values()
    }
    observed_directories = {path.name for path in output.iterdir() if path.is_dir()}
    _require_equal("sources.directories", observed_directories, expected_directories)
    observed_root_files = {path.name for path in output.iterdir() if path.is_file()}
    _require_equal("sources.root_files", observed_root_files, {"source-provenance-summary.json"})
    for family in sorted(SOURCE_FAMILIES):
        specification = catalog["source_families"][family]
        directory = output / specification["batch_prefix"]
        receipt_path = directory / "source-provenance.json"
        receipt = _load_object(receipt_path)
        _require_equal(f"receipt.{family}.source_family", receipt.get("source_family"), family)
        parameters = receipt.get("parameters")
        if not isinstance(parameters, dict):
            _fail(f"receipt.{family}.parameters", type(parameters).__name__, "JSON object")
        _require_equal(
            f"receipt.{family}.parameters",
            parameters,
            {
                "as_of_knowledge_time": specification["as_of_knowledge_time"],
                "fault": specification["fault"],
                "order_count": parameters.get("order_count"),
                "produced_at": specification["produced_at"],
                "seed": specification["seed"],
            },
        )
        order_count = validate_order_count(parameters.get("order_count"))
        order_counts.add(order_count)
        source_commit = receipt.get("source_commit")
        if not isinstance(source_commit, str):
            _fail(f"receipt.{family}.source_commit", source_commit, "commit SHA")
        source_commits.add(source_commit)
        verify_receipt(receipt, directory=directory, repo_root=repo_root, catalog=catalog)
        expected_files = {
            "expected-results.json",
            "manifest.json",
            "source-provenance.json",
            *(str(item["path"]) for item in receipt["files"]),
        }
        if family == "tamper":
            expected_files.update({"tamper-mutation.json", "tamper-replacement.bin"})
        observed_files = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        _require_equal(f"sources.{family}.files", observed_files, expected_files)
        receipt_summary = {
            "batch_id": str(receipt["batch_id"]),
            "bundle_content_sha256": str(receipt["bundle_content_sha256"]),
            "receipt_sha256": str(receipt["receipt_sha256"]),
        }
        if family == "tamper":
            mutation_receipt = _load_object(directory / "tamper-mutation.json")
            verify_tamper_mutation_receipt(
                directory,
                mutation_receipt=mutation_receipt,
                source_receipt=receipt,
                catalog_sha256=catalog_result.catalog_sha256,
            )
            receipt_summary["mutation_receipt_sha256"] = str(
                mutation_receipt["mutation_receipt_sha256"]
            )
        receipts[family] = receipt_summary
    _require_equal("sources.order_counts", len(order_counts), 1)
    _require_equal("sources.source_commits", len(source_commits), 1)
    summary = _load_object(output / "source-provenance-summary.json")
    supplied_summary_sha256 = summary.get("summary_sha256")
    payload = dict(summary)
    payload.pop("summary_sha256", None)
    _require_equal("summary.summary_sha256", supplied_summary_sha256, digest(payload))
    _require_equal(
        "summary.catalog_sha256", summary.get("catalog_sha256"), catalog_result.catalog_sha256
    )
    _require_equal(
        "summary.contract_sha256", summary.get("contract_sha256"), catalog_result.contract_sha256
    )
    _require_equal(
        "summary.target_sha256", summary.get("target_sha256"), catalog_result.target_sha256
    )
    _require_equal("summary.receipts", summary.get("receipts"), receipts)
    _require_equal("summary.order_count", summary.get("order_count"), next(iter(order_counts)))
    _require_equal(
        "summary.source_commit", summary.get("source_commit"), next(iter(source_commits))
    )
    return summary


def materialize_part4_sources(
    output: Path,
    *,
    repo_root: Path,
    order_count: int,
    source_commit: str,
    run_id: str,
) -> dict[str, Any]:
    """Materialize and validate all physical Part 4 source families."""

    validate_order_count(order_count)
    if not COMMIT_PATTERN.fullmatch(source_commit):
        _fail("source_commit", source_commit, "40-character lowercase commit SHA")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
        _fail("run_id", run_id, "safe run identifier")
    catalog_path = repo_root / CATALOG_RELATIVE_PATH
    catalog = _load_object(catalog_path)
    catalog_result = validate_catalog(catalog, repo_root=repo_root)
    receipts: dict[str, dict[str, str]] = {}
    for family in sorted(SOURCE_FAMILIES):
        specification = catalog["source_families"][family]
        batch_id = f"{specification['batch_prefix']}-{run_id}"
        directory = output / specification["batch_prefix"]
        parameters: dict[str, object] = {
            "as_of_knowledge_time": specification["as_of_knowledge_time"],
            "fault": specification["fault"],
            "order_count": order_count,
            "produced_at": specification["produced_at"],
            "seed": specification["seed"],
        }
        generate_source_data(
            directory,
            orders=order_count,
            seed=specification["seed"],
            batch_id=batch_id,
            fault=specification["fault"],
            produced_at=specification["produced_at"],
            as_of_knowledge_time=specification["as_of_knowledge_time"],
        )
        receipt = build_receipt(
            directory,
            repo_root=repo_root,
            source_commit=source_commit,
            source_family=family,
            batch_id=batch_id,
            parameters=parameters,
            catalog=catalog,
        )
        verify_receipt(
            receipt,
            directory=directory,
            repo_root=repo_root,
            catalog=catalog,
        )
        _write_json(directory / "source-provenance.json", receipt)
        receipt_summary = {
            "batch_id": batch_id,
            "bundle_content_sha256": receipt["bundle_content_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
        }
        if family == "tamper":
            mutation_receipt = build_tamper_mutation_receipt(
                directory,
                source_receipt=receipt,
                catalog_sha256=catalog_result.catalog_sha256,
            )
            verify_tamper_mutation_receipt(
                directory,
                mutation_receipt=mutation_receipt,
                source_receipt=receipt,
                catalog_sha256=catalog_result.catalog_sha256,
            )
            _write_json(directory / "tamper-mutation.json", mutation_receipt)
            receipt_summary["mutation_receipt_sha256"] = mutation_receipt["mutation_receipt_sha256"]
        receipts[family] = receipt_summary
    summary_payload: dict[str, Any] = {
        **catalog_result.to_dict(),
        "order_count": order_count,
        "receipts": receipts,
        "source_commit": source_commit,
    }
    summary = {**summary_payload, "summary_sha256": digest(summary_payload)}
    _write_json(output / "source-provenance-summary.json", summary)
    return verify_materialized_sources(output, repo_root=repo_root)
