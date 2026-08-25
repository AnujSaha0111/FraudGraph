# EvidenceRecord schema
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

EVIDENCE_ENGINE_VERSION = "v1"

ALLOWED_TYPES = {
    "NEW_PAIRING",
    "AMOUNT_DEVIATION",
    "UNUSUAL_HOUR",
    "VELOCITY_BURST",
    "SHARED_DEVICE_LINK",
    "COMMUNITY_STATS",
    "CONNECTED_HIGH_RISK",
    "NO_RELATIONAL_EVIDENCE",
}

@dataclass
class EvidenceRecord:
    evidence_id: str
    transaction_id: int
    evidence_type: str
    title: str
    description: str
    details: dict[str, Any]
    severity: str | None  # e.g., "info","low","medium","high"
    provenance: dict[str, Any]  # source_table, source_row_ids, code_version
    evidence_hash: str
    generated_at: str  # ISO8601, runtime-only excluded from hash

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def new(transaction_id: int, evidence_type: str, title: str, description: str,
            details: dict, provenance: dict, severity: str | None = None) -> "EvidenceRecord":
        assert evidence_type in ALLOWED_TYPES, f"invalid type {evidence_type}"
        # Deterministic evidence_id via uuid5 (so hash is deterministic)

        from app.evidence.canonical import canonicalize
        seed_payload = {
            "transaction_id": transaction_id,
            "evidence_type": evidence_type,
            "title": title,
            "description": description,
            "details": details,
            "severity": severity,
            "provenance": provenance,
        }
        # deterministic uuid5 from canonical seed
        canon_seed = canonicalize(seed_payload)
        eid = str(uuid.uuid5(uuid.NAMESPACE_URL, canon_seed))
        payload = {
            "evidence_id": eid,
            "transaction_id": transaction_id,
            "evidence_type": evidence_type,
            "title": title,
            "description": description,
            "details": details,
            "severity": severity,
            "provenance": provenance,
        }
        from app.evidence.canonical import evidence_hash as eh
        h = eh(payload)
        return EvidenceRecord(
            evidence_id=eid,
            transaction_id=transaction_id,
            evidence_type=evidence_type,
            title=title,
            description=description,
            details=details,
            severity=severity,
            provenance=provenance,
            evidence_hash=h,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def canonical_payload(self) -> dict:
        d = self.to_dict()
        d.pop("generated_at", None)
        d.pop("evidence_hash", None)
        return d

    def recomputed_hash(self) -> str:
        from app.evidence.canonical import evidence_hash as eh
        return eh(self.canonical_payload())
