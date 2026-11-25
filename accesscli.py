"""What the Administrator access screen reads and says, without a dialog.

Handbook decision 0098: an administrator reaches a node only through its
access network, the WireGuard interface keel-access, from a computer
enrolled with `keel access invite`. keel owns every part of it: the
section network.access of the instance spec, the enrolment, the one-use
command, the list and the removal. The screen (``accessscreen.py``,
``plugins.d/Instance/Admin_access.py``) only calls keel and shows
what keel printed; it writes no state itself. Everything here is pure: it
reads keel's output and composes the text of each screen.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime

import keelcli

TITLE = "Administrator access"
LIST = ["access", "list", "--json"]
INVITES = ["access", "invites"]
REMOVE = ["access", "remove"]
CANCEL = ["access", "cancel"]
# the verdict of describe_exit for each keel access command
VERDICT = "access"
# what `keel access invites` prints in each row: id, name, address,
# "until <UTC>", "TCP <port>"
UNTIL = "until "
EXPIRES_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
CLOCK = "%H:%M:%S UTC on %Y-%m-%d"
VALID_FOR = re.compile(r"valid once, for (\d+) minutes")

ABOUT = (
    "Administrators reach the services of this node through its access"
    " network: a private WireGuard network between this node and the"
    " computers added here (decision 0098). Nothing else reaches those"
    " services."
)
NO_NETWORK = (
    "No access network yet. Add a computer makes it, then gives the"
    " command to paste on that computer."
)
NO_COMPUTER = "No computer yet: choose Add a computer."
NO_ENROLMENT = "No enrolment waits: each command was used, or expired."
NAME_TEXT = (
    "The name of the computer, for example laptop-ana: 1 to 32 of the"
    " letters a-z, the digits 0-9 and -.\n\n"
    "keel then gives one command to paste on that computer."
)
WAIT = (
    "keel makes the enrolment. The first one also makes the access"
    " network, which can take a minute."
)


@dataclass(frozen=True)
class Computer:
    """One computer on the access network, as keel lists it"""

    name: str
    address: str
    enrolled: str
    last_handshake: str


@dataclass(frozen=True)
class Network:
    """The access network of this node; interface None before the first
    enrolment"""

    interface: str | None
    address: str
    port: str
    computers: tuple


@dataclass(frozen=True)
class Enrolment:
    """An enrolment whose command was not used yet"""

    invite_id: str
    name: str
    address: str
    until: str
    port: str


def text_of(value) -> str:
    return "" if value is None else str(value)


def network_of(text: str) -> Network | None:
    """`keel access list --json` read; None when it is not a JSON object"""
    try:
        found = json.loads(text)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    computers = tuple(
        Computer(text_of(one.get("name")), text_of(one.get("address")),
                 text_of(one.get("enrolled")),
                 text_of(one.get("last_handshake")))
        for one in found.get("computers") or [] if isinstance(one, dict))
    return Network(found.get("interface"), text_of(found.get("address")),
                   text_of(found.get("port")), computers)


def enrolments(text: str) -> list[Enrolment]:
    """`keel access invites` read: its rows by tab; any other line, "no
    enrolment waits" among them, is left out"""
    found = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 5 or not fields[3].startswith(UNTIL):
            continue
        found.append(Enrolment(fields[0], fields[1], fields[2],
                               fields[3][len(UNTIL):],
                               fields[4].removeprefix("TCP ")))
    return found


def invite_argv(name: str) -> list[str]:
    """The name as one argument: keel, not the screen, refuses a bad one"""
    return ["access", "invite", f"--name={name}"]


def _lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.strip()]


def command_line(stdout: str) -> str:
    """The command to paste: the last line keel prints on standard output"""
    found = _lines(stdout)
    return found[-1] if found else ""


def notes(stdout: str) -> list[str]:
    """What keel printed before the command ("network.access made: ...")"""
    return _lines(stdout)[:-1]


def minutes(stderr: str) -> int | None:
    found = VALID_FOR.search(stderr)
    return int(found.group(1)) if found else None


def expiry_of(found: list[Enrolment], name: str) -> str:
    return next((one.until for one in found if one.name == name), "")


def clock(until: str) -> str:
    """An expiry as a clock time, or as keel printed it"""
    try:
        return datetime.strptime(until, EXPIRES_FORMAT).strftime(CLOCK)
    except ValueError:
        return until


def expires_text(until: str, valid: int | None) -> str:
    if until and valid is not None:
        return f"at {clock(until)} ({valid} minutes from now)"
    if until:
        return f"at {clock(until)}"
    if valid is not None:
        return f"in {valid} minutes"
    return "after the time network.access.token_minutes gives"


def enrol_lines(name: str, line: str, until: str, valid: int | None,
                said: list[str]) -> list[str]:
    """The enrolment screen, on the plain terminal: the command holds a
    one-use secret, and a dialog would put it on its own command line"""
    return [
        f"{TITLE}: add the computer {name}", "", *said,
        *([""] if said else []),
        f"On the computer {name} (Linux or macOS), open a terminal and"
        " paste this one command. It needs wg-quick, curl and openssl, and"
        " sudo asks for the password of that computer.", "",
        line, "",
        "ONE USE ONLY: the command works one time. It expires"
        f" {expires_text(until, valid)}. After that, add the computer"
        " again for a new command.",
        "The command holds a secret: keep it private until it is used.",
        "When the command finishes, the computer shows in Computers.", "",
    ]


def main_text(network: Network) -> str:
    if network.interface is None:
        return f"{ABOUT}\n\n{NO_NETWORK}"
    return (f"{ABOUT}\n\nAccess network: {network.interface},"
            f" {network.address}, UDP {network.port}\n"
            f"Computers: {len(network.computers)}")


def computers_text(network: Network) -> str:
    if network.interface is None:
        return NO_NETWORK
    lines = [f"Access network: {network.interface}, {network.address},"
             f" UDP {network.port}", ""]
    for one in network.computers:
        lines += [one.name, f"  address {one.address}, enrolled"
                  f" {one.enrolled}, last handshake"
                  f" {one.last_handshake or 'none'}"]
    return "\n".join(lines if network.computers else lines + [NO_COMPUTER])


def computer_choices(network: Network) -> list[tuple[str, str]]:
    """The name is the tag: no address beside it, which a name of 32
    characters would push past 80 columns"""
    return [(one.name, f"enrolled {one.enrolled}")
            for one in network.computers]


def enrolment_choices(found: list[Enrolment]) -> list[tuple[str, str]]:
    return [(one.name, f"until {clock(one.until)}") for one in found]


def remove_question(name: str) -> str:
    return (f"Remove the computer {name}?\n\nkeel takes it off the access"
            " network at once: its packets get no answer from then on. To"
            " use it again, add it again.")


def cancel_question(name: str) -> str:
    return (f"Cancel the enrolment of {name}?\n\nIts command stops working"
            " at once.")


def command_text(result: keelcli.Result) -> str:
    """A keel run: the command, what keel printed, and its verdict"""
    return (f"$ {result.command}\n{result.output}\n\n"
            f"{keelcli.describe_exit(VERDICT, result.code)}")
