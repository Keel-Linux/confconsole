"""The dialog flow of the Administrator access screen (decision 0098).

The entry ``plugins.d/Instance/Admin_access.py`` only calls
``run``. The first screen asks ``keel access list --json`` and offers:
Add a computer (a name, then ``keel access invite``, and the one command
to paste on that computer, with its expiry), Computers (the list),
Remove a computer (``keel access remove`` after a question) and Waiting
enrolments (``keel access invites``, and ``keel access cancel`` after a
question). keel does every change; this screen writes no file.

The enrolment command holds a one-use secret. It goes to the plain
terminal, as the invite line of meshscreen does, never into a dialog:
the text of a dialog is on the command line of the dialog process, and
a dialog wraps a long line.

``console`` is passed in, so each function is tested with a scripted
fake and no dialog opens.
"""

import accesscli
import dbscreen
import keelcli
import meshscreen

OK = "ok"
ADD = "Add a computer"
LIST = "Computers"
REMOVE = "Remove a computer"
WAITING = "Waiting enrolments"


def run(console) -> None:
    """The first screen, again after each action, until Back"""
    while True:
        network = listed(console)
        if network is None:
            return
        code, choice = console.menu(accesscli.TITLE,
                                    accesscli.main_text(network),
                                    choices(network))
        if code != OK:
            return
        ACTIONS[choice](console, network)


def choices(network: accesscli.Network) -> list[tuple[str, str]]:
    """No removal without a computer"""
    found = [(ADD, "give the command that adds a computer"),
             (LIST, "the computers on the access network")]
    if network.computers:
        found.append((REMOVE, "take a computer off the access network"))
    found.append((WAITING, "commands not used yet: list, cancel"))
    return found


def done(console, argv: list[str]) -> keelcli.Result | None:
    """keel's result when it succeeded; else None, after the screen said
    why (keel not installed, or keel's own words and verdict)"""
    result = dbscreen.call(console, accesscli.TITLE, argv)
    if result is None:
        return None
    if result.code != keelcli.OK:
        console.msgbox(accesscli.TITLE, accesscli.command_text(result),
                       autosize=True)
        return None
    return result


def listed(console) -> accesscli.Network | None:
    result = done(console, accesscli.LIST)
    if result is None:
        return None
    network = accesscli.network_of(result.stdout)
    if network is None:
        console.msgbox(accesscli.TITLE, f"$ {result.command}\nprinted no"
                       f" JSON object:\n{result.output}", autosize=True)
    return network


def add(console, network: accesscli.Network) -> None:
    """A name, the enrolment, and its command on the plain terminal"""
    code, name = console.inputbox(accesscli.TITLE, accesscli.NAME_TEXT, "")
    name = name.strip()
    if code != OK or not name:
        return
    console.infobox(accesscli.WAIT)
    result = done(console, accesscli.invite_argv(name))
    if result is None:
        return
    line = accesscli.command_line(result.stdout)
    if not line:
        console.msgbox(accesscli.TITLE, accesscli.command_text(result),
                       autosize=True)
        return
    meshscreen.print_plain(accesscli.enrol_lines(
        name, line, expiry(console, name), accesscli.minutes(result.stderr),
        accesscli.notes(result.stdout)))
    meshscreen.read_line(meshscreen.PRESS_ENTER)


def expiry(console, name: str) -> str:
    """When the enrolment of `name` expires, from keel; "" when keel did
    not say, and the minutes keel gave stand alone"""
    result = dbscreen.call(console, accesscli.TITLE, accesscli.INVITES)
    if result is None or result.code != keelcli.OK:
        return ""
    return accesscli.expiry_of(accesscli.enrolments(result.stdout), name)


def computers(console, network: accesscli.Network) -> None:
    console.msgbox(accesscli.TITLE, accesscli.computers_text(network),
                   autosize=True)


def remove(console, network: accesscli.Network) -> None:
    code, name = console.menu(accesscli.TITLE,
                              "Take which computer off the access network?",
                              accesscli.computer_choices(network))
    if code != OK:
        return
    if console.yesno(accesscli.remove_question(name), autosize=True) != OK:
        return
    said(console, accesscli.REMOVE + [name])


def waiting(console, network: accesscli.Network) -> None:
    result = done(console, accesscli.INVITES)
    if result is None:
        return
    found = accesscli.enrolments(result.stdout)
    if not found:
        console.msgbox(accesscli.TITLE, accesscli.NO_ENROLMENT)
        return
    code, name = console.menu(
        accesscli.TITLE, "Commands not used yet. Choose one to cancel it.",
        accesscli.enrolment_choices(found))
    if code != OK:
        return
    if console.yesno(accesscli.cancel_question(name), autosize=True) != OK:
        return
    chosen = next(one for one in found if one.name == name)
    said(console, accesscli.CANCEL + [chosen.invite_id])


def said(console, argv: list[str]) -> None:
    """Run keel and show what it said, whatever its verdict"""
    result = dbscreen.call(console, accesscli.TITLE, argv)
    if result is not None:
        console.msgbox(accesscli.TITLE, accesscli.command_text(result),
                       autosize=True)


ACTIONS = {ADD: add, LIST: computers, REMOVE: remove, WAITING: waiting}
