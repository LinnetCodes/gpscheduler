"""Process-local Registry mapping dotted-path keys to Scheduled Functions.

The key is ``f"{func.__module__}.{func.__qualname__}"`` (ADR-0004). The
decorator fills this at import time; the config loader queries it at startup.
Per ADR-0004, no locking is needed in v1: registration happens at import
(single-threaded) and lookups are read-only at runtime.
"""

from __future__ import annotations

from collections.abc import Callable


class Registry:
    """A map of dotted-path key -> Scheduled Function."""

    def __init__(self) -> None:
        self._functions: dict[str, Callable[..., object]] = {}

    def register(self, func: Callable[..., object]) -> str:
        """Register ``func`` and return its dotted-path key.

        Re-registering the same function under the same key is idempotent.
        """
        key = f"{func.__module__}.{func.__qualname__}"
        self._functions[key] = func
        return key

    def get(self, key: str) -> Callable[..., object]:
        """Return the function for ``key``.

        Raises:
            KeyError: if ``key`` is not registered.
        """
        try:
            return self._functions[key]
        except KeyError:
            raise KeyError(key) from None

    def contains(self, key: str) -> bool:
        """Return True if ``key`` is registered."""
        return key in self._functions

    def clear(self) -> None:
        """Remove all entries."""
        self._functions.clear()

    def __len__(self) -> int:
        return len(self._functions)


#: Process-global registry populated by ``@scheduled`` and queried by the loader.
registry: Registry = Registry()
