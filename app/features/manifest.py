# Feature manifest generation/validation.
# The manifest is the single source of truth for what the model sees. control_status per family is injected from shuffled-control gate results once the gate experiment has run.

import json
from pathlib import Path

from app.features.contract import FEATURE_REGISTRY, validate_manifest_alignment


def build_manifest(gate_results: dict | None = None) -> list[dict]:
    gate_results = gate_results or {}
    manifest = []
    for spec in FEATURE_REGISTRY:
        family_result = gate_results.get(spec.family, {})
        control_status = family_result.get(
            "gate", spec.control_status if family_result else "PENDING")
        manifest.append({
            "name": spec.name,
            "family": spec.family,
            "source_entities": list(spec.source_entities),
            "partner_entities": list(spec.partner_entities),
            "window": spec.window,
            "aggregation": spec.aggregation,
            "cutoff_rule": spec.cutoff_rule,
            "training_only": spec.training_only,
            "inference_safe": spec.inference_safe,
            "missing_value_policy": spec.missing_value_policy,
            "rationale": spec.rationale,
            "control_status": control_status,
            "included_in_model": bool(control_status == "PASS"),
        })
    validate_manifest_alignment(manifest)
    return manifest


def save_manifest(path: Path, gate_results: dict | None = None) -> list[dict]:
    manifest = build_manifest(gate_results)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"features": manifest}, f, indent=1)
    return manifest


def load_manifest(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["features"]


def assert_no_banned_features(manifest: list[dict]) -> None:
    banned_markers = ("tx_prior", "_prior_mean", "distinct_dev_prior",
                      "distinct_card_prior", "distinct_addr_prior")
    for m in manifest:
        for marker in banned_markers:
            assert marker not in m["name"], \
                f"banned cumulative feature in manifest: {m['name']}"


def included_features(manifest: list[dict]) -> list[str]:
    return [m["name"] for m in manifest
            if m["included_in_model"] and m["control_status"] == "PASS"]
