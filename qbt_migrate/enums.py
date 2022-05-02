from enum import Enum


class TargetOS(Enum):
    WINDOWS = ["windows"]
    POSIX = ["linux", "mac", "unix"]
