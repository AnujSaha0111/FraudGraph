# Risk score bands — deterministic, config-driven, not calibrated probabilities
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskBands:
    low: float = 0.3
    medium: float = 0.6
    high: float = 0.85

    def band(self, score: float) -> str:
        if score >= self.high:
            return "CRITICAL"
        if score >= self.medium:
            return "HIGH"
        if score >= self.low:
            return "MEDIUM"
        return "LOW"

DEFAULT_BANDS = RiskBands()
