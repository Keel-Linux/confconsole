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

import keelcli

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


def ask(console, title: str, text: str, fields: list) -> dict | None:
    """Show the form, prefilled; None when it was cancelled or cannot run

    `fields` is (label, key, label width, field width), in the order the
    role needs them.
    """
    path = keelcli.spec_path()
    document, problem = keelcli.load_spec(path)
    if problem:
        console.msgbox(title, problem)
        return None
    server = keelcli.server_of(document)
    engine = engine_of(console, title, server)
    if not engine:
        return None
    filled = defaults(server)
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


def apply_mode(console, title: str, server: dict, may_destroy: bool = False):
    """Write the role into the description and hand it to keel

    Staged, validated, committed, applied: what the operator typed only
    becomes the description this machine boots from once `keel spec
    validate` has accepted it.
    """
    path = keelcli.spec_path()
    document, problem = keelcli.load_spec(path)
    if problem:
        console.msgbox(title, problem)
        return
    staged, problem = keelcli.stage_spec(
        keelcli.with_server(document, server), path
    )
    if problem:
        console.msgbox(title, problem)
        return
    result = call(console, title, [
        "spec", "validate", "--no-secret-files", "--spec", staged
    ])
    if result is None or result.code != keelcli.OK:
        keelcli.discard_spec(staged)
        if result is not None:
            console.msgbox(
                title, keelcli.invalid_text(path, result), autosize=True
            )
        return
    problem = keelcli.commit_spec(staged, path)
    if problem:
        console.msgbox(title, problem)
        return
    result = converge(console, title, path, may_destroy)
    if result is None:
        return
    console.msgbox(
        title, keelcli.mode_text(server, path, result), autosize=True
    )


def converge(console, title: str, path: str, may_destroy: bool):
    """Apply the description, and ask before anything is destroyed

    The question repeats keel's own refusal rather than inventing one:
    the refusal an operator confirms has to be the refusal that was made.
    """
    argv = keelcli.APPLY + ["--spec", path]
    result = call(console, title, argv)
    if result is None:
        return None
    refusal = keelcli.was_refused(result)
    if not refusal or not may_destroy:
        return result
    if console.yesno(keelcli.destroy_question(refusal), autosize=True) != "ok":
        return result
    return call(console, title, argv + [keelcli.DESTROY])
