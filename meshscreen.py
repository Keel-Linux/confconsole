"""The mesh and the pair of a cloud node (handbook decision 0076).

The role screen of the first boot, and the Database mode > Cloud
entries, run one of three flows here. Each calls the keel commands of
keel's contract for confconsole (keel docs/mesh.md, "The contract for
confconsole", and docs/vip.md) and reads what they print; nothing here
types a key, an address, a port or a password that keel can give.

- Primary: ``keel mesh create`` when this node has no mesh, then one
  ``keel mesh invite --json`` per node it waits for (the replica, and in
  cloud advanced the witness after it: an invite holds its port, so the
  two follow each other). The line is shown as plain text on one line,
  outside any dialog: a dialog wraps it, and the commissioning driver
  reads the raw terminal. The invite carries the VIP; this node writes it
  as its ``appliance.vip``. Once the replica has paired, it applies and
  takes the VIP (``keel vip promote``).
- Replica: Join a mesh (``keel mesh join -``, the token on standard
  input), the VIP the join received written as ``appliance.vip``, then
  ``keel vip pair`` with the primary (in cloud advanced once etcd has
  three voters), and the apply that replaces the local database, behind
  the question that says so.
- Witness (cloud advanced, Keel Core): it joins and waits for etcd. It
  holds no VIP and no data (decision 0057).

A node with nothing to pair (Keel Core as a primary or a replica) does
the mesh steps only. A pair is a database pair when the chain has an
engine keel replicates, else a pair of files when its mode enables
Syncthing (Keel Web, decision 0076 point 4).

``console`` is passed in, and the terminal is reached through
``print_plain`` and ``read_line``, so the tests drive every flow with a
scripted fake.
"""

import json
import os
import re
import sys
from dataclasses import dataclass

import dbscreen
import keelcli
import keelmenu
import keelmode

OK = "ok"
PRIMARY = keelcli.PRIMARY
REPLICA = keelcli.REPLICA
WITNESS = "witness"
SYNCTHING = "syncthing"
ENABLED = keelmode.ENABLED

ROLE_TITLE = "Role of this node"
MESH_TITLE = "Make the mesh"
INVITE_TITLE = "Invite a node"
JOIN_TITLE = "Join a mesh"
WAIT_TITLE = "Waiting for the nodes"
ACCEPT_TITLE = "Paste accept line"
INVITER_TITLE = "Primary of the pair"
PAIR_TITLE = "Pair with the primary"
VIP_TITLE = "Take the VIP"
STATUS_TITLE = "Status of this node"

STATUS = ["mesh", "status", "--json"]
CREATE = ["mesh", "create"]
INVITE = ["mesh", "invite", "--json"]
JOIN = ["mesh", "join", "-"]
ACCEPT = ["mesh", "accept", "-"]
PAIR = ["vip", "pair"]
PROMOTE = ["vip", "promote"]
DONE_COMMANDS = (["vip", "status"], ["mesh", "status"],
                 ["database", "status"])
# where keel keeps the signed pair record (keel docs/vip.md, "The pair
# record"); the status JSON does not say whether it exists
PAIR_RECORD = "/var/lib/keel/vip/{vip}.pair"
VOTERS = 3
POLL_SECONDS = 5
# an hour of rounds, the life of an invite
WAIT_ROUNDS = 720
PAUSE_BOX = (16, 72)
CLEAR = "\033[H\033[2J"
TOKEN = re.compile(r"keel[0-9]+:[A-Za-z0-9_-]+")
ACCEPT_LINE = re.compile(r"keel[0-9]+a:[A-Za-z0-9_-]+")
CHECK = "Check again"
LATER = "Later"
SHOW_AGAIN = "Show the line"
TAKE_NOW = "Take it now"

INVITE_TEXT = (
    "This node invites {who} into its mesh.\n\n"
    "The next screen shows a line as plain text, on one line. Copy it to"
    " {who}: paste it into its Join a mesh screen, or run it there as"
    " root. It can be used once, until {expires}.\n\n"
    "{vip}"
)
INVITE_VIP = (
    "The line carries the VIP of the pair, {vip}: this node writes it as"
    " its appliance.vip, and the replica takes it from the join. Nobody"
    " types it."
)
INVITE_NO_VIP = "This node holds no VIP: the line carries none."
WHO = {
    (keelmode.CLOUD_SIMPLE, 0): "the replica (node 2)",
    (keelmode.CLOUD_ADVANCED, 0): "the replica (node 2)",
    (keelmode.CLOUD_ADVANCED, 1): "the witness (node 3, Keel Core)",
}
PLAIN_INVITE = (
    "Copy this line to {who}, on one line, as it is. It is a secret: it"
    " lets one node join this mesh."
)
PRESS_ENTER = "Press Enter to go on: "
WAIT_JOIN = (
    "Waiting for {who} to join with the line, checked every {seconds} s."
    " Back gives a menu: Paste accept line, when the join printed one"
    " (keel mesh accept keel1a:...), or the line again."
)
WAIT_ETCD = (
    "Waiting for etcd to have {voters} voters: the primary, the replica"
    " and the witness. etcd forms when the third node joins."
)
WAIT_HOLDER = (
    "Paired. Waiting for the primary to take the VIP: its screen does it"
    " once this node has paired."
)
WAIT_PAIR = (
    "Waiting for the replica to pair with this node (keel vip pair on the"
    " replica). Then this node applies its description and takes the"
    " VIP. If the replica says it paired and nothing moves here, choose"
    " Back and Take it now."
)
NO_VIP = (
    "The invite carries no VIP, so no pair can be made. keel said why:"
    "\n\n{why}"
)
NO_VIP_JOINED = (
    "The join received no VIP, so this node cannot pair. The primary must"
    " be in a cloud mode with its VIP overlay on; run Invite a node there"
    " again and join with the new line."
)
JOIN_TEXT = (
    "Paste the line that Invite a node shows on the inviting node:\n\n"
    "  keel mesh join - <<< keel2:...\n\n"
    "The token alone (keel2:...) is accepted too. It goes to keel on its"
    " standard input, never on a command line."
)
NO_TOKEN = (
    "That is not an invite line: it holds no keel1: or keel2: token. Copy"
    " the whole line that Invite a node shows on the other node."
)
ACCEPT_HERE = (
    "That is an accept line (keel1a:). It goes on the INVITING node, in"
    " its Paste accept line screen. Here, paste the invite line."
)
JOINING = (
    "Join a mesh: keel joins this node to the mesh. When the inviting"
    " node cannot be reached, keel prints a line keel mesh accept"
    " keel1a:... and waits: run that line on the inviting node, or paste"
    " it into its Paste accept line screen."
)
ACCEPT_TEXT = (
    "Paste the line the joining node printed:\n\n"
    "  keel mesh accept keel1a:...\n\n"
    "keel then accepts the node and waits until it confirms."
)
NO_ACCEPT = (
    "That is not an accept line: it holds no keel1a: answer. Copy the"
    " whole line the joining node printed."
)
ACCEPTING = "Paste accept line: keel accepts the node and waits for it."
INVITER_TEXT = (
    "This node has more than one member in its mesh. Which one is the"
    " primary of the pair, the node whose invite this node joined?"
)
NO_MEMBER = (
    "This node has no member in its mesh, so there is no primary to pair"
    " with. Join a mesh first."
)
REPLICA_NOTE = {
    keelmode.CLOUD_SIMPLE: keelcli.NO_FAILOVER,
    keelmode.CLOUD_ADVANCED: keelcli.ADVANCED_FAILOVER,
}
LATER_TEXT = (
    "Not finished yet. What was applied stays. To go on, run keel-init"
    " again{where}."
)
LATER_WHERE = (
    ", or confconsole, Advanced Menu > Instance > Database mode > Cloud >"
    " {entry}"
)
ENTRY = {PRIMARY: "Primary", REPLICA: "Replica"}
TIMED_OUT = "Nothing changed for an hour: the invite has expired."
SIMPLE_NODE = (
    "This node is not in a cloud mode, so it has no mesh and no pair. The"
    " mode is chosen once, at the first boot (decision 0028)."
)


@dataclass(frozen=True)
class Node:
    """The node a flow configures, as its description and chain say"""

    path: str
    mode: str
    role: str
    engine: str = ""
    files: bool = False

    @property
    def pairs(self) -> bool:
        return bool(self.engine or self.files)

    @property
    def advanced(self) -> bool:
        return self.mode == keelmode.CLOUD_ADVANCED

    @property
    def needed(self) -> int:
        """The members the primary waits for"""
        return 2 if self.advanced else 1


def node_of(path: str, document: dict, facts, role: str) -> Node:
    """What pairs on this node: the engine keel replicates, else the
    files when the mode enables Syncthing; nothing on a witness"""
    mode = keelmode.mode_of(document)
    if role == WITNESS:
        return Node(path, mode, role)
    declared = str(keelcli.server_of(document).get("engine") or "")
    chained = facts.engines if facts else frozenset()
    engines = sorted(keelmenu.REPLICATING_ENGINES & chained)
    engine = declared if keelmenu.replicates(declared) else (
        engines[0] if engines else "")
    if not declared and not chained:
        # the chain cannot say (Keel MariaDB adds no overlay that
        # provides its engine): the machine is asked, quietly
        found = dbscreen.find_engine({})
        engine = found if keelmenu.replicates(found) else ""
    columns = (facts.columns or {}) if facts else {}
    files = not engine and columns.get(SYNCTHING, {}).get(mode) == ENABLED
    return Node(path, mode, role, engine, files)


# --- the terminal, outside dialog ------------------------------------------


def print_plain(lines: list[str]) -> None:
    """Lines on the cleared terminal, each as it is: no dialog wraps
    them, so a line of 300 characters reaches the terminal whole"""
    sys.stdout.write(CLEAR + "\n".join(lines) + "\n")
    sys.stdout.flush()


def read_line(prompt: str) -> str:
    """One line from the operator; "" when there is nobody to type it"""
    try:
        return input(prompt)
    except EOFError:
        return ""


def on_terminal(console, title: str, lines: list[str], argv: list[str],
                text: str) -> int | None:
    """Run keel with its output on the terminal; its exit code, or None
    when keel is not installed (the screen then says so)"""
    print_plain(lines + [""])
    try:
        code = keelcli.run_on_terminal(argv, text)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(title, str(error))
        return None
    read_line(PRESS_ENTER)
    return code


# --- what keel says ----------------------------------------------------------


def command_text(result: keelcli.Result) -> str:
    word = result.argv[1] if len(result.argv) > 1 else ""
    return (f"$ {result.command}\n{result.output}\n\n"
            f"{keelcli.describe_exit(word, result.code)}")


def run(console, title: str, argv: list[str]) -> keelcli.Result | None:
    """keel's result, or None when it is not installed or failed, which
    the screen then shows"""
    result = dbscreen.call(console, title, argv)
    if result is None:
        return None
    if result.code != keelcli.OK:
        console.msgbox(title, command_text(result), autosize=True)
        return None
    return result


def as_json(console, title: str, result: keelcli.Result) -> dict | None:
    try:
        found = json.loads(result.stdout)
    except ValueError:
        found = None
    if not isinstance(found, dict):
        console.msgbox(title, f"$ {result.command}\nprinted no JSON"
                       f" object:\n{result.output}", autosize=True)
        return None
    return found


def status(console, title: str) -> dict | None:
    """`keel mesh status --json`, or None after the screen said why"""
    result = run(console, title, STATUS)
    return None if result is None else as_json(console, title, result)


def bare(address) -> str:
    """An overlay address without its prefix length"""
    return str(address or "").split("/")[0]


def members(found: dict) -> list[dict]:
    listed = found.get("members")
    return [one for one in listed if isinstance(one, dict)] if isinstance(
        listed, list) else []


def member_at(found: dict, assigned: str) -> bool:
    """Whether the node invited at `assigned` is a member keel reached"""
    return any(bare(one.get("address")) == bare(assigned)
               and one.get("reachable") is not False
               for one in members(found))


def etcd_of(found: dict) -> dict:
    found = found.get("etcd")
    return found if isinstance(found, dict) else {}


def vip_of(found: dict) -> dict:
    found = found.get("vip")
    return found if isinstance(found, dict) else {}


def etcd_formed(found: dict) -> bool:
    """etcd formed with 3 healthy voters: only then does `keel vip
    promote` get its claim an etcd lease (keel#161)"""
    etcd = etcd_of(found)
    return etcd.get("state") == "formed" and (
        etcd.get("healthy_voters") or 0) >= VOTERS


def holder_known(found: dict) -> bool:
    return bool(vip_of(found).get("holder"))


def paired(vip: str) -> bool:
    return os.path.exists(PAIR_RECORD.format(vip=vip))


def describe(found: dict) -> str:
    """The wait screen's lines: the members, etcd, the VIP"""
    lines = [f"This node: {found.get('address') or '-'}"]
    for one in members(found):
        reached = {True: "reached", False: "not reached"}.get(
            one.get("reachable"), "no handshake yet")
        lines.append(f"Member: {bare(one.get('address'))}, {reached}")
    etcd = etcd_of(found)
    if etcd.get("state") not in (None, "off"):
        lines.append(f"etcd: {etcd.get('state')}, voters"
                     f" {etcd.get('voters') or 0}")
    vip = vip_of(found)
    if vip.get("declared") or vip.get("proposed"):
        lines.append(f"VIP: {vip.get('declared') or vip.get('proposed')},"
                     f" holder {vip.get('holder') or 'none yet'}")
    return "\n".join(lines)


def pause(console, title: str, text: str) -> str:
    """A box that closes by itself after POLL_SECONDS; OK then, or the
    button the operator pressed"""
    height, width = PAUSE_BOX
    return console._wrapper("pause", text, height, width, POLL_SECONDS,
                            title=title)


def wait(console, title: str, intro: str, done, actions=()) -> bool:
    """Ask keel again every POLL_SECONDS until `done` holds; Back opens a
    menu of `actions` (tag, item, action), an action that returns True
    ends the wait as done. False when the operator chose Later."""
    for _ in range(WAIT_ROUNDS):
        found = status(console, title)
        if found is None:
            return False
        if done(found):
            return True
        if pause(console, title,
                 f"{intro}\n\n{describe(found)}") == OK:
            continue
        choices = [(CHECK, "ask keel again now")] + [
            (tag, item) for tag, item, _ in actions] + [
            (LATER, "finish this later")]
        code, choice = console.menu(title, intro, choices)
        if code != OK or choice == LATER:
            return False
        for tag, _, action in actions:
            if choice == tag and action(console):
                return True
    console.msgbox(title, TIMED_OUT, autosize=True)
    return False


def later(console, node: Node) -> None:
    entry = ENTRY.get(node.role) if node.engine else None
    where = LATER_WHERE.format(entry=entry) if entry else ""
    console.msgbox(ROLE_TITLE, LATER_TEXT.format(where=where),
                   autosize=True)


def done(console, node: Node) -> None:
    """What keel says about this node now, read only"""
    shown = []
    for argv in DONE_COMMANDS:
        if argv[0] == "vip" and not node.pairs:
            continue
        if argv[0] == "database" and not node.engine:
            continue
        result = dbscreen.call(console, STATUS_TITLE, argv)
        if result is None:
            return
        shown.append(f"$ {result.command}\n{result.output}")
    console.msgbox(STATUS_TITLE, "\n\n".join(shown), autosize=True)


# --- the description ---------------------------------------------------------


def load(console, title: str, path: str) -> dict | None:
    document, problem = keelcli.load_description(path)
    if problem:
        console.msgbox(title, problem)
        return None
    return document


def save(console, title: str, path: str, document: dict) -> bool:
    problem = keelcli.save_spec(path, document)
    if problem:
        console.msgbox(title, problem, autosize=True)
    return not problem


def with_vip(document: dict, vip: str) -> dict:
    """`appliance.vip` and the VIP overlay on; a copy"""
    appliance = {**keelmode.section(document, "appliance")}
    appliance.setdefault("vip", vip)
    overlays = {**keelmode.section(document, "overlays"),
                keelmode.VIP: ENABLED}
    return {**document, "appliance": appliance, "overlays": overlays}


def pair_server(document: dict, node: Node, own: str,
                inviter: str = "") -> dict:
    """The server of a node of a pair: what it answers on is its overlay
    address too, and the rest (who may replicate, the credential) comes
    from the pair record (keel docs/replication.md)"""
    server = keelcli.server_of(document)
    listen = [str(one) for one in server.get("listen") or
              keelcli.addresses(keelcli.DEFAULT_LISTEN)]
    found = {"engine": node.engine, "role": node.role,
             "listen": list(dict.fromkeys([bare(own), *listen]))}
    if inviter:
        found["replication"] = {"primary": {"host": inviter}}
    return found


def apply(console, title: str, path: str) -> keelcli.Result | None:
    return run(console, title, keelcli.APPLY + ["--spec", path])


# --- the primary -------------------------------------------------------------


def primary(console, node: Node) -> None:
    found = status(console, INVITE_TITLE)
    if found is None:
        return
    if not found.get("in_mesh"):
        if not create(console):
            return
        found = status(console, INVITE_TITLE)
        if found is None:
            return
    if node.pairs and not vip_on(console, node):
        return
    while len(members(found)) < node.needed:
        if not invite(console, node, len(members(found))):
            later(console, node)
            return
        found = status(console, INVITE_TITLE)
        if found is None:
            return
    if node.advanced and not wait(console, WAIT_TITLE, WAIT_ETCD.format(
            voters=VOTERS), etcd_formed):
        later(console, node)
        return
    if node.pairs and not take_vip(console, node):
        later(console, node)
        return
    done(console, node)


def create(console) -> bool:
    console.infobox("keel mesh create: making the mesh...")
    result = dbscreen.call(console, MESH_TITLE, CREATE)
    if result is None:
        return False
    console.msgbox(MESH_TITLE, command_text(result), autosize=True)
    return result.code == keelcli.OK


def vip_on(console, node: Node) -> bool:
    """The VIP overlay on before the first invite, which proposes no VIP
    where it is off (the column of every mode has it off: a witness keeps
    it so)"""
    document = load(console, INVITE_TITLE, node.path)
    if document is None:
        return False
    overlays = keelmode.section(document, "overlays")
    if overlays.get(keelmode.VIP, ENABLED) == ENABLED:
        return True
    return save(console, INVITE_TITLE, node.path, {
        **document, "overlays": {**overlays, keelmode.VIP: ENABLED}})


def invite(console, node: Node, nth: int) -> bool:
    """One invite: made, the VIP written, the line shown, the join
    waited for. Whether the node joined."""
    result = run(console, INVITE_TITLE, INVITE)
    if result is None:
        return False
    made = as_json(console, INVITE_TITLE, result)
    if made is None:
        return False
    if node.pairs:
        if not made.get("vip"):
            console.msgbox(INVITE_TITLE, NO_VIP.format(
                why=result.stderr.strip()), autosize=True)
            return False
        if not declare_primary(console, node, made["vip"]):
            return False
    who = WHO.get((node.mode, nth), "the new node")
    show_line(console, made, who)
    actions = [(ACCEPT_TITLE, "the joining node printed keel1a:...",
                accept),
               (SHOW_AGAIN, "show the invite line again",
                lambda console: show_plain(made, who))]
    return wait(console, WAIT_TITLE, WAIT_JOIN.format(
        who=who, seconds=POLL_SECONDS),
        lambda found: member_at(found, made.get("assigned")), actions)


def declare_primary(console, node: Node, vip: str) -> bool:
    """appliance.vip from the invite, and the primary's server, applied
    before the line is shown: the replica's `keel vip pair` needs the VIP
    declared here, and its seed needs this server on the overlay"""
    document = load(console, INVITE_TITLE, node.path)
    if document is None:
        return False
    found = status(console, INVITE_TITLE)
    if found is None:
        return False
    wanted = with_vip(document, vip)
    if node.engine:
        wanted = keelcli.with_server(wanted, pair_server(
            document, node, found.get("address")))
    if wanted == document:
        return True
    if not save(console, INVITE_TITLE, node.path, wanted):
        return False
    return apply(console, INVITE_TITLE, node.path) is not None


def show_line(console, made: dict, who: str) -> None:
    """What the line is for, in a box; then the line itself, plain"""
    vip = INVITE_VIP.format(vip=made["vip"]) if made.get("vip") else (
        INVITE_NO_VIP)
    console.msgbox(INVITE_TITLE, INVITE_TEXT.format(
        who=who, expires=made.get("expires"), vip=vip), autosize=True)
    show_plain(made, who)


def show_plain(made: dict, who: str) -> bool:
    """The line on one line, never in a dialog: a dialog wraps it, and
    its text is on the command line of the dialog process"""
    lines = [INVITE_TITLE, "", PLAIN_INVITE.format(who=who), "",
             str(made.get("line") or ""), ""]
    if made.get("vip"):
        lines.append(f"VIP: {made['vip']}")
    lines.append(f"Expires: {made.get('expires')}")
    print_plain(lines)
    read_line(PRESS_ENTER)
    return False


def accept(console) -> bool:
    """keel mesh accept -, with the line the joining node printed"""
    typed = ask_line(console, ACCEPT_TITLE, ACCEPT_TEXT)
    if typed is None:
        return False
    found = ACCEPT_LINE.search(typed)
    if found is None:
        console.msgbox(ACCEPT_TITLE, NO_ACCEPT, autosize=True)
        return False
    code = on_terminal(console, ACCEPT_TITLE, [ACCEPTING], ACCEPT,
                       found.group(0) + "\n")
    if code is not None:
        console.msgbox(ACCEPT_TITLE, keelcli.describe_exit("mesh", code),
                       autosize=True)
    return False


def take_vip(console, node: Node) -> bool:
    """Once the replica has paired: apply, then `keel vip promote`. A
    node that holds the VIP already (keel-init again) is left as it is"""
    document = load(console, VIP_TITLE, node.path)
    found = status(console, VIP_TITLE)
    if document is None or found is None:
        return False
    if vip_of(found).get("role") == PRIMARY:
        return True
    vip = str(keelmode.section(document, "appliance").get("vip") or "")
    taken = wait(console, VIP_TITLE, WAIT_PAIR, lambda found: paired(vip),
                 [(TAKE_NOW, "the replica says it paired",
                   lambda console: True)])
    if not taken or apply(console, VIP_TITLE, node.path) is None:
        return False
    result = run(console, VIP_TITLE, PROMOTE)
    if result is None:
        return False
    console.msgbox(VIP_TITLE, command_text(result), autosize=True)
    return True


# --- the replica and the witness ---------------------------------------------


def ask_line(console, title: str, text: str) -> str | None:
    """A pasted line; None when cancelled. In a private directory, as a
    password box is: the line is a secret"""
    with dbscreen.private_tmp():
        code, typed = console.inputbox(title, text)
    return typed.strip() if code == OK else None


def join(console) -> bool:
    """Join a mesh: the line pasted, `keel mesh join -`; whether it
    joined"""
    while True:
        typed = ask_line(console, JOIN_TITLE, JOIN_TEXT)
        if typed is None:
            return False
        if ACCEPT_LINE.search(typed):
            console.msgbox(JOIN_TITLE, ACCEPT_HERE, autosize=True)
            continue
        token = TOKEN.search(typed)
        if token is None:
            console.msgbox(JOIN_TITLE, NO_TOKEN, autosize=True)
            continue
        code = on_terminal(console, JOIN_TITLE, [JOIN_TITLE, "", JOINING],
                           JOIN, token.group(0) + "\n")
        if code is None:
            return False
        if code == keelcli.OK:
            return True
        console.msgbox(JOIN_TITLE, keelcli.describe_exit("mesh", code),
                       autosize=True)
        if code != keelcli.MESH_LINE_BAD:
            return False


def joined(console, node: Node) -> dict | None:
    """The status of a node in the mesh, joining it first when it is not
    in one; None when it is not"""
    found = status(console, JOIN_TITLE)
    if found is None or found.get("in_mesh"):
        return found
    if not join(console):
        later(console, node)
        return None
    return status(console, JOIN_TITLE)


def inviter_of(console, found: dict) -> str:
    """The primary's overlay address: the one member when there is one
    (the replica joins before the witness), else the operator's choice"""
    addresses = [bare(one.get("address")) for one in members(found)]
    if not addresses:
        console.msgbox(INVITER_TITLE, NO_MEMBER, autosize=True)
        return ""
    if len(addresses) == 1:
        return addresses[0]
    code, choice = console.menu(INVITER_TITLE, INVITER_TEXT,
                                [(one, "member") for one in addresses])
    return choice if code == OK else ""


def replica(console, node: Node) -> None:
    found = joined(console, node)
    if found is None:
        return
    inviter = inviter_of(console, found) if node.pairs else ""
    if node.pairs and not inviter:
        return
    if node.advanced and not wait(console, WAIT_TITLE, WAIT_ETCD.format(
            voters=VOTERS), etcd_formed):
        later(console, node)
        return
    if node.pairs and not pair_replica(console, node, inviter):
        return
    done(console, node)


def pair_replica(console, node: Node, inviter: str) -> bool:
    """The VIP the join received, the server, `keel vip pair`, the
    apply; whether the pair is applied"""
    found = status(console, PAIR_TITLE)
    document = load(console, PAIR_TITLE, node.path)
    if found is None or document is None:
        return False
    vip = vip_of(found).get("declared") or vip_of(found).get("proposed")
    if not vip:
        console.msgbox(PAIR_TITLE, NO_VIP_JOINED, autosize=True)
        return False
    wanted = with_vip(document, vip)

    def step(console) -> bool:
        return pair(console, inviter)

    if not node.engine:
        if not save(console, PAIR_TITLE, node.path, wanted) or not step(
                console):
            return False
        result = apply(console, PAIR_TITLE, node.path)
        if result is not None:
            console.msgbox(PAIR_TITLE, keelcli.apply_text(result),
                           autosize=True)
        return result is not None
    if console.yesno(keelcli.replica_warning(inviter),
                     autosize=True) != OK:
        later(console, node)
        return False
    server = pair_server(document, node, found.get("address"), inviter)
    return dbscreen.apply_mode(
        console, PAIR_TITLE, server, may_destroy=True, document=wanted,
        before_apply=step, note=REPLICA_NOTE[node.mode]) is not None


def pair(console, inviter: str) -> bool:
    """`keel vip pair` with the primary, then the wait for it to take the
    VIP, which the replica's seed needs"""
    result = run(console, PAIR_TITLE, PAIR + [inviter])
    if result is None:
        return False
    console.msgbox(PAIR_TITLE, command_text(result), autosize=True)
    return wait(console, PAIR_TITLE, WAIT_HOLDER, holder_known)


def witness(console, node: Node) -> None:
    found = joined(console, node)
    if found is None:
        return
    if not wait(console, WAIT_TITLE, WAIT_ETCD.format(voters=VOTERS),
                etcd_formed):
        later(console, node)
        return
    done(console, node)


ROLES = {PRIMARY: primary, REPLICA: replica, WITNESS: witness}


def from_menu(console, role: str) -> None:
    """Database mode > Cloud > Primary or Replica: the first boot's flow"""
    path = keelcli.spec_path()
    document = load(console, ROLE_TITLE, path)
    if document is None:
        return
    if keelmode.mode_of(document) not in keelmode.CLOUD_MODES:
        console.msgbox(ROLE_TITLE, SIMPLE_NODE, autosize=True)
        return
    facts, _ = keelmode.facts_of(document)
    ROLES[role](console, node_of(path, document, facts, role))

