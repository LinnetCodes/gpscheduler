"""Example jobs package for the gpscheduler demo.

gpscheduler imports every package named in ``scheduler.yaml:packages`` via
``importlib.import_module``. Importing a top-level package does *not* re-import
its submodules, so we import the job modules here to ensure the ``@scheduled``
and ``@worker_init`` side-effects (Registry registration) fire.

Run from the repo root so ``demo_jobs`` is importable:

    python -m gpscheduler ...   # with cwd = gpscheduler/  (examples/ is on sys.path)

Each ``func`` / ``worker_init`` value in ``configs/jobs/*.yaml`` must equal the
decorated function's registry key, which is ``f"{__module__}.{__qualname__}"``.
"""

# Importing the submodules triggers @scheduled / @worker_init registration. The
# import order does not matter; Registry registration is order-independent.
from demo_jobs import (
    cleanup,  # noqa: F401
    compute,  # noqa: F401  (worker_init + process executor)
    db,  # noqa: F401  (worker_init + gp_context)
    hello,  # noqa: F401
    maintenance,  # noqa: F401
)
