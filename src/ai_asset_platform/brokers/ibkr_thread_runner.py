"""Contain IB API message-loop teardown races without weakening broker safety.

The IB API client can raise a TypeError inside EClient.run() when a connection
attempt is torn down before serverVersion is populated. Read-only probes use
this helper so such background-thread exceptions are captured as diagnostic
errors instead of leaking uncaught tracebacks to the operator.
"""
from __future__ import annotations


def run_ibapi_message_loop_safely(client, *, errors: list[str]) -> None:
    try:
        client.run()
    except TypeError as exc:
        message = str(exc)
        if "NoneType" in message and ">=" in message:
            errors.append(f"IBAPI message-loop teardown race: {message}")
            return
        raise
