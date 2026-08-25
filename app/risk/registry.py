# Model registry — filesystem-backed, strict validation
import json
from pathlib import Path

import numpy as np
from xgboost import XGBClassifier

from app.config import get_settings


class RegistryError(RuntimeError):
    pass

def _load_metadata(model_dir: Path, version: str) -> dict:
    meta_path = model_dir / f"{version}.metadata.json"
    if not meta_path.exists():
        raise RegistryError(f"metadata missing for version {version} at {meta_path}")
    return json.load(open(meta_path))

def _load_features(model_dir: Path, version: str) -> list[str]:
    feat_path = model_dir / f"{version}.features.json"
    if feat_path.exists():
        return json.load(open(feat_path))
    # fallback to metadata
    meta = _load_metadata(model_dir, version)
    return meta["feature_names"]

def load_model(version: str = "latest", model_dir: Path | None = None) -> tuple[XGBClassifier, dict, list[str]]:
    settings = get_settings()
    md = model_dir or settings.model_dir
    if not md.exists():
        raise RegistryError(f"model_dir not found: {md}")
    # resolve version
    model_path = md / f"{version}.json"
    if not model_path.exists():
        raise RegistryError(f"model artifact missing for version {version} at {model_path}")
    meta = _load_metadata(md, version)
    features = _load_features(md, version)
    # validate feature contract
    if len(features) != meta["feature_count"]:
        raise RegistryError(f"feature count mismatch: {len(features)} vs {meta['feature_count']}")
    if features != meta["feature_names"]:
        raise RegistryError("feature ordering mismatch between sidecar and metadata")
    # banned check
    banned = ("tx_prior", "_prior_mean", "distinct_dev_prior", "distinct_card_prior")
    for n in features:
        for b in banned:
            if b in n:
                raise RegistryError(f"banned feature in artifact: {n}")
    # load xgboost
    clf = XGBClassifier()
    clf.load_model(str(model_path))
    # validate expected count via booster
    booster_n = clf.n_features_in_ if hasattr(clf, "n_features_in_") else len(features)
    if booster_n != len(features):
        raise RegistryError(f"booster feature count {booster_n} != manifest {len(features)}")
    return clf, meta, features

def latest_version(model_dir: Path | None = None) -> str:
    settings = get_settings()
    md = model_dir or settings.model_dir
    # read latest metadata
    meta = _load_metadata(md, "latest")
    return meta["model_version"]

def validate_feature_matrix(X: np.ndarray, expected_features: list[str]) -> None:
    if X.shape[1] != len(expected_features):
        raise RegistryError(f"feature count mismatch: got {X.shape[1]} expected {len(expected_features)}")
    # ordering is caller's responsibility; we just check count here
