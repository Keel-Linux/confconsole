"""The first boot screens of a Keel appliance: its mode, its role, then
Keel Cloud.

Handbook decisions 0028 and 0076: the operator chooses the installation
mode first (simple, cloud simple or cloud advanced, as the appliance's
manifest allows), then, in a cloud mode, the role of this node (primary,
replica, and in cloud advanced on Keel Core the witness); an API key for
Keel Cloud is offered last and is never a precondition (decision 0020).

Syntax: python3 /usr/lib/confconsole/keelfirstboot.py mode|role|cloud

The inithooks firstboot hooks ``75keel-role`` (mode, then role) and
``80keel-cloud`` run this. The mode is keelmode's screen; the mesh and
the pair of a cloud node are meshscreen's, the same flows the Database
mode > Cloud entries of confconsole run later. A simple node has no role
screen: a database appliance records ``database.server.role:
standalone``, as before.

A description that declares ``installation.mode``, or
``database.server.role``, or an overlay address, or ``hub.api_key``, or
a preseeded HUB_APIKEY, skips the matching screen, as every other hook
skips what the description declares. keel-init (_TURNKEY_INIT) is an
explicit interactive run and asks again; a mode already chosen is shown
there, with the one move decision 0057 allows.

A step that has one answer runs with no terminal too: an appliance that
allows one mode records it, and a simple node records its role. A step
that has a question and no terminal to ask it on exits DEFERRED, so the
hook can leave it to keel-init (inithooks lib/console.sh,
console_deferred).
"""

import os
import shutil
import sys

import dbscreen
import keelbanner
import keelcli
import keelmenu
import keelmode
import meshscreen

OK = "ok"
MODE = "mode"
ROLE = "role"
CLOUD = "cloud"
USAGE = "Syntax: keelfirstboot.py mode|role|cloud"
BACKTITLE = "Keel Linux - First boot configuration"
TTY = "/dev/tty"
# confconsole's box height, and the rows the back title and the shadow
# take on a terminal smaller than that
FULL_HEIGHT = 25
ROWS_LEFT = 2
EXPLICIT_RUN = "_TURNKEY_INIT"
PRESEED = "HUB_APIKEY"
SKIP = "skip"
# a question with no terminal to ask it on: the hook leaves it to
# keel-init (EX_TEMPFAIL)
DEFERRED = 75
STANDALONE = keelcli.STANDALONE
PRIMARY = keelcli.PRIMARY
REPLICA = keelcli.REPLICA
WITNESS = meshscreen.WITNESS

ROLE_TITLE = meshscreen.ROLE_TITLE
ROLE_TEXT = {
    keelmode.CLOUD_SIMPLE: (
        "What this node is in its set of two (cloud simple).\n\n"
        "Primary: the first node. It makes the mesh and invites the"
        " replica with a line you copy to it.\n\n"
        "Replica: the second node. It joins with that line, and its data"
        " follows the primary."
    ),
    keelmode.CLOUD_ADVANCED: (
        "What this node is in its set of three (cloud advanced).\n\n"
        "Primary: the first node. It makes the mesh and invites the"
        " replica, then the witness, each with a line you copy to it.\n\n"
        "Replica: the second node. It joins with the first line, and its"
        " data follows the primary.\n\n"
        "Witness: the third node, Keel Core on a third site. It joins with"
        " the second line and gives etcd its third vote. It holds no data."
    ),
}
ROLE_OF = {"Primary": PRIMARY, "Replica": REPLICA, "Witness": WITNESS}
LABEL_OF = {role: label for label, role in ROLE_OF.items()}
ROLE_ITEMS = {
    PRIMARY: "the first node: makes the mesh, invites",
    REPLICA: "joins the primary; its data follows it",
    WITNESS: "Keel Core on a third site: a vote, no data",
}
WHERE = "confconsole, Advanced Menu > Instance > "

CLOUD_TITLE = "Keel Cloud API key"
DEFAULT_CLOUD_KEY = "/etc/keel/secrets/cloud_api_key"
CLOUD_TEXT = (
    "Keel Cloud is optional: a standalone appliance has every feature."
    " It will keep this appliance's name pointing at a live node and let"
    " the nodes of a set find each other.\n\n"
    "Paste your API key, or leave the field empty to run standalone. The"
    " key is kept in {path} (root, mode 0600) and the description"
    " references it as hub.api_key.\n\n"
    "The key takes effect once the Keel Cloud service exists; nothing on"
    " this appliance contacts any service now."
)
CLOUD_UNAVAILABLE = (
    "Keel Cloud is not available yet: no key is asked, and this node runs"
    " standalone. It is offered once " + keelmenu.CLOUD_ENDPOINT
    + " names the service."
)
CLOUD_SAVED = "Saved: hub.api_key references {path} (root, mode 0600)."
CLOUD_SKIPPED = "No Keel Cloud key: this node runs standalone."
KEEP = "Keep"
REMOVE = "Remove"
KEY_CHOICES = [
    (KEEP, "keep the key this node has"),
    ("Replace", "type another key"),
    (REMOVE, "no key: this node runs standalone"),
]
CLOUD_HELD = (
    "This node has a Keel Cloud API key: hub.api_key references {path}."
    "\n\nKeep it, replace it, or remove it."
)

NO_TERMINAL = {
    MODE: "no terminal to ask on: keel-init asks the installation mode",
    ROLE: "no terminal to ask on: keel-init asks the role of this cloud"
    " node",
    CLOUD: "no terminal to ask on: no Keel Cloud key, which is standalone;"
    " add one later in " + WHERE + "Keel Cloud",
}


def say(step: str, text: str) -> None:
    """What was not asked, and why: stderr, which inithooks journals"""
    print(f"keelfirstboot {step}: {text}", file=sys.stderr)


def main(argv: list[str], environ=None) -> int:
    environ = os.environ if environ is None else environ
    if len(argv) != 1 or argv[0] not in STEPS:
        print(USAGE, file=sys.stderr)
        return 1
    step = argv[0]
    path = keelcli.spec_path()
    document, problem = keelcli.load_description(path)
    if problem:
        say(step, f"{problem}; not asked")
        return 0
    reason = skip_reason(step, document, environ)
    if reason:
        say(step, reason)
        return 0
    # keel-init is an explicit run: it asks, whatever was preseeded; and
    # SKIP is an answer, never a key to store
    preseeded = "" if environ.get(EXPLICIT_RUN) else environ.get(PRESEED, "")
    if step == CLOUD and preseeded and preseeded.upper() != "SKIP":
        problem = save_key(path, document, preseeded)
        say(step, problem or f"the preseeded {PRESEED} was stored in"
            f" {DEFAULT_CLOUD_KEY}")
        return 0
    if step in UNATTENDED:
        status = UNATTENDED[step](path, document)
        if status is not None:
            return status
    if not draw_on_terminal():
        say(step, NO_TERMINAL[step])
        return 0 if step == CLOUD else DEFERRED
    try:
        STEPS[step](make_console(), path, document)
    except SystemExit:
        # confconsole's console quits on ESC and a Yes to "really
        # quit?": the question is left to keel-init, never dropped
        say(step, "left with ESC: keel-init asks it again")
        return 0 if step == CLOUD else DEFERRED
    return 0


def skip_reason(step: str, document: dict, environ) -> str:
    """Why a step is not asked, or "" when it is"""
    if not shutil.which(keelcli.KEEL):
        return keelcli.NOT_INSTALLED
    if step == CLOUD and not keelmenu.cloud_available():
        return CLOUD_UNAVAILABLE
    if environ.get(EXPLICIT_RUN):
        return ""
    if step == MODE:
        mode = keelmode.mode_of(document)
        return f"installation.mode is declared ({mode})" if mode else ""
    if step == ROLE:
        return role_declared(document)
    if "api_key" in (document.get("hub") or {}):
        return "hub.api_key is declared"
    if environ.get(PRESEED, "").upper() == "SKIP":
        return f"{PRESEED} is SKIP"
    return ""


def role_declared(document: dict) -> str:
    """Why the description already answers the role, or "" """
    role = keelcli.server_of(document).get("role")
    if role:
        return f"database.server.role is declared ({role})"
    overlay = keelmode.section(keelmode.section(
        document, "network"), "overlay")
    address = keelmode.section(overlay, "wireguard").get("address")
    if address and keelmode.mode_of(document) in keelmode.CLOUD_MODES:
        return f"this node is in a mesh already ({address})"
    return ""


def terminal_path(stdin: int, tty: str) -> str:
    """The terminal on standard input, else the controlling one"""
    try:
        return os.ttyname(stdin)
    except OSError:
        return tty


def draw_on_terminal(stdin: int = 0, stdout: int = 1,
                     tty: str = TTY) -> bool:
    """Make sure dialog draws on the terminal; False when there is none

    dialog draws on its standard output, which it inherits. A hook that
    reads this script's output through a pipe would get the screen and
    the operator a frozen console, as happened with dbpass.py of
    keel-mariadb; so standard output becomes the terminal the operator
    answers on, the one on standard input.
    """
    if not os.isatty(stdin):
        return False
    if os.isatty(stdout):
        return True
    try:
        terminal = os.open(terminal_path(stdin, tty),
                           os.O_WRONLY | os.O_NOCTTY)
    except OSError:
        return False
    sys.stdout.flush()
    os.dup2(terminal, stdout)
    os.close(terminal)
    return True


def make_console():
    """confconsole's own console, with the first boot's title

    No taller than the terminal leaves room for: confconsole draws 25
    rows, and an LXC console (lxc-console, pct console) is often 24, on
    which the boxes were drawn over each other.
    """
    import confconsole

    rows, _ = keelbanner.terminal_size()
    return confconsole.Console(
        BACKTITLE, height=min(FULL_HEIGHT, rows - ROWS_LEFT))


# --- the role ------------------------------------------------------------


def unattended_role(path: str, document: dict) -> int | None:
    """The role when it has one answer: a simple node, or a machine of
    before decision 0041, records standalone with or without a terminal.
    A cloud node is asked (None). A node whose mode is not chosen yet
    waits for it: keel-init asks the mode, then the role."""
    mode = keelmode.mode_of(document)
    if mode in keelmode.CLOUD_MODES:
        return None
    if not mode and keelmode.facts_of(document)[0] is not None:
        say(ROLE, "no installation.mode yet: the role follows the mode,"
            " and keel-init asks both")
        return 0
    record_standalone(path, document)
    return 0


def record_standalone(path: str, document: dict) -> None:
    """A simple database appliance is standalone: recorded, not applied"""
    server = keelcli.server_of(document)
    if server.get("role"):
        say(ROLE, f"database.server.role is declared ({server['role']})")
        return
    engine = dbscreen.find_engine(server)
    if not engine:
        say(ROLE, "no database server on this machine, so no role to"
            " record")
        return
    problem = keelcli.save_spec(path, keelcli.with_server(
        document, {**server, "engine": engine, "role": STANDALONE}))
    say(ROLE, problem or f"recorded database.server.role: {STANDALONE}"
        f" ({engine})")


def role_choices(mode: str, facts) -> list[tuple[str, str]]:
    """Primary and Replica; Witness in cloud advanced where the manifest
    says the appliance may be one (Keel Core)"""
    roles = [PRIMARY, REPLICA]
    if mode == keelmode.CLOUD_ADVANCED and facts is not None and (
            facts.witness):
        roles.append(WITNESS)
    return [(LABEL_OF[role], ROLE_ITEMS[role]) for role in roles]


def choose_role(console, path: str, document: dict) -> None:
    """The role of a cloud node, then its flow (meshscreen)"""
    mode = keelmode.mode_of(document)
    if mode not in keelmode.CLOUD_MODES:
        record_standalone(path, document)
        return
    facts, _ = keelmode.facts_of(document)
    declared = keelcli.server_of(document).get("role")
    current = LABEL_OF.get(declared, LABEL_OF[PRIMARY])
    code = ""
    while code != OK:
        # ESC is not an answer: the question stays until it is answered
        code, choice = console.menu(ROLE_TITLE, ROLE_TEXT[mode],
                                    role_choices(mode, facts),
                                    no_cancel=True, default_item=current)
    role = ROLE_OF[choice]
    meshscreen.ROLES[role](console, meshscreen.node_of(path, document,
                                                       facts, role))


# --- the Keel Cloud key --------------------------------------------------


def cloud_screen(console) -> None:
    """The Instance menu entry: the same screen as the first boot's

    keel is asked first, so nobody types a key that cannot be kept.
    The menu hides the entry until Keel Cloud exists; run by name
    (confconsole --plugin) it says so and asks nothing.
    """
    if not keelmenu.cloud_available():
        console.msgbox(CLOUD_TITLE, CLOUD_UNAVAILABLE, autosize=True)
        return
    if dbscreen.call(console, CLOUD_TITLE, ["--version"]) is None:
        return
    path = keelcli.spec_path()
    document, problem = keelcli.load_description(path)
    if problem:
        console.msgbox(CLOUD_TITLE, problem)
        return
    ask_key(console, path, document)


def ask_key(console, path: str, document: dict) -> None:
    """Ask for the key; empty means standalone, Cancel changes nothing

    A node that holds a key keeps it unless the operator chooses Remove:
    Cancel, Keep, or an empty field after Replace leave it as it is, so
    keel-init or Instance > Keel Cloud never throw a key away by
    accident.
    """
    held = (document.get("hub") or {}).get("api_key")
    if isinstance(held, dict):
        code, choice = console.menu(
            CLOUD_TITLE, CLOUD_HELD.format(path=held.get("file")),
            KEY_CHOICES)
        if code != OK or choice == KEEP:
            return
        if choice == REMOVE:
            show_saved(console, save_key(path, document, ""), "")
            return
    typed = dbscreen.passwordbox(
        console, CLOUD_TITLE, CLOUD_TEXT.format(path=DEFAULT_CLOUD_KEY))
    if typed is None or (not typed and isinstance(held, dict)):
        return
    show_saved(console, save_key(path, document, typed), typed)


def show_saved(console, problem: str, key: str) -> None:
    """What saving the key did"""
    if problem:
        console.msgbox(CLOUD_TITLE, problem, autosize=True)
    elif key:
        console.msgbox(CLOUD_TITLE, CLOUD_SAVED.format(
            path=DEFAULT_CLOUD_KEY), autosize=True)
    else:
        console.msgbox(CLOUD_TITLE, CLOUD_SKIPPED, autosize=True)


def save_key(path: str, document: dict, key: str) -> str:
    """Write hub.api_key, the key itself only in its secret file

    Staged and validated before anything is written, as the database
    screens do; the key file is written before the description is
    committed, so the description never references a file that is not
    there, and it is taken back when the commit fails. An empty key is
    `skip`, and the file this screen wrote for an earlier key goes. The
    problem, or "".
    """
    hub = dict(document.get("hub") or {})
    earlier = hub.get("api_key")
    hub["api_key"] = {"file": DEFAULT_CLOUD_KEY} if key else SKIP
    staged, problem = keelcli.stage_spec({**document, "hub": hub}, path)
    if problem:
        return problem
    try:
        result = keelcli.call(["spec", "validate", "--no-secret-files",
                               "--spec", staged])
    except keelcli.KeelNotInstalled as error:
        keelcli.discard_spec(staged)
        return str(error)
    if result.code != keelcli.OK:
        keelcli.discard_spec(staged)
        return keelcli.invalid_text(path, result)
    before = keelcli.read_back(DEFAULT_CLOUD_KEY)
    if key:
        problem = keelcli.write_secret(DEFAULT_CLOUD_KEY, key)
        if problem:
            keelcli.discard_spec(staged)
            return f"{path} was NOT changed.\n\n{problem}"
    problem = keelcli.commit_spec(staged, path)
    if problem:
        keelcli.discard_spec(staged)
        keelcli.restore(DEFAULT_CLOUD_KEY, before)
        return f"{path} was NOT changed.\n\n{problem}"
    if not key and earlier == {"file": DEFAULT_CLOUD_KEY}:
        keelcli.restore(DEFAULT_CLOUD_KEY, None)
    return ""


STEPS = {MODE: keelmode.choose, ROLE: choose_role, CLOUD: ask_key}
UNATTENDED = {MODE: keelmode.unattended, ROLE: unattended_role}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
