# Centralized canonicalization and hashing
import hashlib
import json


def canonicalize(payload: dict) -> str:
    """Deterministic JSON canonical form."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

def evidence_hash(canonical_payload: dict) -> str:
    """SHA256 of canonical payload (must exclude generated_at)."""
    canon = canonicalize(canonical_payload)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()

def canonical_evidence_payload(record: dict) -> dict:
    """Extract canonical payload by removing runtime fields and hash itself."""
    # exclude generated_at and any runtime metadata plus evidence_hash (to avoid circular)
    excluded = {"generated_at", "request_id", "host", "latency", "evidence_hash"}
    return {k: v for k, v in record.items() if k not in excluded}
