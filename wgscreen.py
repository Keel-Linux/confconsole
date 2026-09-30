"""The dialog flow of the overlay screen (handbook decision 0020).

The entry ``plugins.d/Instance/Overlay_network.py`` only calls ``run``.
This module shows this node's public key and overlay address, asking
``keel network wireguard key`` for the key (which makes the key pair on
first use), collects an address or a peer, writes it into the instance
description through the same stage, validate and commit as the database
screens (``dbscreen.commit``), and hands the description to ``keel spec
apply --system-only``. keel brings the overlay up under the confirmation
window of decision 0018; the screen then says how to confirm, and offers
to confirm from here, which keel accepts from a console only.

``console`` is passed in, so each function is tested with a scripted
fake and no dialog opens.
"""

import dbscreen
import keelcli
import wgcli

OK = "ok"
ADDRESS = "Address"
ADD = "Add peer"
REMOVE = "Remove peer"
ADDRESS_TEXT = (
    "This node's address on the overlay: IPv6 with its /64, a unique local"
    " address (fd00::/8). The first node of a set takes the suggested one,"
    " ::1 on a fresh /64; the others take ::2, ::3 on the SAME /64.\n\n"
    "The port is where the other nodes reach this one (blank: 51820)."
)
PEER_TEXT = (
    "Another node this one accepts on the overlay, as that node's own"
    " screen shows it.\n\n"
    "Endpoint: where that node is reached, host:port, an IPv6 address in"
    " brackets ([2001:db8::20]:51820); blank when it reaches this node"
    " instead. Keepalive: seconds, keeps a path through a firewall or NAT"
    " open (blank: none).\n\n" + wgcli.THIS_NODE
)


def run(console) -> None:
    """The screen: this node's key and address, then what to change"""
    path = keelcli.spec_path()
    key = public_key(console, path)
    if key is None:
        return
    while True:
        document, problem = wgcli.load(path)
        if problem:
            console.msgbox(wgcli.TITLE, problem)
            return
        wireguard = wgcli.overlay_of(document)
        code, choice = console.menu(
            wgcli.TITLE, wgcli.overlay_text(key, wireguard),
            choices(wireguard),
        )
        if code != OK:
            return
        ACTIONS[choice](console, path, document, wireguard)


def choices(wireguard: dict) -> list[tuple[str, str]]:
    """No peer before an address; no removal without a peer"""
    found = [(ADDRESS, "this node's overlay address and port")]
    if not wireguard.get("address"):
        return found
    found.append((ADD, "accept another node: its key, address, endpoint"))
    if wgcli.peers(wireguard):
        found.append((REMOVE, "stop accepting a node"))
    return found


def public_key(console, path: str) -> str | None:
    """This node's public key from keel, the pair made on first use"""
    result = dbscreen.call(console, wgcli.TITLE, wgcli.KEY + ["--spec", path])
    if result is None:
        return None
    key = result.stdout.strip()
    if result.code != keelcli.OK or not key:
        console.msgbox(wgcli.TITLE, wgcli.command_text("key", result),
                       autosize=True)
        return None
    return key


def suggested(console) -> str:
    """A fresh unique local address from keel, or blank"""
    result = dbscreen.call(console, wgcli.TITLE, wgcli.SUGGEST)
    if result is None or result.code != keelcli.OK:
        return ""
    return result.stdout.strip()


def ask(console, text: str, fields: list) -> list | None:
    code, values = console.form(
        wgcli.TITLE, text, dbscreen.format_fields(fields), autosize=True
    )
    return values if code == OK else None


def set_address(console, path: str, document: dict, wireguard: dict):
    address = str(wireguard.get("address") or suggested(console))
    port = str(wireguard.get("listen_port") or "")
    values = ask(console, ADDRESS_TEXT, [
        ("Overlay address", address, 20, 44),
        ("Listen port", port, 20, 44),
    ])
    if values is None:
        return
    apply(console, path, wgcli.with_overlay(
        document, wgcli.with_address(wireguard, *values)))


def add_peer(console, path: str, document: dict, wireguard: dict):
    values = ask(console, PEER_TEXT, [
        ("Its public key", "", 20, 46),
        ("Its overlay address", "", 20, 46),
        ("Its endpoint", "", 20, 46),
        ("Keepalive (seconds)", wgcli.DEFAULT_KEEPALIVE, 20, 46),
    ])
    if values is None:
        return
    key, address, endpoint, keepalive = values
    peer = wgcli.peer_entry(key, endpoint, address, keepalive)
    apply(console, path, wgcli.with_overlay(
        document, wgcli.with_peer(wireguard, peer)))


def remove_peer(console, path: str, document: dict, wireguard: dict):
    code, key = console.menu(
        wgcli.TITLE, "Stop accepting which node?",
        wgcli.peer_choices(wireguard),
    )
    if code != OK:
        return
    question = (f"Remove the peer {key}?\n\nThis node stops accepting it"
                " on the overlay once the change is confirmed.")
    if console.yesno(question, autosize=True) != OK:
        return
    apply(console, path, wgcli.with_overlay(
        document, wgcli.without_peer(wireguard, key)))


def apply(console, path: str, document: dict) -> None:
    """Commit the description, converge it, and see the change kept"""
    if not dbscreen.commit(console, wgcli.TITLE, path, document):
        return
    result = dbscreen.call(console, wgcli.TITLE,
                           keelcli.APPLY + ["--spec", path])
    if result is None:
        return
    console.msgbox(wgcli.TITLE, wgcli.applied_text(result), autosize=True)
    if not wgcli.is_pending(result):
        return
    if console.yesno(wgcli.CONFIRM_QUESTION, autosize=True) != OK:
        return
    confirmed = dbscreen.call(console, wgcli.TITLE, wgcli.CONFIRM)
    if confirmed is not None:
        console.msgbox(wgcli.TITLE, wgcli.command_text("confirm", confirmed),
                       autosize=True)


ACTIONS = {ADDRESS: set_address, ADD: add_peer, REMOVE: remove_peer}
