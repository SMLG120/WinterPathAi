"""Dedicated, pre-warmed worker pool for CPU-bound route computation.

Running the engine on FastAPI's generic threadpool made requests that landed on a fresh thread
pay pyproj's per-thread transformer initialisation (measured 17–94 ms per transformer). This
pool's threads warm their transformers once, at startup.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from winterpath_routing.geo import warm_thread

T = TypeVar("T")


class ComputePool:
    def __init__(self, workers: int = 4) -> None:
        self.workers = max(1, workers)
        self._ex = ThreadPoolExecutor(
            self.workers, thread_name_prefix="wp-route", initializer=warm_thread
        )

    def warm(self) -> None:
        """Force creation (and warm-up) of every worker thread."""
        barrier = threading.Barrier(self.workers)
        futs = [self._ex.submit(barrier.wait, 30) for _ in range(self.workers)]
        for f in futs:
            f.result()

    async def run(self, fn: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._ex, fn)

    def shutdown(self) -> None:
        self._ex.shutdown(wait=False, cancel_futures=True)
