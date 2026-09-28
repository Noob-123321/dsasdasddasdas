"""In-process application metrics and request instrumentation."""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    requests: int = 0
    errors: int = 0
    api_requests: int = 0
    route_counts: Counter = field(default_factory=Counter)
    status_counts: Counter = field(default_factory=Counter)
    latencies: deque = field(default_factory=lambda: deque(maxlen=2000))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, path: str, status: int, duration_ms: float, api: bool = False) -> None:
        with self.lock:
            self.requests += 1
            self.route_counts[path] += 1
            self.status_counts[str(status)] += 1
            self.latencies.append(duration_ms)
            if api:
                self.api_requests += 1
            if status >= 500:
                self.errors += 1

    def snapshot(self) -> dict:
        with self.lock:
            values = sorted(self.latencies)
            p50 = values[len(values) // 2] if values else 0.0
            p95 = values[min(len(values) - 1, int(len(values) * 0.95))] if values else 0.0
            return {
                "uptime_seconds": max(0, int(time.time() - self.started_at)),
                "requests": self.requests,
                "errors": self.errors,
                "api_requests": self.api_requests,
                "error_rate": round(self.errors / self.requests, 5) if self.requests else 0.0,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "routes": dict(self.route_counts.most_common(20)),
                "statuses": dict(self.status_counts),
            }


metrics = Metrics()
