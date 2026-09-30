"""The first boot screens of a Keel appliance: its role, then Keel Cloud.

Handbook decision 0020: the role is chosen at installation, by hand, on
each LXC or VM (standalone, primary or replica), and lives in the
instance description as ``database.server.role``; an API key for Keel
Cloud is offered at installation and is never a precondition.

Syntax: python3 /usr/lib/confconsole/keelfirstboot.py role|cloud

The inithooks firstboot hooks ``75keel-role`` and ``80keel-cloud`` run
this. Nothing here is a second copy of a confconsole screen: a primary or
a replica goes through the Overlay network screen's own actions
(``wgscreen``) and the Database mode screens themselves, loaded the way
confconsole loads them, in the order the set needs them. A step that
needs the other node can be left with Later, and the screen says which
confconsole entry finishes it; the role is written to the description
only by the Database mode screen, once keel has validated it, so a step
left before that leaves a node that is still standalone. Once written,
the description holds the role chosen (decision 0020), even when the
apply that follows it did not finish: the screen shows keel's verdict,
and running it again converges it.

Each overlay change comes up under the confirmation window of decision
0018, and the Overlay network screen offers to confirm it from here.
keel accepts that because the first boot runs on the machine's console
(inithooks.service draws on /dev/tty1, a pct console or lxc-console
attaches to it, and keel reads the terminal of the process tree, not the
environment). It is sound at first boot: the window exists so that a
change cannot lock the operator out, and the overlay screen never moves
the uplink (--skip-uplink), so the console the operator is typing on is
the path the change cannot break. What a console confirmation does not
test, the overlay itself and SSH over the uplink, is what the screens
ask the operator to test from the other node.

A description that already declares ``database.server.role``, or
``hub.api_key``, or a preseeded HUB_APIKEY, skips the matching screen, as
every other hook skips what the description declares. keel-init
(_TURNKEY_INIT) is an explicit interactive run and asks again.
"""

import os
import shutil
import sys

import dbscreen
import keelbanner
import keelcli
import plugin
import wgcli
import wgscreen

OK = "ok"
ROLE = "role"
CLOUD = "cloud"
USAGE = "Syntax: keelfirstboot.py role|cloud"
BACKTITLE = "Keel - First boot configuration"
TTY = "/dev/tty"
# confconsole's box height, and the rows the back title and the shadow
# take on a terminal smaller than that
FULL_HEIGHT = 25
ROWS_LEFT = 2
EXPLICIT_RUN = "_TURNKEY_INIT"
PRESEED = "HUB_APIKEY"
SKIP = "skip"
STANDALONE = keelcli.STANDALONE
PRIMARY = keelcli.PRIMARY
REPLICA = keelcli.REPLICA
HERE = os.path.dirname(os.path.realpath(__file__))
MODE_DIR = os.path.join(HERE, "plugins.d", "Instance", "Database_mode")
SCREENS = {
    STANDALONE: "01Standalone.py",
    PRIMARY: os.path.join("Cloud", "01Primary.py"),
    REPLICA: os.path.join("Cloud", "02Replica.py"),
}

ROLE_TITLE = "Role of this node"
ROLE_TEXT = (
    "What this node is in its appliance. Standalone is the default: one"
    " machine, what the appliance has always been. Choose it unless you"
    " are building a replicated set.\n\n"
    "Primary and Replica build that set, one node at a time: first the"
    " private WireGuard network between the nodes, then the database's"
    " mode. Each step needs details from the other node, and each can be"
    " left and finished later in confconsole."
)
# the menu's words, and the role each one is in the description
ROLE_OF = {"Standalone": STANDALONE, "Primary": PRIMARY, "Replica": REPLICA}
ROLE_CHOICES = [
    ("Standalone", "one machine (default)"),
    ("Primary", "other nodes replicate from this one"),
    ("Replica", "this node replicates from another"),
]
WHERE = "confconsole, Advanced Menu > Instance > "
OVERLAY_WHERE = "Overlay network"
MODE_WHERE = {
    PRIMARY: "Database mode > Cloud > Primary",
    REPLICA: "Database mode > Cloud > Replica",
}
CONTINUE = "Continue"
LATER = "Later"
OVERLAY_INTRO = {
    PRIMARY: (
        "Step 1 of 2: the overlay, a private WireGuard network between"
        " the nodes of the set.\n\n"
        "Set this node's overlay address first. A primary is usually"
        " installed before its replicas, so it has no peer yet: Continue"
        " without one. Each replica's first boot shows its public key and"
        " overlay address; add them here later with " + WHERE
        + OVERLAY_WHERE + " > Add peer.\n\n"
        "Each change comes up under keel's confirmation window and"
        " reverts unless it is confirmed. The screen offers to confirm"
        " from here: keel accepts it because this is the machine's"
        " console, which a change of the overlay cannot cut off."
    ),
    REPLICA: (
        "Step 1 of 2: the overlay, a private WireGuard network between"
        " the nodes of the set.\n\n"
        "Set this node's overlay address on the primary's /64 (::2, ::3"
        " and so on), then add the primary as a peer: its public key and"
        " overlay address as its own " + OVERLAY_WHERE + " screen shows"
        " them, and its endpoint, [its address]:51820. Continue appears"
        " once the primary is a peer.\n\n"
        "Each change comes up under keel's confirmation window and"
        " reverts unless it is confirmed. The screen offers to confirm"
        " from here: keel accepts it because this is the machine's"
        " console, which a change of the overlay cannot cut off."
    ),
}
PRIMARY_NEXT = (
    "Step 2 of 2: the database mode of this primary.\n\n"
    "'Allow replication from' takes each replica's overlay address, one"
    " by one. With no replica yet, leave it empty: once a replica is a"
    " peer, open " + WHERE + MODE_WHERE[PRIMARY] + " again and add it.\n\n"
    "The screen then shows what each replica needs, and a replication"
    " password it shows ONCE: keep it for each replica's first boot."
)
REPLICA_READY = (
    "Step 2 of 2: the database mode of this replica. It needs the"
    " primary to accept this node first. On the PRIMARY, in {where}:\n\n"
    "  1. " + OVERLAY_WHERE + " > Add peer, with this node's\n"
    "     public key: {key}\n"
    "     overlay address: {address}\n"
    "     endpoint: blank (this node reaches the primary)\n"
    "  2. " + MODE_WHERE[PRIMARY] + ": add {address} to 'Allow"
    " replication from'.\n\n"
    "The next screen asks for the replication password: use the password"
    " shown when it was generated on the primary, or read it from"
    " {secret} there.\n\n"
    "Then, on the next screen, 'Replicate from' is the primary's overlay"
    " address: {peers}.\n\n"
    "Go on now? Answer No to finish later with " + WHERE
    + MODE_WHERE[REPLICA] + " on this node."
)
DONE = {
    PRIMARY: (
        "The description says this node is the primary. The screen before"
        " showed what keel did; if it did not finish, run "
        + MODE_WHERE[PRIMARY] + " again in confconsole.\n\n"
        "For each replica: add it with " + WHERE + OVERLAY_WHERE
        + " > Add peer, using the key and overlay address its first boot"
        " shows, then allow its overlay address in " + MODE_WHERE[PRIMARY]
        + "."
    ),
    REPLICA: (
        "The description says this node is a replica. The screen before"
        " showed what keel did; if it did not finish, because the primary"
        " did not accept this node yet, run " + WHERE + MODE_WHERE[REPLICA]
        + " again once it does."
    ),
}
LATER_TEXT = (
    "The description names no role yet, so this node is still"
    " standalone. What was already applied stays.\n\n"
    "To finish, in " + WHERE.rstrip("> ") + ":"
)
LATER_REPLICA = (
    "The primary must accept this node first: on the primary, add this"
    " node as a peer and allow its overlay address."
)

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
    ROLE: "no terminal to ask on: this node stays standalone; choose its"
    " role later in " + WHERE + "Database mode",
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
    if not draw_on_terminal():
        say(step, NO_TERMINAL[step])
        return 0
    STEPS[step](make_console(), path, document)
    return 0


def skip_reason(step: str, document: dict, environ) -> str:
    """Why a step is not asked, or "" when it is"""
    if not shutil.which(keelcli.KEEL):
        return keelcli.NOT_INSTALLED
    if environ.get(EXPLICIT_RUN):
        return ""
    if step == ROLE:
        role = keelcli.server_of(document).get("role")
        return f"database.server.role is declared ({role})" if role else ""
    if "api_key" in (document.get("hub") or {}):
        return "hub.api_key is declared"
    if environ.get(PRESEED, "").upper() == "SKIP":
        return f"{PRESEED} is SKIP"
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


def choose_role(console, path: str, document: dict) -> None:
    server = keelcli.server_of(document)
    engine = find_engine(server)
    if not engine:
        say(ROLE, "no database server on this machine, so no role to"
            " choose: it stays standalone")
        return
    text = ROLE_TEXT
    if server.get("role"):
        text += f"\n\nThe description says: {server['role']}."
    current = {role: label for label, role in ROLE_OF.items()}.get(
        server.get("role"), "Standalone")
    code, choice = console.menu(ROLE_TITLE, text, ROLE_CHOICES,
                                no_cancel=True, default_item=current)
    if code != OK:
        return
    ROLES[ROLE_OF[choice]](console, path, document, server, engine)


def find_engine(server: dict) -> str:
    """The declared engine, else the one keel inspect finds, quietly"""
    declared = str(server.get("engine") or "")
    if declared:
        return declared
    return dbscreen.observed_engine()[0]


def standalone(console, path: str, document: dict, server: dict,
               engine: str) -> None:
    """Record the default, or go back to it through its own screen

    A fresh node is standalone already, so the role is written and
    nothing is applied. A node the description makes a primary or a
    replica (keel-init asks again) is changed by the Standalone screen,
    which applies it.
    """
    role = server.get("role")
    if not role:
        recorded = {**server, "engine": engine, "role": STANDALONE}
        wgscreen.commit(console, path,
                        keelcli.with_server(document, recorded), ROLE_TITLE)
    elif role != STANDALONE:
        run_screen(console, STANDALONE)


def primary(console, path: str, document: dict, server: dict,
            engine: str) -> None:
    if overlay(console, path, PRIMARY) is None:
        later(console, PRIMARY, overlay_done=False)
        return
    console.msgbox(ROLE_TITLE, PRIMARY_NEXT, autosize=True)
    run_screen(console, PRIMARY)
    finish(console, path, PRIMARY)


def replica(console, path: str, document: dict, server: dict,
            engine: str) -> None:
    key = overlay(console, path, REPLICA)
    if key is None:
        later(console, REPLICA, overlay_done=False)
        return
    current, _ = keelcli.load_description(path)
    if console.yesno(replica_ready_text(key, current), autosize=True) != OK:
        later(console, REPLICA, overlay_done=True)
        return
    run_screen(console, REPLICA)
    finish(console, path, REPLICA)


def replica_ready_text(key: str, document: dict) -> str:
    wireguard = wgcli.overlay_of(document)
    address = str(wireguard.get("address") or "").split("/")[0]
    peers = ", ".join(wgcli.peer_addresses(document))
    return REPLICA_READY.format(where=WHERE.rstrip("> "), key=key,
                                address=address, peers=peers,
                                secret=keelcli.DEFAULT_SECRET)


def overlay(console, path: str, role: str) -> str | None:
    """The overlay step: this node's key once it may go on, else None"""
    console.msgbox(wgcli.TITLE, OVERLAY_INTRO[role], autosize=True)
    key = wgscreen.public_key(console, path)
    if key is None:
        return None
    while True:
        document, problem = keelcli.load_description(path)
        if problem:
            console.msgbox(wgcli.TITLE, problem)
            return None
        wireguard = wgcli.overlay_of(document)
        code, choice = console.menu(
            wgcli.TITLE, wgcli.overlay_text(key, wireguard),
            overlay_choices(role, wireguard),
        )
        if code != OK or choice == LATER:
            return None
        if choice == CONTINUE:
            return key
        wgscreen.ACTIONS[choice](console, path, document, wireguard)


def overlay_choices(role: str, wireguard: dict) -> list[tuple[str, str]]:
    """An address first; a replica goes on only with its primary a peer"""
    later_choice = (LATER, "finish this in confconsole")
    if not wireguard.get("address"):
        return [(wgscreen.ADDRESS, "this node's overlay address and port"),
                later_choice]
    found = []
    if role == PRIMARY or wgcli.peers(wireguard):
        found.append((CONTINUE, "on to the database mode"))
    return found + [
        (wgscreen.ADD, "accept another node: its key, address, endpoint"),
        (wgscreen.ADDRESS, "change this node's address or port"),
        later_choice,
    ]


def run_screen(console, role: str) -> None:
    """A Database mode screen, loaded and run the way confconsole does"""
    screen = plugin.Plugin(os.path.join(MODE_DIR, SCREENS[role]))
    screen.updateGlobals({"console": console})
    screen.module.run()


def finish(console, path: str, role: str) -> None:
    """Done when the description holds the role, else what is left"""
    document, _ = keelcli.load_description(path)
    if keelcli.server_of(document).get("role") == role:
        console.msgbox(ROLE_TITLE, DONE[role], autosize=True)
    else:
        later(console, role, overlay_done=True)


def later(console, role: str, overlay_done: bool) -> None:
    lines = [LATER_TEXT]
    if not overlay_done:
        lines.append(f"  {OVERLAY_WHERE}: this node's address and peers")
    lines.append(f"  {MODE_WHERE[role]}")
    if role == REPLICA:
        lines += ["", LATER_REPLICA]
    console.msgbox(ROLE_TITLE, "\n".join(lines), autosize=True)


# --- the Keel Cloud key --------------------------------------------------


def cloud_screen(console) -> None:
    """The Instance menu entry: the same screen as the first boot's

    keel is asked first, so nobody types a key that cannot be kept.
    """
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


STEPS = {ROLE: choose_role, CLOUD: ask_key}
ROLES = {STANDALONE: standalone, PRIMARY: primary, REPLICA: replica}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
