"""The dialog flow the three database mode screens share.

Decision 0013 settled that a database appliance's mode is chosen from the
console and that each screen configures the machine it runs on. The
screens themselves (``plugins.d/Instance/Database_mode``) only say what
their role is and which fields it needs; everything they then do is here,
and everything this module decides is nothing: it collects, hands the
description to ``keel``, and shows what came back. What a role means, and
every refusal, is keel's (``docs/apply.md`` of the keel repository).

``console`` is passed in rather than taken from the plugin globals, so
each function is tested with a scripted fake and no dialog opens.
"""

import contextlib
import os
import shutil
import tempfile

from dialog import DialogError

import ifutil
import keelcli

NET_DIR = "/sys/class/net"
PRIVATE_PREFIX = "keel-console-"
HANDOUT_BOX = (24, 78)
# The interfaces the usage screen leaves out as well: loopback, and the
# virtual ones no replica reaches this node through.
SKIPPED_INTERFACES = (
    "lo", "tap", "tun", "vmnet", "veth", "wmaster", "natbr", "docker",
)
TRANSIENT = {"temporary", "deprecated", "tentative"}
PASSWORD_BOX = (10, 64)
NO_PASSWORD = (
    "No replication password was given and {path} holds none, so there is"
    " nothing a replica could authenticate with. Nothing was changed."
)
GENERATE_QUESTION = (
    "{path} holds no replication password yet.\n\n"
    "Generate one now? It is written to that file (root, mode 0600) and"
    " shown ONCE, after the primary is configured, so you can paste it"
    " into each replica's screen.\n\n"
    "Answer No to type one of your own instead."
)
TYPE_PASSWORD = (
    "The replication password this primary grants to its replicas. It is"
    " written to {path} (root, mode 0600)."
)
PASTE_PASSWORD = (
    "The replication password the primary's screen showed. It is written"
    " to {path} (root, mode 0600).\n\n"
    "Leave it blank to keep the one already in that file."
)
NO_ENGINE = (
    "No database server was found on this machine, and the instance"
    " description names none, so there is no mode to choose. This menu is"
    " for an appliance that runs a database server of its own."
)
INSPECT_FAILED = (
    "keel could not be asked what this machine runs, so the engine to"
    " configure is unknown and nothing was changed."
)
# Under /run: a description the console reads once to learn what this
# machine is, never one the machine boots from, and gone at the next boot.
INSPECTED = "/run/keel-console-inspect.yaml"
REPORT = "/run/keel-console-inspect.report.txt"


def call(console, title: str, argv: list[str]):
    """Run keel; None when it is not installed, and the screen says so"""
    try:
        return keelcli.call(argv)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(title, str(error))
        return None


def engine_of(console, title: str, server: dict) -> str:
    """Which engine this node runs: the description, else the machine

    The screen never asks the operator for it. A machine knows which
    server is installed on it, and `keel inspect` is how that is asked.
    """
    declared = str(server.get("engine") or "")
    if declared:
        return declared
    result = call(console, title, ["inspect", "--output", INSPECTED,
                                   "--report", REPORT])
    if result is None:
        return ""
    document, problem = keelcli.load_spec(INSPECTED)
    if problem:
        console.msgbox(title, f"{INSPECT_FAILED}\n\n{problem}")
        return ""
    observed = str(keelcli.server_of(document).get("engine") or "")
    if not observed:
        console.msgbox(title, f"{NO_ENGINE}\n\n{result.output}".strip())
    return observed


def defaults(server: dict) -> dict:
    """What the form is prefilled with: what the description says now"""
    replication = server.get("replication") or {}
    endpoint = replication.get("primary") or {}
    secret = replication.get("secret") or {}
    listen = server.get("listen") or []
    return {
        "listen": ", ".join(str(one) for one in listen)
                  or keelcli.DEFAULT_LISTEN,
        "allowed_from": ", ".join(
            str(one) for one in (replication.get("allowed_from") or [])
        ),
        "host": str(endpoint.get("host") or ""),
        "port": str(endpoint.get("port") or ""),
        "secret": str(secret.get("file") or keelcli.DEFAULT_SECRET),
    }


def ask(
    console, title: str, text: str, fields: list,
    offer_addresses: bool = False,
) -> dict | None:
    """Show the form, prefilled; None when it was cancelled or cannot run

    `fields` is (label, key, label width, field width), in the order the
    role needs them. `offer_addresses` puts this node's own addresses in
    front of a loopback only 'Answer on', which is what a primary needs.
    The answers always carry the secret file the description references,
    asked or not.
    """
    path = keelcli.spec_path()
    document, problem = keelcli.load_description(path)
    if problem:
        console.msgbox(title, problem)
        return None
    server = keelcli.server_of(document)
    engine = engine_of(console, title, server)
    if not engine:
        return None
    filled = defaults(server)
    if offer_addresses:
        machine = local_addresses()
        filled["listen"] = keelcli.primary_listen(filled["listen"], machine)
        filled["allowed_from"] = keelcli.suggested_origin(
            filled["allowed_from"], machine
        )
    shown = [
        (label, filled[key], label_width, field_width)
        for label, key, label_width, field_width in fields
    ]
    code, values = console.form(
        title, text, format_fields(shown), autosize=True
    )
    if code != "ok":
        return None
    answers = {key: value for (_, key, _, _), value in zip(fields, values)}
    answers.setdefault("secret", filled["secret"])
    answers["engine"] = engine
    return answers


def format_fields(fields: list) -> list:
    """(label, value, label width, field width) as dialog wants a form"""
    return [
        (label, index + 1, 1, value, index + 1, label_width + 2,
         field_width, field_width)
        for index, (label, value, label_width, field_width)
        in enumerate(fields)
    ]


def apply_mode(
    console, title: str, server: dict, may_destroy: bool = False,
    password: str = "",
):
    """Write the role into the description and hand it to keel

    Staged, validated, committed, applied: what the operator typed only
    becomes the description this machine boots from once `keel spec
    validate` has accepted it. A `password` is written to the secret file
    the description references between the validation and the commit, so
    a description keel refused never leaves a credential behind, and the
    apply that reads it never runs without it.

    What the operator answers No to, keel's refusal to destroy the local
    database, is undone as well: the description and the password file
    are put back as they were and the old description is applied again,
    so No leaves the machine as it was found.

    The result of the apply, or None when it stopped before one.
    """
    path = keelcli.spec_path()
    document, problem = keelcli.load_description(path)
    if problem:
        console.msgbox(title, problem)
        return None
    staged, problem = keelcli.stage_spec(
        keelcli.with_server(document, server), path
    )
    if problem:
        console.msgbox(title, problem)
        return None
    result = call(console, title, [
        "spec", "validate", "--no-secret-files", "--spec", staged
    ])
    if result is None or result.code != keelcli.OK:
        keelcli.discard_spec(staged)
        if result is not None:
            console.msgbox(
                title, keelcli.invalid_text(path, result), autosize=True
            )
        return None
    before = [(path, keelcli.read_back(path))]
    if password:
        secret = secret_path(server)
        before.append((secret, keelcli.read_back(secret)))
        problem = keelcli.write_secret(secret, password)
        if problem:
            keelcli.discard_spec(staged)
            console.msgbox(title, f"{path} was NOT changed.\n\n{problem}")
            return None
    problem = keelcli.commit_spec(staged, path)
    if problem:
        # The description stays as it was, so the password written for it
        # goes too: kept, it would be a value no screen ever shows (a later
        # run keeps a password that is already there).
        keelcli.discard_spec(staged)
        problems = put_back(before[1:])
        lines = [f"{path} was NOT changed.", problem]
        if problems:
            lines += [
                "The password file could NOT be put back; fix it by hand:",
                *problems,
            ]
        elif password:
            lines.append("The password file was put back as it was.")
        console.msgbox(title, "\n\n".join(lines))
        return None
    result, declined = converge(console, title, path, may_destroy)
    if result is None:
        return None
    if declined:
        roll_back(console, title, before, result)
        return None
    console.msgbox(
        title, keelcli.mode_text(server, path, result), autosize=True
    )
    return result


def roll_back(console, title: str, before: list, refused) -> None:
    """Put the description and the password back, and apply the old one

    keel already wrote the server's configuration before it refused, so
    putting the files back is not enough: the old description is applied
    again. Where there was none, nothing is left to apply, and the screen
    says what stays.
    """
    problems = put_back(before)
    path, old = before[0]
    again = None
    if keelcli.declares_server(old) and not problems:
        again = call(console, title, keelcli.APPLY + ["--spec", path])
    console.msgbox(
        title,
        keelcli.rollback_text(
            path, refused, again, problems, existed=old is not None
        ),
        autosize=True,
    )


def put_back(before: list) -> list[str]:
    """Restore every file in `before`, last written first; the problems"""
    return [
        problem
        for where, text in reversed(before)
        if (problem := keelcli.restore(where, text))
    ]


def secret_path(server: dict) -> str:
    """The file the description says holds the replication password"""
    secret = (server.get("replication") or {}).get("secret") or {}
    return str(secret.get("file") or keelcli.DEFAULT_SECRET)


def local_addresses() -> list[str]:
    """This machine's stable global addresses, IPv6 first

    Every one, and not the one per interface the usage screen shows: an
    interface commonly holds a public address and a unique local one,
    and the usage screen's pick can be the one a replica elsewhere cannot
    reach. Privacy (temporary) and deprecated addresses are left out,
    because they go away and a replica would lose the primary with them.
    """
    try:
        names = sorted(os.listdir(NET_DIR))
    except OSError:
        return []
    found = []
    for name in names:
        if name.startswith(SKIPPED_INTERFACES):
            continue
        found += [
            address
            for address, _, flags in ifutil._list_ipv6_global(name)
            if not flags & TRANSIENT
        ]
        found.append(ifutil.get_ipconf(name)[0])
    return keelcli.ipv6_first([one for one in found if one])


def passwordbox(console, title: str, text: str) -> str | None:
    """Ask for a password without echoing it; None when cancelled

    `insecure` shows one asterisk per character, so an operator pasting a
    generated password can see that the paste landed.
    """
    height, width = PASSWORD_BOX
    with private_tmp():
        code, value = console._wrapper(
            "passwordbox", text, height, width, title=title, insecure=True
        )
    if code != "ok":
        return None
    return value.strip()


def primary_password(console, title: str, path: str) -> str | None:
    """The password to write for a primary: "" keeps the file's, None stops

    A file that already holds one is kept, never regenerated: the replicas
    configured with it would stop authenticating.
    """
    if keelcli.secret_exists(path):
        return ""
    question = GENERATE_QUESTION.format(path=path)
    if console.yesno(question, autosize=True) == "ok":
        return keelcli.generate_password()
    typed = passwordbox(console, title, TYPE_PASSWORD.format(path=path))
    if not typed:
        if typed is not None:
            console.msgbox(title, NO_PASSWORD.format(path=path))
        return None
    return typed


def replica_password(console, title: str, path: str) -> str | None:
    """The password to write for a replica: "" keeps the file's, None stops"""
    typed = passwordbox(console, title, PASTE_PASSWORD.format(path=path))
    if typed is None:
        return None
    if not typed and not keelcli.secret_exists(path):
        console.msgbox(title, NO_PASSWORD.format(path=path))
        return None
    return typed


def converge(console, title: str, path: str, may_destroy: bool):
    """Apply the description, and ask before anything is destroyed

    The question repeats keel's own refusal rather than inventing one:
    the refusal an operator confirms has to be the refusal that was made.
    (the result, or None when keel is gone; whether the operator said No)
    """
    argv = keelcli.APPLY + ["--spec", path]
    result = call(console, title, argv)
    if result is None:
        return None, False
    refusal = keelcli.was_refused(result)
    if not refusal or not may_destroy:
        return result, False
    if console.yesno(keelcli.destroy_question(refusal), autosize=True) != "ok":
        return result, True
    return call(console, title, argv + [keelcli.DESTROY]), False


@contextlib.contextmanager
def private_tmp():
    """A temporary directory only root can enter, removed on the way out

    pythondialog and dialog may write what a box holds to temporary files;
    while a password is on screen they go here rather than in /tmp, and
    are gone when the box closes, even when the session drops mid box
    and the exception unwinds through here.
    """
    directory = tempfile.mkdtemp(prefix=PRIVATE_PREFIX)
    saved_env = os.environ.get("TMPDIR")
    saved_module = tempfile.tempdir
    os.environ["TMPDIR"] = directory
    tempfile.tempdir = directory
    try:
        yield directory
    finally:
        tempfile.tempdir = saved_module
        if saved_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved_env
        shutil.rmtree(directory, ignore_errors=True)


def show_secret(console, title: str, text: str) -> None:
    """Show a text that holds a password, never on a command line

    A msgbox hands its text to dialog as an argument, which anybody on the
    machine can read in /proc/PID/cmdline for as long as the box is open.
    A textbox reads a file instead, and the file lives in a private
    directory that is removed when the box closes.
    """
    with private_tmp() as directory:
        where = os.path.join(directory, "handout")
        descriptor = os.open(where, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "w") as fob:
            fob.write(text + "\n")
        height, width = HANDOUT_BOX
        try:
            console.console.textbox(where, height, width, title=title)
        except DialogError:
            # A terminal smaller than the box: the password must still be
            # shown once, so let dialog size the box to what there is.
            console.console.textbox(where, 0, 0, title=title)
