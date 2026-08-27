# Small shared utilities: timing, memory tracking, resource logging
import json
import threading
import time
import contextlib

import psutil

from src.config import RESOURCE_LOG


def current_rss_gb():
    return psutil.Process().memory_info().rss / 1e9


def system_ram_gb():
    m = psutil.virtual_memory()
    return {"total_gb": round(m.total / 1e9, 2),
            "available_gb": round(m.available / 1e9, 2)}


class _RssSampler(threading.Thread):
    # Samples own-process RSS ~20x/second to approximate peak usage

    def __init__(self):
        super().__init__(daemon=True)
        self.peak = 0.0
        self._stop = threading.Event()
        self._proc = psutil.Process()

    def run(self):
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak,
                                self._proc.memory_info().rss / 1e9)
            except Exception:
                pass
            self._stop.wait(0.05)


@contextlib.contextmanager
def log_resources(stage, extra=None):
    # Context manager that times a stage and appends metrics to the log
    sampler = _RssSampler()
    t0 = time.perf_counter()
    rss0 = current_rss_gb()
    sampler.start()
    yield
    dt = time.perf_counter() - t0
    sampler._stop.set()
    sampler.join(timeout=1.0)
    rec = {
        "stage": stage,
        "seconds": round(dt, 2),
        "rss_start_gb": round(rss0, 3),
        "rss_end_gb": round(current_rss_gb(), 3),
        "peak_rss_gb": round(max(sampler.peak, current_rss_gb()), 3),
    }
    if extra:
        rec.update(extra)
    RESOURCE_LOG.parent.mkdir(exist_ok=True, parents=True)
    with open(RESOURCE_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[resources] {stage}: {dt:.1f}s, peak RSS {rec['peak_rss_gb']} GB")
