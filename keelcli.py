"""Thin client of the ``keel`` command for the Instance menu.

The Instance plugins (``plugins.d/Instance``) collect input in a dialog,
call ``keel`` through this module and show what comes back. Nothing here
opens a dialog and nothing here decides anything about a spec: every check
is the command's, so the menu and the headless run share one code path
(brief section 6). ``call`` is the only function with a side effect; the
rest are pure functions over its result, tested without a ``keel``.
"""

import ipaddress
import json
import os
import secrets
import subprocess
import tempfile
from dataclasses import dataclass

import yaml

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
APPLY_NEEDS_ROOT = 15
APPLY_FAILED = 16
NETWORK_NOT_CONFIRMED = 21

COMMON_MESSAGES = {
    OK: "done",
    USAGE: "usage error: keel rejected an option or argument",
    SPEC_UNREADABLE: "the spec file cannot be read or is not valid YAML",
    SPEC_INVALID: "the spec is valid YAML but fails validation; every error"
    " is listed above",
    SECRET_ERROR: "a referenced secret is missing or is readable by somebody"
    " other than its owner",
    CONF_ERROR: "the conf file cannot be written",
    APPLY_NEEDS_ROOT: "this must run as root on the live system",
    APPLY_FAILED: "at least one field was not converged; the output above"
    " names it, and a refusal is one of the reasons it can say",
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
    "promote": {
        OK: "this node is a primary now; the description still says"
        " replica, which keel diff reports as drift until you change it",
        APPLY_FAILED: "nothing was promoted; the reason is above",
        APPLY_NEEDS_ROOT: "promoting must run as root",
    },
    "confirm": {
        OK: "confirmed: the network change stays",
        # keel refuses for several reasons, nothing waiting among them
        # (another session may have confirmed it already), so the verdict
        # repeats none of them and points at keel's own line
        NETWORK_NOT_CONFIRMED: "not confirmed: the reason is above",
    },
    "key": {
        OK: "this node's public key; the private key never leaves the"
        " machine",
        APPLY_FAILED: "no public key: the reason is above",
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


# --- the database mode screens -------------------------------------------
#
# Decision 0013: choosing a database appliance means choosing its mode, and
# the mode choice leads to a screen that configures **this node only**. The
# screens collect what this node needs, write it into the instance
# description and hand the description to keel; every decision about what a
# role means, and every refusal, is keel's (docs/apply.md). Nothing below
# opens a dialog, and nothing below configures anybody else's machine.

DEFAULT_SECRET = "/etc/keel/secrets/replication_password"
DEFAULT_LISTEN = "::1, 127.0.0.1"
STANDALONE = "standalone"
PRIMARY = "primary"
REPLICA = "replica"
NO_FAILOVER = (
    "This replication has NO AUTOMATIC FAILOVER. If the primary stops, no"
    " node takes over by itself: promoting a replica is something you do,"
    " on that replica, from this menu. Replication without failover is not"
    " high availability."
)
THIS_NODE = (
    "This screen configures THIS node only. It does not create replicas,"
    " does not change any other machine, and cannot know what the others"
    " are doing. It changes the database server and leaves the network"
    " and the TLS certificate alone."
)
# A database mode screen converges the database and nothing else it can
# avoid: --skip-network, so saving a mode never rewrites the interfaces
# and never opens the revert window of decision 0018 while the operator
# is reading a result box, and --defer-certificate, so it never asks a
# certificate authority for anything. Both are keel's own flags for the
# system phase (docs/apply.md).
APPLY = [
    "spec", "apply", "--system-only", "--non-interactive",
    "--skip-network", "--defer-certificate",
]
LEFT_ALONE = (
    "The network and the TLS certificate are left alone by this screen"
    " (--skip-network, --defer-certificate)."
)
DESTROY = "--destroy-local-database"
REFUSED = "refused: "
STAGED = ".keelcli-new"
# What a description that does not exist yet starts as: the smallest one
# keel accepts, to which the screen adds `database.server`.
NEW_DESCRIPTION = {"version": 1}


def load_description(path: str) -> tuple[dict, str]:
    """The description a database screen edits

    A fresh appliance may have none yet. The screen then starts one rather
    than stopping at an errno: a description holding only `version` and
    the database section converges the database and nothing else.
    """
    if not os.path.lexists(path):
        return dict(NEW_DESCRIPTION), ""
    return load_spec(path)


def load_spec(path: str) -> tuple[dict, str]:
    """The description as a mapping, or an empty one and what went wrong"""
    try:
        with open(path) as fob:
            document = yaml.safe_load(fob) or {}
    except OSError as error:
        return {}, f"{path}: {error.strerror}"
    except yaml.YAMLError as error:
        return {}, f"{path}: not valid YAML: {error}"
    if not isinstance(document, dict):
        return {}, f"{path}: the description is not a mapping"
    return document, ""


def server_of(document: dict) -> dict:
    """What the description says this node's server is, if anything"""
    database = document.get("database") or {}
    return (database.get("server") or {}) if isinstance(database, dict) else {}


def with_server(document: dict, server: dict) -> dict:
    """A new description with `database.server` replaced

    A copy, never an edit in place: the caller keeps what it loaded, so a
    screen that is cancelled or whose description fails validation leaves
    the file and the loaded document exactly as they were.
    """
    database = dict(document.get("database") or {})
    database["server"] = server
    return {**document, "database": database}


def addresses(text: str) -> list[str]:
    """The listen field as the operator typed it: a list of literals"""
    return [
        one.strip()
        for one in text.replace(",", " ").split()
        if one.strip()
    ]


def standalone_server(engine: str, listen: str) -> dict:
    """One server, answering where it is told and replicating nothing"""
    server = {"engine": engine, "role": STANDALONE}
    if addresses(listen):
        server["listen"] = addresses(listen)
    return server


def primary_server(
    engine: str, listen: str, allowed_from: str, secret: str
) -> dict:
    """Other nodes may replicate from this one, from these origins"""
    server = standalone_server(engine, listen)
    server["role"] = PRIMARY
    server["replication"] = {
        "allowed_from": addresses(allowed_from),
        "secret": {"file": secret.strip()},
    }
    return server


def replica_server(
    engine: str, listen: str, host: str, port: str, secret: str
) -> dict:
    """This node replicates from that one"""
    server = standalone_server(engine, listen)
    server["role"] = REPLICA
    # Brackets are how an IPv6 address is written beside a port, so an
    # operator may paste them; the description holds the bare literal.
    endpoint: dict = {"host": host.strip().strip("[]")}
    if port.strip():
        digits = port.strip()
        endpoint["port"] = int(digits) if digits.isdigit() else digits
    server["replication"] = {
        "primary": endpoint,
        "secret": {"file": secret.strip()},
    }
    return server


def render_spec(document: dict) -> str:
    """The description as it will be written, keys in the order given"""
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)


def write_beside(path: str, text: str, suffix: str) -> tuple[str, str]:
    """Write `text` to a new file of its own beside `path`, root only

    A unique name (mkstemp, created 0600 by it), so two consoles open at
    once never write into each other's file. (the file, the reason on
    failure or "")
    """
    directory = os.path.dirname(path) or "."
    try:
        descriptor, written = tempfile.mkstemp(
            prefix=os.path.basename(path) + ".", suffix=suffix,
            dir=directory,
        )
    except OSError as error:
        return "", f"{path}: {error.strerror}"
    try:
        with os.fdopen(descriptor, "w") as fob:
            fob.write(text)
    except OSError as error:
        discard_spec(written)
        return "", f"{written}: {error.strerror}"
    return written, ""


def stage_spec(document: dict, path: str) -> tuple[str, str]:
    """Write the new description beside the old one, root only

    Beside and not over: what the operator typed is handed to `keel spec
    validate` before it becomes the description this machine boots from,
    so a value that would not load cannot replace one that does. The
    screen commits it or throws it away.
    """
    return write_beside(path, render_spec(document), STAGED)


def commit_spec(staged: str, path: str) -> str:
    """Move the staged description into place; the reason on failure"""
    try:
        os.replace(staged, path)
    except OSError as error:
        return f"{path}: {error.strerror}"
    return ""


def discard_spec(staged: str) -> None:
    """Throw away a staged description that will not be used"""
    try:
        os.unlink(staged)
    except OSError:
        pass


def destroy_question(refusal: str) -> str:
    """The one question in this menu whose Yes loses data"""
    return (
        f"keel refused to build the replica:\n\n{refusal}\n\n"
        "Drop those databases and build the replica? Everything in them"
        " is lost, on this node, and cannot be undone. Answer No to"
        " leave this machine exactly as it is."
    )


def was_refused(result: Result) -> str:
    """What keel refused to do, if it refused something

    apply prints one line per action, and a refusal is the line that says
    so. The console repeats keel's own words rather than inventing its
    own: the refusal an operator confirms has to be the refusal that was
    made.
    """
    for line in result.output.splitlines():
        _, marker, reason = line.partition(REFUSED)
        if marker and reason.strip():
            return reason.strip()
    return ""


def mode_text(server: dict, path: str, result: Result) -> str:
    """The screen an operator reads after a mode was applied"""
    role = str(server.get("role", "?"))
    return (
        f"{path}: database.server.role: {role}\n\n"
        f"$ {result.command}\n{result.output}\n\n"
        f"{describe_exit('apply', result.code)}\n\n{LEFT_ALONE}\n\n"
        f"{NO_FAILOVER}"
    )


def declares_server(text: str | None) -> bool:
    """Whether a description's text declares `database.server`

    keel converges only what a description declares, so applying one that
    declares no server again changes nothing a replica screen wrote.
    """
    try:
        document = yaml.safe_load(text or "") or {}
    except yaml.YAMLError:
        return False
    return isinstance(document, dict) and bool(server_of(document))


def rollback_text(
    path: str, refused: Result, again: Result | None, problems: list[str],
    existed: bool = True,
) -> str:
    """The screen after the operator answered No to dropping data"""
    lines = [
        "You answered No: nothing was dropped and this node is NOT a"
        " replica.", "",
        f"$ {refused.command}\n{refused.output}", "",
    ]
    stays = (
        " The server configuration keel wrote above before it refused"
        " (the replica's drop-in, and a restart) stays until a database"
        " mode is applied from this menu."
    )
    if problems:
        lines += [
            "These could NOT be put back as they were; fix them by hand:",
            *problems,
        ]
    elif again is None and not existed:
        lines += [
            f"There was no {path} before this screen, so it was removed"
            " again, and so was the password file if this screen wrote it."
            + stays,
        ]
    elif again is None:
        lines += [
            f"{path} and the password file were put back as they were. The"
            " old description declares no database server, so keel has"
            " nothing of it to apply again." + stays,
        ]
    else:
        lines += [
            f"{path} and the password file were put back as they were, and"
            " the old description was applied again to undo what keel"
            " wrote above before it refused:", "",
            f"$ {again.command}\n{again.output}", "",
            describe_exit("apply", again.code),
        ]
    return "\n".join(lines)


def invalid_text(path: str, result: Result) -> str:
    """The screen when what was typed does not make a valid description"""
    return (
        f"{path} was NOT changed: the values would not make a valid"
        f" description.\n\n$ {result.command}\n{result.output}\n\n"
        f"{describe_exit('validate', result.code)}"
    )


def promote_text(result: Result) -> str:
    """The screen an operator reads after promoting this replica"""
    return (
        f"$ {result.command}\n{result.output}\n\n"
        f"{describe_exit('promote', result.code)}\n\n{NO_FAILOVER}"
    )


# --- what a replica needs, and the credential both ends hold -------------
#
# The primary's screen hands the operator what each replica's screen will
# ask for: where to replicate from, as whom, and with which password. The
# password lives in a file both ends reference (keel reads it with
# `read_secret_file`: root owned, 0600 or stricter, one trailing newline
# dropped). keel refuses `generate: true` for it, because both ends must
# hold the same value, so the console generates it once, on the primary,
# and shows it once.

# keel/system/dbmariadb.py REPLICATION_USER, reproduced like the exit codes
# above. It is a constant there and not a field on purpose: both ends of a
# pair must name the same account.
REPLICATION_ACCOUNT = "repl"
MARIADB = "mariadb"
DEFAULT_PORTS = {MARIADB: 3306}
REFUSED_ORIGINS = (
    "KEEL REFUSES {origins} ON MARIADB. MariaDB matches the text of a"
    " replica's address, which can leave out a zero group of the prefix"
    " (fd3d:80b2:d0d7::2 is not fd3d:80b2:d0d7:0:...), so no grant holds"
    " it exactly, and the description would not validate."
)
PASSWORD_BYTES = 24
SECRET_DIR_MODE = 0o700
REPLACING = ".keelcli-tmp"
WILDCARDS = ("::", "0.0.0.0")
NO_ORIGIN = (
    "NO ORIGIN IS AUTHORIZED. 'Allow replication from' was left empty, so"
    " keel removed every replication account and no replica can connect."
    " Run this screen again and give each replica's address."
)
LOOPBACK_ONLY = (
    "This server answers on loopback only, so no replica can reach it."
    " Add one of this node's addresses to 'Answer on', or :: for all of"
    " them, and run this screen again."
)


def generate_password() -> str:
    """A replication password: URL safe, so it survives a copy and paste

    keel quotes it into SQL itself and refuses control characters, which
    token_urlsafe never produces.
    """
    return secrets.token_urlsafe(PASSWORD_BYTES)


def secret_exists(path: str) -> bool:
    """Whether a non empty secret file is already there to be kept"""
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def write_secret(path: str, value: str) -> str:
    """Write the replication password where the description references it

    Root only from the first byte and all at once: the value goes to a new
    file beside it (created 0600), which then replaces the old one, so an
    interrupted write never leaves half a password where keel reads it and
    a file that existed with a wider mode is replaced rather than reused.
    Its directory is made 0700 when it has to be made. The reason on
    failure, else "".
    """
    try:
        os.makedirs(os.path.dirname(path) or ".", SECRET_DIR_MODE,
                    exist_ok=True)
    except OSError as error:
        return f"{path}: {error.strerror}"
    return replace_file(path, value + "\n")


def replace_file(path: str, text: str) -> str:
    """Replace a file with `text`, root only and all at once"""
    written, problem = write_beside(path, text, REPLACING)
    if problem:
        return problem
    try:
        os.replace(written, path)
    except OSError as error:
        discard_spec(written)
        return f"{path}: {error.strerror}"
    return ""


def read_back(path: str) -> str | None:
    """A file's text as it is now, or None when there is none"""
    try:
        with open(path) as fob:
            return fob.read()
    except OSError:
        return None


def restore(path: str, text: str | None) -> str:
    """Put a file back as `read_back` found it: the reason on failure

    None means it did not exist, so it is removed again.
    """
    if text is not None:
        return replace_file(path, text)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        return f"{path}: {error.strerror}"
    return ""


def parse_address(text: str):
    """An address object, or None for anything that is not a literal"""
    try:
        return ipaddress.ip_address(text.strip().strip("[]"))
    except ValueError:
        return None


def is_global(text: str) -> bool:
    """An address another machine can reach: not loopback, not link local,
    not the wildcard"""
    found = parse_address(text)
    return found is not None and not (
        found.is_loopback or found.is_link_local or found.is_unspecified
    )


def ipv6_first(values: list[str]) -> list[str]:
    """The same addresses, IPv6 before IPv4 and public before private
    (a unique local fd00::/8, an RFC 1918 10/8) within each, otherwise in
    the order given"""

    def rank(one: str) -> tuple[bool, bool]:
        found = parse_address(one)
        if found is None:
            return (False, False)
        return (found.version != 6, found.is_private)

    return sorted(values, key=rank)


def reachable(listen: list[str], machine: list[str]) -> list[str]:
    """The addresses a replica can replicate from, IPv6 first

    What the server answers on decides it: the global literals of
    `listen`, or every address of the machine when `listen` is absent or
    holds the wildcard. Loopback alone is reachable by nobody, and the
    empty list says so.
    """
    if not listen or any(one.strip() in WILDCARDS for one in listen):
        candidates = machine
    else:
        candidates = listen
    unique = list(dict.fromkeys(one for one in candidates if is_global(one)))
    return ipv6_first(unique)


def primary_listen(listen: str, machine: list[str]) -> str:
    """What the primary's form offers for 'Answer on'

    A description that answers on loopback only (what every appliance
    ships) cannot be replicated from, so the form offers this node's own
    addresses in front of it, IPv6 first. Anything else the operator
    already chose is offered as it is.
    """
    current = addresses(listen)
    if reachable(current, machine) or not machine:
        return listen
    own = ipv6_first([one for one in machine if is_global(one)])
    return ", ".join(own + current)


def suggested_origin(
    allowed_from: str, peers: list[str], refused: list[str] = (),
) -> str:
    """What the primary's form offers for 'Allow replication from'

    Left as it is when the description already names origins keel
    grants. Otherwise the overlay peers' addresses, each replica by its
    own, after what the description names that keel grants: MariaDB
    matches a grant against the text of the replica's address, and in
    this node's /64 that text can drop a zero group of the prefix
    (fd3d:80b2:d0d7::2 is not fd3d:80b2:d0d7:0:...), so keel refuses such
    a prefix (`refused`). With nothing left the field stays empty, which
    authorizes nobody (keel drops every replication account) and the
    handout says so.
    """
    kept = [one for one in addresses(allowed_from) if one not in refused]
    if kept and not refused:
        return allowed_from
    return ", ".join(kept + [one for one in peers if one not in kept])


def refused_origins(allowed_from: str, engine: str) -> list[str]:
    """The origins of the field keel's validation refuses on this engine

    keel.spec.origins.mariadb_problem, reproduced like the account name:
    a prefix that stops inside a group, an IPv6 prefix with a zero group
    the text of an address compresses away (its last group is zero, or
    two in a row are), and a host pattern with ::. PostgreSQL takes a
    prefix as it is.
    """
    if engine != MARIADB:
        return []
    return [one for one in addresses(allowed_from) if _unholdable(one)]


def _unholdable(origin: str) -> bool:
    if "::" in origin and any(one in origin for one in "%_"):
        return True
    if origin.endswith(":%"):
        origin = origin[:-1] + f":/{16 * (origin.count(':'))}"
    if "/" not in origin:
        return False
    try:
        network = ipaddress.ip_network(origin, strict=False)
    except ValueError:
        return False
    length, bits = network.prefixlen, (16 if network.version == 6 else 8)
    if length == network.max_prefixlen:
        return False
    if length == 0 or length % bits:
        return True
    if network.version == 4:
        return False
    groups = network.network_address.exploded.split(":")[: length // 16]
    zero = [int(one, 16) == 0 for one in groups]
    return zero[-1] or any(a and b for a, b in zip(zero, zero[1:]))


def refused_text(refused: list[str], peers: list[str]) -> str:
    """What the primary's form says above a field it had to change"""
    instead = (
        "The field offers the overlay peers' addresses in its place; check"
        " that each is a replica." if peers else
        "There is no overlay peer to offer in its place; give each"
        " replica's address."
    )
    return REFUSED_ORIGINS.format(origins=", ".join(refused)) + " " + instead


def bracketed(address: str) -> str:
    """An IPv6 literal in brackets, the way it is written with a port"""
    return f"[{address}]" if ":" in address else address


def handout_text(
    engine: str, where: list[str], secret: str, password: str = "",
    origins: list[str] | None = None, failure: str = "",
) -> str:
    """What the operator carries to each replica's screen

    The password appears only when it was generated in this run: it is
    shown this once, and afterwards only the file holds it. So it is shown
    even when the apply failed, under a warning that says so. The address
    is written bare, the way the replica's field wants it.
    """
    port = DEFAULT_PORTS.get(engine, "")
    lines = []
    if failure:
        lines += [
            f"THIS NODE IS NOT READY: {failure}. No replica can use it until"
            " the apply succeeds; the output on the previous screen says"
            " why.", "",
        ]
    if not origins:
        lines += [NO_ORIGIN, ""]
    lines += ["What each replica's screen asks for:", ""]
    if where:
        lines.append("  Replicate from (address), IPv6 first:")
        lines += [f"    {one}" for one in where]
        lines.append(
            f"    (with a port it is written {bracketed(where[0])}:{port};"
            " type the bare address)"
        )
    else:
        lines += [f"  Replicate from: none. {LOOPBACK_ONLY}"]
    if origins:
        lines.append(f"  Allowed to replicate: {', '.join(origins)}")
    lines += [
        f"  Port: {port} (leave the field blank)",
        f"  Replication account: {REPLICATION_ACCOUNT} (keel names it;"
        " both ends use it)",
        f"  Password kept in: {secret} (root, mode 0600)",
    ]
    if password:
        lines += [
            "", "Replication password, generated now and shown ONCE:", "",
            f"  {password}", "",
            "Paste it into each replica's screen. Afterwards only the"
            " file above holds it.",
        ]
    else:
        lines += [
            "", f"The password is the one already in {secret}; it is not"
            " shown here.",
        ]
    return "\n".join(lines)


def replica_warning(host: str) -> str:
    """The question asked before a replica screen changes anything"""
    return (
        "Becoming a replica REPLACES the data on this node with a copy of"
        f" the primary at {bracketed(host)}.\n\n"
        "If this server holds any database that is not its own, keel"
        " refuses and this console asks once more, naming them; a Yes"
        " there drops them and cannot be undone. Move anything you need"
        " elsewhere first.\n\n"
        f"{THIS_NODE}\n\nGo on and make this node a replica?"
    )
