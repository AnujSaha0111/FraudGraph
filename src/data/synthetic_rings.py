# Synthetic coordinated-abuse benchmark generator (data/synthetic/).
# Background population: independent customers (own device + instrument), Poisson transaction streams over 90 days at shared terminals/merchants.
# Planted rings (ground-truth membership saved):
# - Ring A: 5 accounts, 2 shared devices, 3 instruments, 2 merchants, 20 txns inside a 48h burst
# - Ring B: 10 accounts, 3 shared devices, 5 instruments, 4 merchants, ~80 txns across 7 days
# - Ring C: 20 accounts, 5 shared devices, 8 instruments, 6 merchants, ~240 txns across 14 days, staggered bursts
# Realism knobs (prevent trivial recovery):
# - 2% of BACKGROUND accounts share a household device with one neighbor
# - ring members keep using personal instruments for normal purchases too
# - Ring C contains one 'bridge' member who ALSO touches Ring B's device (tests whether components fuse)
# Raw datasets are never modified; output goes to data/synthetic/.

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import DATA_SYNTH, SEED

N_CUST = 3000
N_TERM = 800
N_MERCH = 120
DAYS = 90


def generate(seed=SEED):
    rng = np.random.default_rng(seed)
    rows = []
    labels = []          # ring id or -1
    acct_of = []
    dev_of, inst_of = [], []

    cust_dev = {}
    cust_inst = {}
    cust_addr = {}
    # background households: pair 2% of customers onto shared devices
    shared_pairs = {}
    for c in range(N_CUST):
        d = f"D{c:05d}"
        i = f"I{c:05d}"
        cust_dev[c] = [d]
        cust_inst[c] = [i]
        cust_addr[c] = f"A{rng.integers(0, 200):03d}"
    victims = rng.choice(N_CUST, size=int(N_CUST * 0.02), replace=False)
    for v in victims:
        nb = int(rng.integers(0, N_CUST))
        if nb == v:
            continue
        shared = f"HH{v:05d}"
        cust_dev[v] = [shared] + cust_dev[v]
        cust_dev[nb] = [shared] + cust_dev[nb]

    def emit(t_sec, cust, dev, inst, merch, term, amt, ring=-1):
        rows.append((t_sec, cust, dev, inst, merch, term, round(amt, 2)))
        labels.append(ring)
        acct_of.append(cust)
        dev_of.append(dev)
        inst_of.append(inst)

    horizon = DAYS * 86400
    lam = 40.0                      # ~40 txns/customer over 90 days
    for c in range(N_CUST):
        n = rng.poisson(lam)
        ts = np.sort(rng.uniform(0, horizon, n))
        devs = cust_dev[c]
        insts = cust_inst[c]
        for t in ts:
            emit(int(t), c, devs[rng.integers(0, len(devs))],
                 insts[rng.integers(0, len(insts))],
                 f"M{rng.integers(0, N_MERCH):03d}",
                 f"T{rng.integers(0, N_TERM):04d}",
                 float(rng.lognormal(3.5, 0.9)))

    def plant_ring(rid, n_acct, n_dev, n_inst, n_merch, n_txn, span_s,
                   start_lo, start_hi, bridge_with=None):
        accts = list(int(a) for a in
                     rng.choice(N_CUST, size=n_acct, replace=False))
        devs = [f"RD{rid}_{k}" for k in range(n_dev)]
        insts = [f"RI{rid}_{k}" for k in range(n_inst)]
        # rings reuse ORDINARY merchants - merchant identity must not leak
        merchs = [f"M{rng.integers(0, N_MERCH):03d}" for _ in range(n_merch)]
        start = float(rng.integers(start_lo, start_hi))
        ts = np.sort(start + rng.uniform(0, span_s, n_txn))
        for t in ts:
            a = accts[rng.integers(0, n_acct)]
            # ring txns mostly through ring infrastructure, sometimes personal
            if rng.random() < 0.85:
                dev = devs[rng.integers(0, n_dev)]
                inst = insts[rng.integers(0, n_inst)]
            else:
                dev = cust_dev[a][rng.integers(0, len(cust_dev[a]))]
                inst = cust_inst[a][0]
            emit(int(t), a, dev, inst,
                 merchs[rng.integers(0, n_merch)],
                 f"T{rng.integers(0, N_TERM):04d}",
                 float(rng.lognormal(4.6, 0.8)), ring=rid)
        if bridge_with:
            # bridge member additionally uses the other ring's first device
            b_devs = bridge_with[1]
            b_start = bridge_with[0]
            for k in range(max(3, n_txn // 20)):
                t = int(b_start + rng.uniform(0, span_s))
                emit(t, accts[0], b_devs[0], insts[0],
                     merchs[rng.integers(0, n_merch)],
                     f"T{rng.integers(0, N_TERM):04d}",
                     float(rng.lognormal(4.6, 0.8)), ring=rid)
        return {"accounts": sorted(accts), "devices": devs,
                "instruments": insts, "merchants": merchs,
                "n_transactions": int(n_txn)}

    meta = {}
    # split boundaries land ~day 63 (70%) and ~day 77 (85%):
    #   Ring A -> TRAIN period, Ring B -> straddles train/valid,
    #   Ring C -> spans VALID+TEST (ground truth present in every split)
    meta["RingA"] = plant_ring("A", 5, 2, 3, 2, 20, 72 * 3600,
                               30 * 86400, 33 * 86400)
    startB = 58 * 86400
    meta["RingB"] = plant_ring("B", 10, 3, 5, 4, 80, 7 * 86400,
                               startB, startB + 86400)
    meta["RingC"] = plant_ring("C", 20, 5, 8, 6, 240, 20 * 86400,
                               62 * 86400, 64 * 86400,
                               bridge_with=(startB, meta["RingB"]["devices"]))

    df = pd.DataFrame(rows, columns=["t_sec", "customer", "device",
                                     "instrument", "merchant", "terminal",
                                     "amount"])
    df["hour"] = (df["t_sec"] % 86400 // 3600).astype("int16")
    df["dow"] = ((df["t_sec"] // 86400) % 7).astype("int8")
    df["is_ring"] = (df.index.to_series().map(
        lambda i: labels[i] != -1)).astype("int8")
    df["ring_id"] = [str(x) for x in labels]

    DATA_SYNTH.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DATA_SYNTH / "synthetic_transactions.parquet", index=False)
    with open(DATA_SYNTH / "ring_ground_truth.json", "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return df, meta


if __name__ == "__main__":
    df, meta = generate()
    print(df.shape, "ring txns:", int(df.is_ring.sum()))
    print(json.dumps(meta, indent=1, default=str)[:600])
