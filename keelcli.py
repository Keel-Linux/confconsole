"""Thin client of the ``keel`` command for the Instance menu.

The Instance plugins (``plugins.d/Instance``) collect input in a dialog,
call ``keel`` through this module and show what comes back. Nothing here
opens a dialog and nothing here decides anything about a spec: every check
is the command's, so the menu and the headless run share one code path
(brief section 6). ``call`` is the only function with a side effect; the
rest are pure functions over its result, tested without a ``keel``.
"""

import json
import os
import subprocess
from dataclasses import dataclass

KEEL = "keel"
DEFAULT_SPEC = "/etc/keel/instance.yaml"
DEFAULT_EXPORT = "/root/instance.yaml"
NOT_INSTALLED = "keel is not installed; install the keel package"

# keel/exits.py, reproduced so that a message exists for every code
OK = 0
USAGE = 1
SPEC_UNREADABLE = 2
SPEC_INVALID = 3
SECRET_ERROR = 4
CONF_ERROR = 5
INSPECT_INCOMPLETE = 13
DRIFT_FOUND = 14

COMMON_MESSAGES = {
    OK: "done",
    USAGE: "usage error: keel rejected an option or argument",
    SPEC_UNREADABLE: "the spec file cannot be read or is not valid YAML",
    SPEC_INVALID: "the spec is valid YAML but fails validation; every error"
    " is listed above",
    SECRET_ERROR: "a referenced secret is missing or is readable by somebody"
    " other than its owner",
    CONF_ERROR: "the conf file cannot be written",
}

COMMAND_MESSAGES = {
    "validate": {OK: "the spec is valid"},
    "apply": {OK: "the spec was applied"},
    "diff": {
        OK: "no drift: every declared field matches the machine",
        INSPECT_INCOMPLETE: "no drift, but some declared fields could not be"
        " observed",
        DRIFT_FOUND: "drift found: at least one declared field differs on"
        " the machine",
    },
    "inspect": {
        OK: "spec written; every required field was inferred",
        CONF_ERROR: "the spec or the report could not be written",
        INSPECT_INCOMPLETE: "spec written, but some fields could not be"
        " inferred and need editing; see the report",
    },
}

DIFF_HEADER = ("field", "status", "declared", "observed")
MISSING_VALUE = "-"
MAX_CELL = 40
ELLIPSIS = "..."


class KeelNotInstalled(Exception):
    """Raised by ``call`` when the keel command is not on PATH."""


@dataclass(frozen=True)
class Result:
    """What one keel run returned."""

    argv: tuple[str, ...]
    code: int
    stdout: str
    stderr: str

    @property
    def command(self) -> str:
        return " ".join(self.argv)

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


def spec_path() -> str:
    """The spec file keel reads: ``$KEEL_SPEC``, else the default."""
    return os.environ.get("KEEL_SPEC") or DEFAULT_SPEC


def report_path(output: str) -> str:
    """Where ``inspect`` writes its report, next to the spec it writes."""
    root, _ = os.path.splitext(output)
    return root + ".report.txt"


def call(argv: list[str]) -> Result:
    """Run ``keel`` with ``argv``, capturing both streams, never a shell."""
    command = [KEEL, *argv]
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise KeelNotInstalled(NOT_INSTALLED) from None
    return Result(tuple(command), proc.returncode, proc.stdout, proc.stderr)


def describe_exit(command: str, code: int) -> str:
    """The one line an operator reads for an exit code of ``command``."""
    message = COMMAND_MESSAGES.get(command, {}).get(code)
    if message is None:
        message = COMMON_MESSAGES.get(code, f"keel exited with code {code}")
    return f"keel {command}: exit {code}, {message}"


def read_text(path: str) -> str:
    """The file's text, or one line saying why it could not be read."""
    try:
        with open(path) as fob:
            return fob.read()
    except OSError as error:
        return f"{path}: {error.strerror}"


def format_value(value) -> str:
    """One cell of the drift table: lists joined, booleans lowercase."""
    if value is None:
        return MISSING_VALUE
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def clip(cell: str, width: int = MAX_CELL) -> str:
    """The cell cut to ``width`` characters, so a key list or a long
    reason does not stretch the table past the dialog."""
    if len(cell) <= width:
        return cell
    return cell[: width - len(ELLIPSIS)] + ELLIPSIS


def diff_rows(fields: list[dict]) -> list[tuple[str, str, str, str]]:
    """The table rows; an unobserved field shows the reason instead."""
    rows = []
    for field in fields:
        observed = format_value(field.get("observed"))
        if observed == MISSING_VALUE and field.get("reason"):
            observed = field["reason"]
        rows.append(
            (
                str(field.get("field", MISSING_VALUE)),
                str(field.get("status", MISSING_VALUE)),
                clip(format_value(field.get("declared"))),
                clip(observed),
            )
        )
    return rows


def align(rows: list[tuple[str, ...]]) -> list[str]:
    """Rows as lines with every column padded to its widest cell."""
    widths = [
        max(len(row[column]) for row in rows)
        for column in range(len(rows[0]))
    ]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths))
        .rstrip()
        for row in rows
    ]


def summary(document: dict) -> str:
    """The summary line, worded as ``keel diff --format text`` words it."""
    counts = document.get("counts", {})
    parts = [
        f"{counts.get(key, 0)} {key.replace('_', ' ')}"
        for key in ("same", "drift", "unknown", "not_declared", "not_compared")
    ]
    verdict = "drift found" if document.get("drift") else "no drift"
    return f"diff: {', '.join(parts)}; {verdict}"


def render_diff(text: str) -> list[str]:
    """Lines for the JSON document ``keel diff --format json`` prints.

    Raises ValueError when ``text`` is not that document."""
    document = json.loads(text)
    if not isinstance(document, dict) or "fields" not in document:
        raise ValueError("not a keel diff document")
    rows = [DIFF_HEADER, *diff_rows(document["fields"])]
    return [*align(rows), "", summary(document)]


def view_text(path: str, spec: str, result: Result) -> str:
    """The View spec screen: the file, then the validation report."""
    return (
        f"{path}\n\n{spec.rstrip()}\n\n"
        f"$ {result.command}\n{result.output}\n\n"
        f"{describe_exit('validate', result.code)}"
    )


def apply_text(result: Result) -> str:
    """The Apply spec screen: the command's output and its verdict."""
    return (
        f"$ {result.command}\n{result.output}\n\n"
        f"{describe_exit('apply', result.code)}"
    )


def drift_text(result: Result) -> str:
    """The Show drift screen: the table when there is one, else the text."""
    try:
        lines = render_diff(result.stdout)
    except ValueError:
        lines = [result.output]
    return "\n".join([*lines, "", describe_exit("diff", result.code)])


def export_text(
    output: str, report: str, report_text: str, result: Result
) -> str:
    """The Export spec screen: where the files went, then the report."""
    return (
        f"spec: {output}\nreport: {report}\n\n"
        f"{(report_text + result.output).strip()}\n\n"
        f"{describe_exit('inspect', result.code)}"
    )
