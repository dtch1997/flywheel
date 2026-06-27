"""Output gate — enforce that a finished run produced a persistable artifact.

The loop's input is an ``Idea``; its *output* should be a durable, reviewable
report. Without a gate, an idea can be marked ``done`` with no artifact at all —
the loop turns but leaves nothing behind. ``OutputGate`` is the mechanism that
refuses the ``done`` transition until a valid report exists.

Like the other seams (``Backlog``, ``Guardrails``, ``Runner``) this is a
``Protocol`` with a default implementation. The default, ``ReportlyGate``,
validates the report against the `reportly` standard (scaffold/lint/build for
experiment reports); ``NullGate`` disables the check. Projects that use a
different report standard implement ``OutputGate`` and wire it in.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, runtime_checkable

from .models import Idea


class GateResult:
    """Outcome of an output check: ``ok`` plus a human-readable ``reason``."""

    __slots__ = ("ok", "reason")

    def __init__(self, ok: bool, reason: str = ""):
        self.ok = ok
        self.reason = reason

    def __bool__(self) -> bool:  # so `if gate.check(...):` reads naturally
        return self.ok


@runtime_checkable
class OutputGate(Protocol):
    """Decides whether an idea has produced an acceptable persistable output.

    Called at the ``done`` transition. ``report_path`` is the candidate report
    for *this* transition (the one passed to ``flywheel update --report``), which
    may differ from / not yet be on ``idea.links``.
    """

    def check(self, idea: Idea, report_path: Optional[str] = None) -> GateResult:
        ...


class NullGate:
    """No-op gate — every run passes. Use when output enforcement is off."""

    def check(self, idea: Idea, report_path: Optional[str] = None) -> GateResult:
        return GateResult(True)


def resolve_report_path(idea: Idea, report_path: Optional[str], *, root: str = ".",
                        link_field: str = "report") -> Optional[str]:
    """The report to validate: the one passed this transition, else the link."""
    candidate = report_path or idea.links.get(link_field) or ""
    if not candidate:
        return None
    return candidate if os.path.isabs(candidate) else os.path.join(root, candidate)


class ReportlyGate:
    """Validate the report against the `reportly` standard.

    Requires `reportly` to be importable (an optional dependency, like the
    stagehand dashboard). Construct via ``ReportlyGate.create(...)`` to get a
    helpful message instead of an ImportError when it's missing.
    """

    def __init__(self, *, root: str = ".", level: str = "error",
                 link_field: str = "report"):
        import reportly  # raises ImportError if absent — see create()

        self._reportly = reportly
        self.root = root
        self.level = level
        self.link_field = link_field

    @classmethod
    def create(cls, **kw) -> "ReportlyGate":
        try:
            return cls(**kw)
        except ImportError as e:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "output validator 'reportly' is not installed.\n"
                "  uv tool install --force <flywheel> --with reportly\n"
                "  (or `pip install` it into the same env), or set "
                "[output] validator = \"none\" to disable the check."
            ) from e

    def check(self, idea: Idea, report_path: Optional[str] = None) -> GateResult:
        path = resolve_report_path(idea, report_path, root=self.root,
                                   link_field=self.link_field)
        if not path:
            return GateResult(
                False,
                f"no report artifact (pass --{self.link_field} <path.md>); a run "
                "must leave a reportly-valid report behind",
            )
        if not os.path.exists(path):
            return GateResult(False, f"report not found on disk: {path}")

        r = self._reportly
        cfg = r.load_config(path)
        if self.level:  # let flywheel's [output] level override reportly.toml
            cfg.level = self.level
        issues = r.lint_file(path, cfg)
        if r.is_failure(issues, cfg):
            shown = "\n".join("  " + i.format() for i in issues)
            return GateResult(
                False,
                f"report fails reportly lint ({path}):\n{shown}",
            )
        return GateResult(True, f"report ok: {path}")


def make_gate(validator: str = "reportly", *, root: str = ".", level: str = "error",
              link_field: str = "report", require_report: bool = True) -> OutputGate:
    """Build the gate the config asks for.

    ``require_report=False`` forces a ``NullGate`` regardless of ``validator``.
    ``validator="none"`` validates only that *a* report path exists on disk.
    """
    if not require_report:
        return NullGate()
    if validator in ("", "none"):
        return _ExistsGate(root=root, link_field=link_field)
    if validator == "reportly":
        return ReportlyGate.create(root=root, level=level, link_field=link_field)
    raise ValueError(f"unknown output validator {validator!r} (use 'reportly' or 'none')")


class _ExistsGate:
    """Require a report path that exists on disk, but don't validate its content."""

    def __init__(self, *, root: str = ".", link_field: str = "report"):
        self.root = root
        self.link_field = link_field

    def check(self, idea: Idea, report_path: Optional[str] = None) -> GateResult:
        path = resolve_report_path(idea, report_path, root=self.root,
                                   link_field=self.link_field)
        if not path:
            return GateResult(
                False, f"no report artifact (pass --{self.link_field} <path>)")
        if not os.path.exists(path):
            return GateResult(False, f"report not found on disk: {path}")
        return GateResult(True, f"report present: {path}")
