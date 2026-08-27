# Central configuration: paths, seeds, split fractions, experiment rules
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- raw data
IEEE_DIR = ROOT / "IEEE-CIS Fraud Detection"
IEEE_TXN_CSV = IEEE_DIR / "train_transaction.csv"
IEEE_IDN_CSV = IEEE_DIR / "train_identity.csv"

SIM_DIR = ROOT / "Fraud-Detection-Handbook" / "simulated-data-raw-main" / "data"

# ------------------------------------------------------- processed / cache
DATA_PROC = ROOT / "data" / "processed"
DATA_SYNTH = ROOT / "data" / "synthetic"
TXN_PARQUET = DATA_PROC / "ieee_train_transaction.parquet"
IDN_PARQUET = DATA_PROC / "ieee_train_identity.parquet"
SIM_PARQUET = DATA_PROC / "simulated_transactions.parquet"

REPORTS = ROOT / "reports"
EXPERIMENTS = ROOT / "experiments"

RESOURCE_LOG = REPORTS / "resource_log.jsonl"

# ------------------------------------------------------------------ random
SEED = 42

# --------------------------------------------- temporal split (chronological)
TRAIN_FRACTION = 0.70
VALID_FRACTION = 0.15
TEST_FRACTION = 0.15

# ------------------------------------------------ experiment slice
SLICE_SIZE = 100_000          # first working experiment: 100k transactions
