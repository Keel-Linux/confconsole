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
    "This screen sets THIS node's side only. On each other node, add this"
    " node as a peer: its public key, mesh address and endpoint."
)
# the peers the first screen lists before it says how many more there are
LISTED = 3
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


OWN_KEY = (
    "That is this node's own public key, the one at the top of the"
    " overlay screen. A node is never its own peer: enter the OTHER"
    " node's key, as that node's own Overlay network screen shows it."
)
OWN_ADDRESS = (
    "{address} is this node's own mesh address. Enter the OTHER node's"
    " mesh address, as that node's own screen shows it (::2, ::3 on"
    " this node's /64)."
)
OUTSIDE = (
    "{peer} is outside this node's mesh prefix, {network} (this node is"
    " {address}).\n\nThe nodes of a set normally share one /64: the"
    " first node's, the others taking ::2, ::3 on it. A peer is routed"
    " as one host (/128), so this still works.\n\nAdd it anyway?"
)
# the fields of the overlay that hold this node's own addresses
OWN_FIELDS = ("address", "ipv4_address")


def interface_of(text: str):
    """An address with or without its prefix, or None when it is not one"""
    try:
        return ipaddress.ip_interface(str(text).strip())
    except ValueError:
        return None


def own_interfaces(wireguard: dict) -> list:
    """This node's overlay addresses, each with its prefix"""
    found = (interface_of(wireguard.get(name) or "") for name in OWN_FIELDS)
    return [one for one in found if one is not None]


def peer_problem(own_key: str, wireguard: dict, key: str,
                 address: str) -> str:
    """Why a peer is this node itself, or "" when it is not

    Only what is this node's own is refused here; anything else that is
    wrong (a key that is not one, an address that does not parse) is
    keel's to refuse, in its own words, when the description is staged.
    """
    if key.strip() and key.strip() == own_key.strip():
        return OWN_KEY
    peer = interface_of(address)
    for own in own_interfaces(wireguard):
        if peer is not None and peer.ip == own.ip:
            return OWN_ADDRESS.format(address=own.ip)
    return ""


def outside_prefix(wireguard: dict, address: str) -> str:
    """The question to ask when a peer is outside this node's prefix

    "" when it is inside one of them, or when either side is not an
    address yet. keel routes a peer by /128 (host_prefix), so a peer on
    another prefix still works; it is asked about because it is most
    often a node of another set, or a typo.
    """
    peer = interface_of(address)
    own = own_interfaces(wireguard)
    if peer is None or not own:
        return ""
    if any(peer.ip in one.network for one in own):
        return ""
    return OUTSIDE.format(peer=peer.ip, network=own[0].network,
                          address=own[0])


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


def routed(peer: dict) -> str:
    """The addresses a peer routes, which name it on the overlay"""
    return ", ".join(str(one) for one in peer.get("allowed_ips") or []) or "-"


def peer_choices(wireguard: dict) -> list[tuple[str, str]]:
    """The remove menu: the key is the tag, the routed addresses the text

    No endpoint: a 44 column key beside it did not fit an 80 column
    console. View spec shows the endpoints.
    """
    return [(str(peer.get("public_key", "?")), routed(peer))
            for peer in peers(wireguard)]


def overlay_text(public_key: str, wireguard: dict) -> str:
    """The first screen: this node, then its peers, then what it is for

    One line a peer, and no more than LISTED of them when there are
    more, so that the menu under the text keeps its rows on an 80x24
    console; Remove peer lists every one.
    """
    port = wireguard.get("listen_port") or DEFAULT_PORT
    lines = [
        f"This node's public key: {public_key}",
        "Mesh address (not your LAN):"
        f" {wireguard.get('address') or NO_ADDRESS}  UDP port: {port}",
        "",
    ]
    found = peers(wireguard)
    shown = found if len(found) <= LISTED else found[:LISTED - 1]
    if found:
        lines.append(f"Peers ({len(found)}):")
        lines += [f"  {peer.get('public_key', '?')}  {routed(peer)}"
                  for peer in shown]
    else:
        lines.append("No peer yet.")
    if len(shown) < len(found):
        lines.append(f"  and {len(found) - len(shown)} more: Remove peer"
                     " lists every one")
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
