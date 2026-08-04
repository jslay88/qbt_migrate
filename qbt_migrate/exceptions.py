from pathlib import Path


class QBTMigrateError(Exception):
    """Base class for errors raised by this package."""


class FastResumeUpdateError(QBTMigrateError):
    """One or more `.fastresume` files could not be updated.

    Raised after the whole batch has been attempted, so a single bad file does
    not stop the rest from being migrated. Previously these failures happened
    on unjoined worker threads, where the traceback went to stderr and the
    process still exited 0, making a partial migration look like a clean one.
    """

    def __init__(self, failures: dict[Path, BaseException]):
        self.failures = failures
        names = ", ".join(sorted(str(path) for path in failures))
        super().__init__(
            f"{len(failures)} .fastresume file(s) could not be updated: "
            f"{names}"
        )
