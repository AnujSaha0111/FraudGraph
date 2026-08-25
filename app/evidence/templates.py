# Evidence eligibility rules and thresholds (machine-readable registry)
from dataclasses import dataclass

EVIDENCE_ENGINE_VERSION = "v1"

# Thresholds — documented, not arbitrary
AMOUNT_Z_THRESHOLD = 2.0  # |z| >=2 considered deviation
HOUR_DEV_THRESHOLD = 0.35  # circular distance /pi >=0.35 (~8.4h away)
VELOCITY_THRESHOLDS = {
    "card_tx_1h": 3,
    "card_tx_24h": 8,
    "dev_tx_1h": 3,
    "dev_tx_24h": 8,
}
SHARED_DEVICE_MIN_TXNS = 2  # at least 2 other txns share device
COMMUNITY_MIN_TXNS = 3  # at least 3 txns to be reportable community
CONNECTED_HIGH_RISK_THRESHOLD = 0.6  # risk_score >=0.6 considered high (HIGH band)

@dataclass(frozen=True)
class TemplateRule:
    evidence_type: str
    required_inputs: tuple[str, ...]
    threshold_desc: str
    output_fields: tuple[str, ...]

REGISTRY: dict[str, TemplateRule] = {
    "NEW_PAIRING": TemplateRule("NEW_PAIRING", ("device_key","card_key","pair_history"), "is_new_device_card_pair==1 or is_new_addr_card_pair==1", ("entity_type","entity_key","pair_type")),
    "AMOUNT_DEVIATION": TemplateRule("AMOUNT_DEVIATION", ("amt_z_card","amt_z_device","TransactionAmt"), f"|z| >= {AMOUNT_Z_THRESHOLD}", ("z_score","current_amount","reference_entity","history_window")),
    "UNUSUAL_HOUR": TemplateRule("UNUSUAL_HOUR", ("hour_dev_card","hour_dev_device"), f"hour_dev >= {HOUR_DEV_THRESHOLD}", ("hour_dev","transaction_hour","reference_entity")),
    "VELOCITY_BURST": TemplateRule("VELOCITY_BURST", ("window_counts",), "count >= threshold per window", ("entity","window","count","threshold")),
    "SHARED_DEVICE_LINK": TemplateRule("SHARED_DEVICE_LINK", ("device_key","graph_neighbors"), f"device exists and >= {SHARED_DEVICE_MIN_TXNS} other txns", ("device","connected_txns","window")),
    "COMMUNITY_STATS": TemplateRule("COMMUNITY_STATS", ("community_summary",), f"community transaction_count >= {COMMUNITY_MIN_TXNS}", ("transaction_count","entity_count","time_span")),
    "CONNECTED_HIGH_RISK": TemplateRule("CONNECTED_HIGH_RISK", ("connected_scores",), f"risk_score >= {CONNECTED_HIGH_RISK_THRESHOLD}", ("connected_transaction","risk_score","risk_band")),
}
