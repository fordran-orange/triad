"""Compatibility guard for the unverified host-worktree executor.

A Git worktree does not isolate filesystem access or credentials. Actual provider
execution goes through Runtime and its independently verified isolated profiles.
"""


class AutonomousCLIRun:
    def __init__(self, *args, **kwargs):
        raise PermissionError(
            "Unverified host CLI execution is unavailable; use Core Runtime with a "
            "verified isolated execution profile and independent QA"
        )
