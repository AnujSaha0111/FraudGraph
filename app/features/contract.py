# Canonical feature-input contract and production feature registry.
# TRAINING_ONLY columns must never reach feature generation at inference. All relational features are computed strictly from events BEFORE the row's timestamp (half-open windows [t-W, t)); ties at exactly t are NOT prior.

from dataclasses import dataclass

TRAINING_ONLY = ["isFraud"]
INFERENCE_SAFE_PREFIXES: tuple[str, ...] = ()  # everything except TRAINING_ONLY

CANONICAL_COLUMNS = {
    "transaction_id": "txn_id",
    "timestamp": "ts",
    "amount": "amount",
    "hour": "hour_of_day",
    "entities": {
        "card": "card_key",
        "device": "device_key",
        "address": "addr_key",
    },
}


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    family: str
    source_entities: tuple[str, ...]
    partner_entities: tuple[str, ...] = ()
    window: str | None = None            # e.g. "[t-24h, t)" ; None = expanding-prior-only
    aggregation: str = ""
    cutoff_rule: str = "strictly_before_t"
    training_only: bool = False
    inference_safe: bool = True
    missing_value_policy: str = ""
    rationale: str = ""
    control_status: str = "PENDING"      # PENDING | PASS | FAIL
    included_in_model: bool = False


def _f(**kw) -> FeatureSpec:
    kw.setdefault("missing_value_policy", "NaN (XGBoost-native missing)")
    return FeatureSpec(**kw)


HISTORY_DEVIATION = [
    _f(name="amt_z_card", family="history_deviation",
       source_entities=("card",),
       aggregation="welford_zscore_vs_prior_amount_distribution",
       missing_value_policy="NaN when entity missing or prior_count < 2 "
                            "(no variance estimate)",
       rationale="Amount far outside the card's own history is a strong "
                 "behavioral-deviation signal (validated round-2 family)."),
    _f(name="amt_z_device", family="history_deviation",
       source_entities=("device",),
       aggregation="welford_zscore_vs_prior_amount_distribution",
       missing_value_policy="NaN when device absent or prior_count < 2",
       rationale="Same deviation logic for shared/mule devices."),
    _f(name="hour_dev_card", family="history_deviation",
       source_entities=("card",),
       aggregation="circular_distance_to_prior_hour_distribution",
       missing_value_policy="NaN when entity missing or prior_count == 0",
       rationale="Transactions at unusual hours for this card."),
    _f(name="hour_dev_device", family="history_deviation",
       source_entities=("device",),
       aggregation="circular_distance_to_prior_hour_distribution",
       missing_value_policy="NaN when device absent or prior_count == 0",
       rationale="Transactions at unusual hours for this device."),
]

RECENCY = [
    _f(name="hours_since_last_card", family="recency",
       source_entities=("card",),
       aggregation="hours_since_previous_event",
       missing_value_policy="NaN when entity missing or never seen before",
       rationale="Dormancy break / rapid reuse context."),
    _f(name="hours_since_last_device", family="recency",
       source_entities=("device",),
       aggregation="hours_since_previous_event",
       missing_value_policy="NaN when device absent or never seen before",
       rationale="Dormancy break / rapid reuse context."),
]

NOVELTY = [
    _f(name="is_new_device_card_pair", family="novelty",
       source_entities=("device", "card"), partner_entities=("card",),
       aggregation="binary first_observation_of_pair_strictly_before_t",
       missing_value_policy="NaN when either entity missing",
       rationale="New device-card pairing is classic mule/CNP signal."),
    _f(name="is_new_addr_card_pair", family="novelty",
       source_entities=("address", "card"), partner_entities=("card",),
       aggregation="binary first_observation_of_pair_strictly_before_t",
       missing_value_policy="NaN when either entity missing",
       rationale="Card appearing behind a previously unseen billing address."),
    _f(name="log_pair_count_device_card", family="novelty",
       source_entities=("device", "card"), partner_entities=("card",),
       aggregation="log1p(prior co-occurrence count)",
       missing_value_policy="NaN when either entity missing",
       rationale="Continuum between brand-new and established pairing."),
]

VELOCITY_WINDOWED = [
    _f(name=f"card_tx_{lbl}", family="velocity_windowed",
       source_entities=("card",), window=f"[t-{lbl}, t)",
       aggregation="count_of_prior_transactions_in_window",
       rationale="Short-window velocity without cumulative components.")
    for lbl in ("1h", "24h")
] + [
    _f(name=f"dev_tx_{lbl}", family="velocity_windowed",
       source_entities=("device",), window=f"[t-{lbl}, t)",
       aggregation="count_of_prior_transactions_in_window",
       missing_value_policy="NaN when device absent",
       rationale="Device-side burst pressure.")
    for lbl in ("1h", "24h")
]

WINDOWED_DISTINCT_PARTNERS = [
    _f(name="device_distinct_cards_24h", family="windowed_distinct_partners",
       source_entities=("device",), partner_entities=("card",),
       window="[t-24h, t)", aggregation="n_distinct_partner_cards",
       rationale="One device transacting across many cards within a day."),
    _f(name="card_distinct_devices_24h", family="windowed_distinct_partners",
       source_entities=("card",), partner_entities=("device",),
       window="[t-24h, t)", aggregation="n_distinct_partner_devices",
       rationale="One card appearing across many devices within a day."),
    _f(name="addr_distinct_cards_7d", family="windowed_distinct_partners",
       source_entities=("address",), partner_entities=("card",),
       window="[t-168h, t)", aggregation="n_distinct_partner_cards",
       rationale="Address funneling multiple cards within a week."),
]

FEATURE_REGISTRY: list[FeatureSpec] = (
    HISTORY_DEVIATION + RECENCY + NOVELTY +
    VELOCITY_WINDOWED + WINDOWED_DISTINCT_PARTNERS
)

FAMILIES: dict[str, list[str]] = {}
for _spec in FEATURE_REGISTRY:
    FAMILIES.setdefault(_spec.family, []).append(_spec.name)

FEATURE_NAMES = [s.name for s in FEATURE_REGISTRY]


@dataclass(frozen=True)
class RelationalInputColumns:
    """Column names the causal engine expects in its input frame."""

    ts: str = "ts"
    amount: str = "amount"
    card: str = "card_key"
    device: str = "device_key"
    address: str = "addr_key"


def validate_manifest_alignment(manifest: list[dict]) -> None:
    """Manifest must mirror the registry one-to-one."""
    reg_names = [s.name for s in FEATURE_REGISTRY]
    man_names = [m["name"] for m in manifest]
    assert reg_names == man_names, (
        f"registry/manifest mismatch: {set(reg_names) ^ set(man_names)}")
