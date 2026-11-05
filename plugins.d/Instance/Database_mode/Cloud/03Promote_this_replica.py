"""Make this replica the primary"""

import dbscreen
import keelcli

TITLE = "Cloud: promote this replica"
QUESTION = (
    "Promote THIS node to a primary?\n\n"
    "It stops replicating and forgets the primary it followed. Nothing"
    " here stops the old primary or tells any other machine, so if the"
    " old primary is still running you will have two writable servers"
    " holding one dataset, and the writes they take will diverge.\n\n"
    "Only do this when you know the old primary is gone.\n\n"
    "Afterwards the description still says replica while the machine"
    " says primary, which keel diff reports as drift. Change the"
    " description with the Primary screen to settle it.\n\n"
    + keelcli.NO_FAILOVER
)
PAIR_TEXT = (
    "Promote THIS node to the primary of its pair?\n\n"
    "keel moves the VIP to this node first (keel database promote, keel"
    " docs/vip.md), and the database follows the VIP.\n\n"
    "Planned: the old primary is running. It drops the VIP, then this"
    " node takes it. keel refuses when the old primary does not"
    " answer.\n\n"
    "Old primary gone: you KNOW the old primary is down for good. keel"
    " does not wait for its answer (--old-primary-gone). If it is alive"
    " after all, without etcd nothing fences it, and its writes diverge."
)
PLANNED = "Planned"
GONE = "Old primary gone"
CHOICES = [
    (PLANNED, "the old primary hands the VIP over"),
    (GONE, "the old primary is down for good"),
]
OLD_PRIMARY_GONE = "--old-primary-gone"


def paired() -> bool:
    """Whether this node is one of a pair: the description has a VIP"""
    document, _ = keelcli.load_description(keelcli.spec_path())
    appliance = document.get("appliance")
    return isinstance(appliance, dict) and bool(appliance.get("vip"))


def run():
    pair = paired()
    argv = ["database", "promote"]
    if pair:
        code, choice = console.menu(TITLE, PAIR_TEXT, CHOICES,
                                    default_item=PLANNED)
        if code != "ok":
            return
        if choice == GONE:
            argv.append(OLD_PRIMARY_GONE)
    elif console.yesno(QUESTION, autosize=True) != "ok":
        return
    result = dbscreen.call(console, TITLE, argv)
    if result is None:
        return
    console.msgbox(TITLE, keelcli.promote_text(result, paired=pair),
                   autosize=True)
