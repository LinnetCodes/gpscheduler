"""Hello-world job: demonstrates args/kwargs configuration.

This job takes a positional arg and a keyword arg, both supplied via the job's
YAML config (see ``configs/jobs/hello.yaml``). It does NOT declare a
``gp_globals`` parameter, so the scheduler will not inject ``job_globals`` into
it (ADR-0006 conditional injection).
"""

from __future__ import annotations

from gpscheduler import scheduled


@scheduled
def greet(name: str, *, greeting: str = "Hello") -> None:
    """Print a greeting to stdout.

    Args:
        name: Who to greet (positional, set via ``args`` in YAML).
        greeting: The greeting word (keyword, set via ``kwargs`` in YAML).
    """
    print(f"[hello] {greeting}, {name}!")
