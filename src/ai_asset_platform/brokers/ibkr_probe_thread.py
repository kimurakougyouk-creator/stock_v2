"""Contain known IB API message-loop startup/teardown exceptions for read-only probes.

The bundled ibapi client may enter ``EClient.run()`` after a failed or already-
disconnected connection attempt. In that state ``serverVersion()`` can be
``None`` and the upstream loop raises a TypeError in a daemon thread. This
helper contains that background exception and exposes it as observable probe
evidence instead of leaking an uncaught traceback.

It never creates, changes, cancels, or transmits an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Thread
from typing import Callable


@dataclass
class IbkrProbeThreadState:
    exception: str | None = None


def start_guarded_ibapi_loop(
    run_fn: Callable[[], None],
    *,
    state: IbkrProbeThreadState | None = None,
    name: str = "ibkr-probe-loop",
) -> tuple[Thread, IbkrProbeThreadState]:
    observed = state or IbkrProbeThreadState()

    def guarded() -> None:
        try:
            run_fn()
        except Exception as exc:  # daemon probe must report instead of traceback
            observed.exception = f"{type(exc).__name__}: {exc}"

    thread = Thread(target=guarded, daemon=True, name=name)
    thread.start()
    return thread, observed
