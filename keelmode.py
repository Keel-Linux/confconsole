"""The installation mode of this node, the first step of its first boot.

Handbook decisions 0028 and 0076: the operator chooses one of three
modes, simple, cloud simple or cloud advanced, and the appliance's
manifest says which of them it allows (``modes:``). The screen writes
``appliance.name``, ``installation.mode`` and every overlay of the chain
at that mode's column, the facts keel itself gives
(``keel.manifest.facts.gather``), and applies the description. Nothing
here decides what a mode means: the columns are the manifests', and
every check is ``keel spec validate``'s.

The mode is chosen once. Under keel-init a node that has a mode shows it
and offers one change only, cloud simple to cloud advanced, the move of
decision 0057.

A step with one answer only (an appliance that allows one mode, no
overlay to ask about) runs with no terminal too, so a headless first
boot is not held for a question that has one answer.
"""

import os
import sys
from dataclasses import dataclass

import yaml

import keelcli
import keelmenu

OK = "ok"
ROOT = "/"
APPLIANCES = os.path.join("usr", "share", "keel", "appliances")
SUFFIX = ".yaml"
SIMPLE = "simple"
CLOUD_SIMPLE = "cloud_simple"
CLOUD_ADVANCED = "cloud_advanced"
MODES = (SIMPLE, CLOUD_SIMPLE, CLOUD_ADVANCED)
CLOUD_MODES = (CLOUD_SIMPLE, CLOUD_ADVANCED)
ENABLED = "enabled"
DISABLED = "disabled"
ASK = "ask"
VIP = "vip"

TITLE = "Installation mode"
LABEL = {SIMPLE: "Simple", CLOUD_SIMPLE: "Cloud simple",
         CLOUD_ADVANCED: "Cloud advanced"}
MODE_OF = {label: mode for mode, label in LABEL.items()}
ITEM = {
    SIMPLE: "one node, no mesh",
    CLOUD_SIMPLE: "two nodes, failover by hand",
    CLOUD_ADVANCED: "two nodes and a witness, failover by itself",
}
TEXT = (
    "How this appliance is installed (decision 0028). You choose it once."
    "\n\n"
    "Simple: one node. Everything is on this machine, with no mesh.\n\n"
    "Cloud simple: two nodes, a primary and a replica on a WireGuard"
    " mesh. The data follows the primary. When the primary stops, you"
    " promote the replica by hand.\n\n"
    "Cloud advanced: two data nodes and a witness, three sites, etcd of"
    " three. When the primary stops, the replica takes over by itself.\n\n"
    "Choose the same mode on every node of the set."
)
ASK_TEXT = (
    "Turn on the overlay {name}?\n\n"
    "The appliance's manifest leaves it to you in the {label} mode."
)
APPLIED = "{path}: installation.mode: {mode}\n\n{output}"
HELD = (
    "This node was installed in the {label} mode. The mode is chosen once"
    " (decision 0028), so this screen does not change it."
)
MOVE_TEXT = (
    "This node was installed in the Cloud simple mode.\n\n"
    "Its pair can move to Cloud advanced (decision 0057): etcd of three,"
    " with a witness on a third site, and a failover that runs by itself."
    " Move both nodes of the pair, then add the witness. A move back is"
    " not possible.\n\n"
    "Keep Cloud simple, or move this node to Cloud advanced?"
)
KEEP = "Keep"
MOVE_CHOICES = [
    (KEEP, "stay in Cloud simple"),
    (LABEL[CLOUD_ADVANCED], "etcd of three; move both nodes of the pair"),
]
MOVE_NEXT = (
    "Next:\n\n"
    "  1. Do the same on the other node of the pair.\n"
    "  2. On a node of the pair, invite the witness: confconsole,"
    " Advanced Menu > Instance > Database mode > Cloud > Primary, or"
    " keel mesh invite. The witness is a Keel Core container in the"
    " Cloud advanced mode, with the role Witness.\n"
    "  3. On the node that made the mesh: keel mesh etcd form --dry-run,"
    " then keel mesh etcd form."
)
NO_MANIFEST = (
    "no appliance manifest under {where}, so no mode to choose: a machine"
    " of before decision 0041 keeps the screens it had"
)
SEVERAL = "{names} are installed, and none is built on the other"


@dataclass(frozen=True)
class Facts:
    """What the appliance's chain says about the modes

    `columns` maps each overlay of the chain, in chain order, to its
    state in each mode; `engines` are the data engines of the chain.
    """

    name: str
    modes: tuple[str, ...] = MODES
    witness: bool = False
    columns: dict | None = None
    engines: frozenset = frozenset()


def say(text: str) -> None:
    """What was done or not asked, and why: stderr, which inithooks
    journals"""
    print(f"keelfirstboot mode: {text}", file=sys.stderr)


def section(document: dict, key: str) -> dict:
    found = document.get(key)
    return found if isinstance(found, dict) else {}


def mode_of(document: dict) -> str:
    """The declared installation mode, or "" """
    mode = section(document, "installation").get("mode")
    return mode if mode in MODES else ""


def installed(root: str = ROOT) -> tuple[list[str], str]:
    """The appliance manifests that no other is built on, the top of the
    chain (how keel inspect names the appliance); and why none is one"""
    where = os.path.join(root, APPLIANCES)
    try:
        entries = sorted(os.listdir(where))
    except OSError:
        return [], NO_MANIFEST.format(where=where)
    names, bases = [], set()
    for entry in entries:
        if not entry.endswith(SUFFIX):
            continue
        names.append(entry[: -len(SUFFIX)])
        bases.add(base_of(os.path.join(where, entry)))
    tops = [name for name in names if name not in bases]
    if not tops:
        return [], NO_MANIFEST.format(where=where)
    return tops, ""


def base_of(path: str) -> str:
    """The base a manifest names, or "" when it cannot be read"""
    try:
        with open(path) as fob:
            document = yaml.safe_load(fob)
    except (OSError, yaml.YAMLError):
        return ""
    return str(document.get("base") or "") if isinstance(
        document, dict) else ""


def appliance_name(document: dict, root: str = ROOT) -> tuple[str, str]:
    """The declared appliance, else the one installed; (name, why not)"""
    declared = section(document, "appliance").get("name")
    if declared:
        return str(declared), ""
    tops, problem = installed(root)
    if problem:
        return "", problem
    if len(tops) > 1:
        return "", SEVERAL.format(names=" and ".join(tops))
    return tops[0], ""


def facts_of(document: dict, root: str = ROOT) -> tuple[Facts | None, str]:
    """The facts of this node's appliance, or None and why not"""
    name, problem = appliance_name(document, root)
    if problem:
        return None, problem
    try:
        from keel.manifest.facts import gather
    except ImportError:
        return None, keelcli.NOT_INSTALLED
    try:
        found = gather(root, name)
    except Exception as error:  # a keel that fails is an unknown chain
        return None, f"keel cannot read the chain of {name}: {error}"
    if found.problems or found.resolved is None:
        return None, "; ".join(found.problems) or (
            f"the chain of {name} does not resolve")
    return Facts(name, tuple(found.modes), bool(found.witness),
                 {one: dict(states) for one, states in
                  found.defaults.items()},
                 keelmenu.engines_of(found.resolved)), ""


def column(facts: Facts, mode: str, document: dict,
           answers: dict | None = None) -> dict:
    """Every overlay of the chain at the column of `mode`

    An `ask` takes the operator's answer. A node that declares
    `appliance.vip` keeps the VIP overlay on, which keel needs for it
    (keel.spec.validate_pair): the cloud simple pair that moves to cloud
    advanced is such a node.
    """
    answers = answers or {}
    overlays = {}
    for name, states in (facts.columns or {}).items():
        state = states.get(mode, DISABLED)
        overlays[name] = answers.get(name, state) if state == ASK else state
    if section(document, "appliance").get("vip") and VIP in overlays:
        overlays[VIP] = ENABLED
    return overlays


def asked(facts: Facts, mode: str) -> list[str]:
    """The overlays whose state the operator gives in `mode`"""
    return [name for name, states in (facts.columns or {}).items()
            if states.get(mode) == ASK]


def with_mode(document: dict, facts: Facts, mode: str,
              answers: dict | None = None) -> dict:
    """A new description at `mode`; a copy, never an edit in place"""
    appliance = {**section(document, "appliance"), "name": facts.name}
    installation = {**section(document, "installation"), "mode": mode}
    return {**document, "appliance": appliance,
            "installation": installation,
            "overlays": column(facts, mode, document, answers)}


def record(path: str, document: dict, facts: Facts, mode: str,
           answers: dict | None = None) -> tuple[str, keelcli.Result | None]:
    """Write the mode and apply it: (the problem or "", the apply)"""
    problem = keelcli.save_spec(path, with_mode(document, facts, mode,
                                                answers))
    if problem:
        return problem, None
    try:
        result = keelcli.call(keelcli.APPLY + ["--spec", path])
    except keelcli.KeelNotInstalled as error:
        return str(error), None
    return "", result


def applied_text(path: str, mode: str, problem: str,
                 result: keelcli.Result | None) -> str:
    if problem:
        return problem
    return APPLIED.format(path=path, mode=mode,
                          output=keelcli.apply_text(result))


def unattended(path: str, document: dict) -> int | None:
    """The step when it has one answer, run with or without a terminal:
    its status, or None when the operator must be asked"""
    if mode_of(document):
        return None
    facts, problem = facts_of(document)
    if facts is None:
        say(f"{problem}; not asked")
        return 0
    if len(facts.modes) != 1 or asked(facts, facts.modes[0]):
        return None
    mode = facts.modes[0]
    problem, result = record(path, document, facts, mode)
    if problem:
        say(f"{mode}, the one mode {facts.name} allows, was NOT recorded:"
            f" {problem}")
    else:
        say(f"{mode}, the one mode {facts.name} allows:"
            f" {keelcli.describe_exit('apply', result.code)}")
    return 0


def choose(console, path: str, document: dict) -> None:
    """The screen: the modes the appliance allows, or the mode it has"""
    facts, problem = facts_of(document)
    if facts is None:
        console.msgbox(TITLE, problem, autosize=True)
        return
    if mode_of(document):
        held(console, path, document, facts)
        return
    choices = [(LABEL[mode], ITEM[mode]) for mode in MODES
               if mode in facts.modes]
    code, choice = console.menu(TITLE, TEXT, choices, no_cancel=True,
                                default_item=choices[0][0])
    if code != OK:
        return
    save(console, path, document, facts, MODE_OF[choice])


def save(console, path: str, document: dict, facts: Facts,
         mode: str) -> bool:
    """Ask what the column leaves to the operator, then record and apply;
    whether the mode was recorded"""
    answers = {}
    for name in asked(facts, mode):
        question = ASK_TEXT.format(name=name, label=LABEL[mode])
        answers[name] = ENABLED if console.yesno(
            question, autosize=True) == OK else DISABLED
    problem, result = record(path, document, facts, mode, answers)
    console.msgbox(TITLE, applied_text(path, mode, problem, result),
                   autosize=True)
    return not problem


def held(console, path: str, document: dict, facts: Facts) -> None:
    """keel-init on a node with a mode: shown, and the one move offered"""
    mode = mode_of(document)
    if mode != CLOUD_SIMPLE or CLOUD_ADVANCED not in facts.modes:
        console.msgbox(TITLE, HELD.format(label=LABEL[mode]), autosize=True)
        return
    code, choice = console.menu(TITLE, MOVE_TEXT, MOVE_CHOICES,
                                default_item=KEEP)
    if code != OK or choice == KEEP:
        return
    if save(console, path, document, facts, CLOUD_ADVANCED):
        console.msgbox(TITLE, MOVE_NEXT, autosize=True)
