# Risk scorer — pure python, no HTTP
from dataclasses import dataclass

import numpy as np

from app.risk.config import DEFAULT_BANDS, RiskBands
from app.risk.registry import load_model, validate_feature_matrix


@dataclass(frozen=True)
class ScoreResult:
    transaction_id: int
    risk_score: float
    risk_band: str
    model_version: str

class RiskScorer:
    def __init__(self, version: str = "latest", model_dir=None, bands: RiskBands | None = None):
        self.clf, self.meta, self.feature_names = load_model(version, model_dir)
        self.bands = bands or DEFAULT_BANDS
        self.model_version = self.meta["model_version"]

    def score_matrix(self, X: np.ndarray) -> np.ndarray:
        validate_feature_matrix(X, self.feature_names)
        return self.clf.predict_proba(X)[:, 1].astype(float)

    def score_row(self, x_row: np.ndarray, transaction_id: int) -> ScoreResult:
        X = x_row.reshape(1, -1)
        s = float(self.score_matrix(X)[0])
        # clamp
        s = max(0.0, min(1.0, s))
        return ScoreResult(transaction_id=transaction_id, risk_score=s, risk_band=self.bands.band(s), model_version=self.model_version)

    def band(self, score: float) -> str:
        return self.bands.band(score)
