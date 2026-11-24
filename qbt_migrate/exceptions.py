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


class BackupError(QBTMigrateError, OSError):
    """The backup archive could not be created.

    Raised before any `.fastresume` file is touched, so nothing has changed.
    Without it a full disk or a read-only BT_backup ended the run with a bare
    `OSError` traceback. Still an `OSError`, with the original `errno`, so
    library callers that caught the bare error keep working.
    """

    def __init__(self, archive_path: Path, error: OSError):
        self.archive_path = archive_path
        self.error = error
        super().__init__(
            f"Could not create the backup archive {archive_path}: {error}"
        )
        # Only `errno`: setting `strerror` too would make `str()` print
        # "[Errno n] strerror" instead of the message above.
        self.errno = error.errno
