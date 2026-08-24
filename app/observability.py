# Minimal structured logging (§24).

# JSON lines for: scoring, graph expansion, evidence generation, case actions, failures. Never logs raw feature vectors or transaction payloads — only IDs, hashes, derived metrics.

import json
import time
from typing import Any


def log(event: str, **fields: Any) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
    # Ensure no raw payload leakage: drop large vectors if accidentally passed
    for k in list(record.keys()):
        if k in {"X", "x_row", "feature_vector", "payload"}:
            record[k] = "[redacted]"
    print(json.dumps(record), flush=True)
