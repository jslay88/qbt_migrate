from dataclasses import dataclass, field
from pathlib import Path

from qbt_migrate.names import torrent_name


# Keys holding a single path value, in the order they are shown to the user.
PATH_KEYS = ("save_path", "qBt-savePath", "qBt-downloadPath")

# Key holding a list of paths.
MAPPED_FILES_KEY = "mapped_files"


@dataclass(frozen=True)
class PathChange:
    """One key's value before and after a migration."""

    key: str
    old: str
    new: str
    # Only set for `mapped_files`. `old` and `new` are then the first entry
    # that changes, as an example, rather than the whole list.
    changed_entries: int | None = None
    total_entries: int | None = None

    @property
    def is_list(self) -> bool:
        return self.changed_entries is not None


@dataclass(frozen=True)
class MigrationPlan:
    """What a migration would do to one `.fastresume`, without doing it."""

    file_path: Path
    changes: tuple[PathChange, ...] = ()
    # The torrent's display name. A .fastresume is named after the 40 character
    # info hash, which tells nobody which torrent they are looking at.
    name: str = ""
    # Set when the file was discovered as relevant but could not be planned,
    # so a dry run surfaces failures instead of only successes.
    error: str | None = None

    def __bool__(self) -> bool:
        """True when applying this plan would change something."""
        return bool(self.changes)


@dataclass
class PlanSummary:
    """Every plan from one dry run, plus the counts worth reporting."""

    plans: list[MigrationPlan] = field(default_factory=list)

    @property
    def discovered(self) -> int:
        return len(self.plans)

    @property
    def changing(self) -> list[MigrationPlan]:
        return [plan for plan in self.plans if plan]

    @property
    def failing(self) -> list[MigrationPlan]:
        return [plan for plan in self.plans if plan.error is not None]


def diff_data(
    file_path: Path,
    before: dict[str, object],
    after: dict[str, object],
) -> MigrationPlan:
    """Build a plan from the same fastresume data before and after a migration.

    Diffing real output rather than predicting it means a preview cannot drift
    away from what an apply actually does.
    """
    changes = []
    name = torrent_name(file_path, before)
    for key in PATH_KEYS:
        old, new = before.get(key), after.get(key)
        if old != new and isinstance(new, str):
            changes.append(PathChange(key, str(old), new))

    list_change = _diff_mapped_files(before, after)
    if list_change is not None:
        changes.append(list_change)

    return MigrationPlan(
        file_path=file_path, changes=tuple(changes), name=name
    )


def _diff_mapped_files(
    before: dict[str, object],
    after: dict[str, object],
) -> PathChange | None:
    old_files = before.get(MAPPED_FILES_KEY)
    new_files = after.get(MAPPED_FILES_KEY)
    if not isinstance(old_files, list) or not isinstance(new_files, list):
        return None

    # strict=True asserts the invariant: the new list is always built from
    # the old by comprehension, so the lengths cannot legitimately differ.
    differing = [
        (old, new)
        for old, new in zip(old_files, new_files, strict=True)
        if old != new and isinstance(new, str)
    ]
    if not differing:
        return None

    example_old, example_new = differing[0]
    return PathChange(
        key=MAPPED_FILES_KEY,
        old=str(example_old),
        new=example_new,
        changed_entries=len(differing),
        total_entries=len(new_files),
    )
