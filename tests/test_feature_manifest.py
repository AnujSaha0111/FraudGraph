from app.features.contract import FAMILIES, FEATURE_REGISTRY
from app.features.manifest import assert_no_banned_features, build_manifest, included_features


def test_manifest_mirrors_registry():
    manifest = build_manifest({})
    assert [m["name"] for m in manifest] == \
        [s.name for s in FEATURE_REGISTRY]
    assert set(FAMILIES) == {m["family"] for m in manifest}


def test_manifest_required_fields_present():
    required = {"name", "family", "source_entities", "partner_entities",
                "window", "aggregation", "cutoff_rule", "training_only",
                "inference_safe", "missing_value_policy", "rationale",
                "control_status", "included_in_model"}
    for m in build_manifest({}):
        missing = required - set(m)
        assert not missing, f"{m['name']} missing {missing}"
        assert m["training_only"] is False
        assert m["inference_safe"] is True
        assert m["cutoff_rule"] == "strictly_before_t"


def test_gate_results_drive_inclusion():
    gate = {
        "history_deviation": {"gate": "PASS"},
        "novelty": {"gate": "PASS"},
        "velocity_windowed": {"gate": "FAIL"},
        "windowed_distinct_partners": {"gate": "PASS"},
    }
    manifest = build_manifest(gate)
    incl = set(included_features(manifest))
    assert "amt_z_card" in incl                    # PASS family
    assert "is_new_device_card_pair" in incl       # PASS family
    assert "card_tx_24h" not in incl               # FAIL family excluded
    for m in manifest:
        if m["family"] == "velocity_windowed":
            assert m["included_in_model"] is False


def test_banned_cumulative_features_absent():
    manifest = build_manifest({})
    assert_no_banned_features(manifest)   # raises if any tx_prior/*_prior_mean


def test_all_windows_half_open_notation():
    for s in FEATURE_REGISTRY:
        if s.window is not None:
            assert s.window.startswith("[t-") and s.window.endswith(", t)")
