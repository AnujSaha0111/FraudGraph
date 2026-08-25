import numpy as np

from app.config import load_settings
from app.graph.index import GraphIndex
from app.version import __version__


def test_graph_strategy_defaults_exposed():
    s = load_settings(environ={"FG_BASE_DIR": "X:"})
    # prototype constants from the investigation prototype, §16
    assert s.hub_degree_max == 1000
    assert (s.window_back_days, s.window_fwd_days) == (14, 2)
    assert s.neighbor_cap == 200


def _tiny_index(hub_degree_max=1000):
    # txn_pos:      0     1     2           3
    all_ts = np.array([100, 200, 500, 20_000_000])
    types = ["CARD", "CARD", "DEVICE", "DEVICE"]
    keys = ["c1", "c1", "d1", "d1"]
    pos = [0, 1, 1, 3]
    ts = [100, 200, 200, 20_000_000]   # txn3 far beyond forward window
    return GraphIndex(types, keys, pos, ts, all_ts,
                      hub_degree_max=hub_degree_max)


def test_windowed_neighbors():
    idx = _tiny_index()
    got = idx.windowed_neighbors("CARD", "c1", t=200,
                                 back_s=14 * 86400, fwd_s=2 * 86400)
    assert sorted(int(x) for x in got) == [0, 1]
    assert len(idx.windowed_neighbors("CARD", "missing", t=200,
                                      back_s=10, fwd_s=10)) == 0


def test_seed_entities():
    idx = _tiny_index()
    assert ("CARD", "c1") in idx.seed_entities(1)
    assert idx.seed_entities(999) == []


def test_hub_guard_excludes_high_degree():
    idx = _tiny_index(hub_degree_max=1)   # c1/d1 each have degree 2 -> dropped
    assert idx.n_entities == 0
    assert len(idx.windowed_neighbors("CARD", "c1", t=200,
                                      back_s=10, fwd_s=10)) == 0


def test_expand_deterministic_and_cached():
    idx = _tiny_index()
    a = idx.expand(1, back_s=14 * 86400, fwd_s=2 * 86400)
    b = idx.expand(1, back_s=14 * 86400, fwd_s=2 * 86400)
    assert a == b
    assert a == frozenset({0, 1})   # txn3 excluded: outside fwd window
    c = idx.expand(2, back_s=14 * 86400, fwd_s=2 * 86400)
    assert c == frozenset({2})      # seed without links expands to itself


def test_health_version_matches_package():
    from app.config import load_settings
    s = load_settings(environ={"FG_BASE_DIR": "X:"})
    assert isinstance(__version__, str) and __version__
    assert s.env == "dev"
