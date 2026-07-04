"""In-process counters, exposed at /metrics in Prometheus text format.

Cache hit rate is the KPI of the whole design (v4 C12) — it ships in Phase 1,
not as an afterthought.
"""

import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)


def inc(name: str, n: int = 1) -> None:
    with _lock:
        _counters[name] += n


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)


def render_prometheus() -> str:
    lines = [f"yoola_{name} {value}" for name, value in sorted(snapshot().items())]
    return "\n".join(lines) + "\n"


def reset() -> None:  # tests only
    with _lock:
        _counters.clear()
