"""Cross-platform graceful-shutdown signal handling (ADR-0008).

Signal handlers must stay minimal: they only set a threading.Event. The actual
shutdown work happens on the main thread, avoiding the classic pitfalls of
calling non-reentrant functions from a signal handler.
"""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Callable

RequestShutdown = Callable[[], None]


def install_shutdown_handler(stop_event: threading.Event) -> RequestShutdown:
    """Register platform-appropriate signals that set ``stop_event``.

    On POSIX both SIGINT and SIGTERM are registered; on Windows only SIGINT
    (Ctrl+C) is reliable (ADR-0008). Returns a ``request_shutdown`` callable
    that sets the event directly — useful for programmatic shutdown.

    Must be called from the main thread (signal.signal() requirement).
    """

    def _handler(*_args: object) -> None:
        stop_event.set()

    signals = [signal.SIGINT]
    if os.name != "nt":
        # Windows: SIGTERM can be registered but is effectively never raised
        # by taskkill; do not rely on it (ADR-0008).
        signals.append(signal.SIGTERM)

    for sig in signals:
        signal.signal(sig, _handler)

    def request_shutdown() -> None:
        stop_event.set()

    return request_shutdown
