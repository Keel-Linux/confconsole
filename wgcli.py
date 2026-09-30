"""What the overlay screen builds and says, without a dialog.

Decision 0020 of the handbook, step 2: the WireGuard overlay the nodes of
a replicated appliance share is ``network.overlay.wireguard`` in the
instance description, converged by ``keel spec apply --system-only``
under the confirmation window of decision 0018. The screen
(``wgscreen.py``, ``plugins.d/Instance/Overlay_network.py``) shows this
node's public key and overlay address, adds or removes a peer, and hands
the description to keel. Everything here is pure: it builds new
descriptions from old ones and composes the text of each screen. What a
field means, and every refusal, is keel's (``docs/spec.md`` and
``docs/apply.md`` of the keel repository).
"""

import ipaddress

import keelcli

TITLE = "Overlay network (WireGuard)"
KEY = ["network", "wireguard", "key"]
SUGGEST = ["network", "wireguard", "suggest-address"]
CONFIRM = ["network", "confirm"]
# Unlike the database screens (keelcli.APPLY), this one exists to change
# the network: no --skip-network, so keel brings the overlay up under the
# window. --skip-uplink keeps network.interfaces out of the run, so what
# this screen applies never moves the interface the operator came in on.
# The certificate is still not asked for from here.
APPLY = [
    "spec", "apply", "--system-only", "--non-interactive",
    "--defer-certificate", "--skip-uplink",
]
DEFAULT_PORT = 51820
DEFAULT_KEEPALIVE = "25"
# what apply prints for a network change it brought up, overlay or
# uplink, and that now waits: the change's line, carried out
UNDER_WINDOW = "reverts in"
DONE = ": done"
# what keel says when it refuses a change because another one waits
WAITING = "waiting for its confirmation"
# what keel says when a change failed and so did putting the old file
# back: the marker and the timer stay, and the change still reverts
STILL_ARMED = "the revert timer will try again"
NO_ADDRESS = "(none yet: choose Address first)"
THIS_NODE = (
    "This screen configures THIS node's side of the overlay only. On the"
    " other node, open this screen too and add this node as its peer:"
    " this node's public key, its overlay address, and the address and"
    " port it can be reached at."
)
CONFIRM_HOW = (
    "The change REVERTS BY ITSELF when its window ends (120 seconds unless"
    " apply was told otherwise) unless it is confirmed. Confirm from a NEW"
    " session: from the other node over the overlay (ssh to this node's"
    " overlay address, which also tests the overlay), or over this node's"
    " usual address, then run: keel network confirm. A session that was"
    " open before the change cannot confirm it."
)
CONFIRM_QUESTION = (
    "Confirm the change from here?\n\nkeel accepts it from the machine's"
    " own console. From an SSH session opened before the change it refuses,"
    " and the change reverts unless a new session confirms it.\n\n"
    "Answer No to confirm from a new session instead."
)


def overlay_of(document: dict) -> dict:
    """What the description declares for this node's overlay, if anything"""
    network = document.get("network") or {}
    overlay = network.get("overlay") if isinstance(network, dict) else None
    wireguard = overlay.get("wireguard") if isinstance(overlay, dict) else None
    return wireguard if isinstance(wireguard, dict) else {}


def with_overlay(document: dict, wireguard: dict) -> dict:
    """A new description with network.overlay.wireguard replaced; a copy"""
    network = dict(document.get("network") or {})
    overlay = dict(network.get("overlay") or {})
    overlay["wireguard"] = wireguard
    network["overlay"] = overlay
    return {**document, "network": network}


def number(text: str):
    """A typed number as an int, anything else as typed for keel to judge"""
    digits = text.strip()
    return int(digits) if digits.isdigit() else digits


def with_address(wireguard: dict, address: str, port: str) -> dict:
    """This node's overlay address and port; a blank port is the default"""
    changed = {**wireguard, "address": address.strip()}
    if port.strip():
        changed["listen_port"] = number(port)
    else:
        changed.pop("listen_port", None)
    return changed


def host_prefix(address: str) -> str:
    """The other node's overlay address as the one-host prefix it routes

    `fd00:6b65:1::2` and `fd00:6b65:1::2/64` both become
    `fd00:6b65:1::2/128`: what is routed to a node is its own address,
    not the /64 the nodes share. Anything that is not an address is left
    as typed, and keel's validation says why.
    """
    text = address.strip()
    try:
        value = ipaddress.ip_interface(text).ip
    except ValueError:
        return text
    return f"{value}/{value.max_prefixlen}"


def peer_entry(public_key: str, endpoint: str, address: str,
               keepalive: str) -> dict:
    """One peer as the description holds it; blank fields are left out"""
    peer: dict = {"public_key": public_key.strip()}
    if endpoint.strip():
        peer["endpoint"] = endpoint.strip()
    peer["allowed_ips"] = [host_prefix(address)]
    if keepalive.strip():
        peer["persistent_keepalive"] = number(keepalive)
    return peer


def peers(wireguard: dict) -> list:
    found = wireguard.get("peers") or []
    return [peer for peer in found if isinstance(peer, dict)]


def peer_addresses(document: dict) -> list[str]:
    """The overlay address of every declared peer, one host each

    What a primary's 'Allow replication from' offers: each replica by its
    address, compressed the way MariaDB compares it. A peer's routed
    range is not one replica, and keel refuses an IPv6 prefix MariaDB
    cannot hold, fd3d:80b2:d0d7::/64 among them, so only a /128 or a /32
    counts.
    """
    found = []
    for peer in peers(overlay_of(document)):
        routed = peer.get("allowed_ips")
        for one in routed if isinstance(routed, list) else []:
            try:
                network = ipaddress.ip_network(str(one), strict=False)
            except ValueError:
                continue
            if network.num_addresses == 1:
                found.append(str(network.network_address))
    return found


def with_peer(wireguard: dict, peer: dict) -> dict:
    """The peer added, or put in place of the one with the same key"""
    kept = [one for one in peers(wireguard)
            if one.get("public_key") != peer["public_key"]]
    return {**wireguard, "peers": kept + [peer]}


def without_peer(wireguard: dict, public_key: str) -> dict:
    kept = [one for one in peers(wireguard)
            if one.get("public_key") != public_key]
    return {**wireguard, "peers": kept}


def peer_line(peer: dict) -> str:
    """How a peer is shown: its addresses and where it is reached"""
    routed = ", ".join(str(one) for one in peer.get("allowed_ips") or [])
    endpoint = peer.get("endpoint") or "reaches this node itself"
    return f"{routed or '-'} at {endpoint}"


def peer_choices(wireguard: dict) -> list[tuple[str, str]]:
    """The remove menu: the key is the tag, the addresses the text"""
    return [(str(peer.get("public_key", "?")), peer_line(peer))
            for peer in peers(wireguard)]


def overlay_text(public_key: str, wireguard: dict) -> str:
    """The first screen: this node, then its peers, then what it is for"""
    port = wireguard.get("listen_port") or DEFAULT_PORT
    lines = [
        f"This node's public key: {public_key}",
        f"Overlay address: {wireguard.get('address') or NO_ADDRESS}",
        f"Listen port: {port}",
        "",
    ]
    found = peers(wireguard)
    if found:
        lines.append(f"Peers ({len(found)}):")
        lines += [f"  {peer.get('public_key', '?')}\n    {peer_line(peer)}"
                  for peer in found]
    else:
        lines.append("No peer yet.")
    return "\n".join(lines + ["", THIS_NODE])


def is_pending(result: keelcli.Result) -> bool:
    """Whether a network change waits for its confirmation after apply

    One this run brought up (its line carried out, whatever failed after
    it), the overlay's or the uplink's; one that failed and could not be
    rolled back either, which keel leaves armed; or one an earlier run
    left, which keel names when it refuses another. A change that failed
    and was rolled back waits for nothing, and one only planned was never
    made.
    """
    return any(
        WAITING in line or STILL_ARMED in line
        or (UNDER_WINDOW in line and line.endswith(DONE))
        for line in result.output.splitlines()
    )


def applied_text(result: keelcli.Result) -> str:
    """What apply said, its verdict, and how to keep the change"""
    text = (f"$ {result.command}\n{result.output}\n\n"
            f"{keelcli.describe_exit('apply', result.code)}")
    if is_pending(result):
        text += f"\n\n{CONFIRM_HOW}"
    return text


def command_text(name: str, result: keelcli.Result) -> str:
    """Any other keel run of this screen: the command, output, verdict"""
    return (f"$ {result.command}\n{result.output}\n\n"
            f"{keelcli.describe_exit(name, result.code)}")
