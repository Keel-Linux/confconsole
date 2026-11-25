"""The Administrator access screen: what it asks keel and what it says.

Handbook decision 0098: administrators reach a node through its access
network, keel-access, from computers enrolled with `keel access invite`.
The screen only calls keel (list, invite, invites, remove, cancel) and
writes no state itself. No dialog opens and no keel runs: keelcli.call
is replaced, and the plain terminal of the enrolment command is
recorded.
"""

import json
from pathlib import Path

import pytest

import accesscli
import accessscreen
import keelcli
import meshscreen
import plugin
from conftest import FakeConsole

ENTRY = (
    Path(__file__).resolve().parent.parent
    / "plugins.d" / "Instance" / "Admin_access.py"
)
LINE = (
    "f=$(mktemp) && curl -fsS --proto '=https' -k --pinnedpubkey"
    " 'sha256//cGlu' -o \"$f\""
    " 'https://[2001:db8::10]:50123/access/0a1b2c3d4e5f6a7b/enrol.sh'"
    " && printf '%s\\n' 'c2VjcmV0' | sudo sh \"$f\"; rm -f \"$f\""
)
NETWORK = {
    "interface": "keel-access", "address": "fd12:3456:789a:1::1/64",
    "port": 51822, "computers": [
        {"name": "laptop-ana", "address": "fd12:3456:789a:1::5b",
         "enrolled": "2026-11-25", "public_key": "k" * 44,
         "last_handshake": "2026-11-25T18:20:00Z"},
        {"name": "desk", "address": "fd12:3456:789a:1::7",
         "enrolled": "2026-11-24", "public_key": "j" * 44,
         "last_handshake": None},
    ]}
EMPTY = {"interface": "keel-access", "address": "fd12:3456:789a:1::1/64",
         "port": 51822, "computers": []}
NONE = {"interface": None, "computers": []}
INVITES = (
    "0a1b2c3d4e5f6a7b\tlaptop-ana\tfd12:3456:789a:1::5b/128\tuntil"
    " 2026-11-25T18:15:00Z\tTCP 50123\n"
    "1122334455667788\tphone\tfd12:3456:789a:1::9/128\tuntil"
    " 2026-11-25T18:30:00Z\tTCP 50999\n"
)
VALID = ("keel access: valid once, for 15 minutes; paste this line in a"
         " terminal on the computer laptop-ana (Linux or macOS):\n")


def make_result(argv, code=0, stdout="", stderr=""):
    return keelcli.Result(("keel", *argv), code, stdout, stderr)


@pytest.fixture
def keel(monkeypatch):
    """Replace keelcli.call; `calls` records argv, `answers` steer it by
    the command's first words, the rest answer 0 with no output."""
    state = {"calls": [], "answers": {}}

    def fake_call(argv):
        state["calls"].append(list(argv))
        for prefix, outcomes in state["answers"].items():
            if " ".join(argv).startswith(prefix) and outcomes:
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return make_result(argv, *outcome)
        return make_result(argv)

    monkeypatch.setattr(keelcli, "call", fake_call)
    return state


@pytest.fixture
def terminal(monkeypatch):
    """The plain terminal: what is printed, and Enter when it is asked"""
    state = {"printed": [], "prompts": []}
    monkeypatch.setattr(meshscreen, "print_plain",
                        lambda lines: state["printed"].append(list(lines)))
    monkeypatch.setattr(meshscreen, "read_line",
                        lambda prompt: state["prompts"].append(prompt) or "")
    return state


def listed(document):
    return (0, json.dumps(document) + "\n")


def commands(keel):
    return [" ".join(argv) for argv in keel["calls"]]


def messages(console):
    return [call for call in console.calls if call[0] == "msgbox"]


def menus(console):
    return [call for call in console.calls if call[0] == "menu"]


# --- what keel prints, read --------------------------------------------------

class TestRead:
    def test_the_list_becomes_the_network_and_its_computers(self):
        found = accesscli.network_of(json.dumps(NETWORK))

        assert found.interface == "keel-access"
        assert found.address == "fd12:3456:789a:1::1/64"
        assert found.port == "51822"
        assert [one.name for one in found.computers] == ["laptop-ana",
                                                         "desk"]
        assert found.computers[1] == accesscli.Computer(
            "desk", "fd12:3456:789a:1::7", "2026-11-24", "")

    def test_a_node_with_no_access_network(self):
        found = accesscli.network_of(json.dumps(NONE))

        assert found.interface is None
        assert found.computers == ()

    @pytest.mark.parametrize("text", ["", "not json", "[1, 2]", "null"])
    def test_anything_but_a_json_object_is_none(self, text):
        assert accesscli.network_of(text) is None

    def test_an_entry_that_is_not_a_mapping_is_left_out(self):
        document = {**EMPTY, "computers": ["laptop", {"name": "desk"}]}

        found = accesscli.network_of(json.dumps(document))

        assert found.computers == (accesscli.Computer("desk", "", "", ""),)

    def test_the_waiting_enrolments_by_tab(self):
        found = accesscli.enrolments(INVITES)

        assert found == [
            accesscli.Enrolment("0a1b2c3d4e5f6a7b", "laptop-ana",
                                "fd12:3456:789a:1::5b/128",
                                "2026-11-25T18:15:00Z", "50123"),
            accesscli.Enrolment("1122334455667788", "phone",
                                "fd12:3456:789a:1::9/128",
                                "2026-11-25T18:30:00Z", "50999"),
        ]

    @pytest.mark.parametrize("text", [
        "no enrolment waits\n", "", "a\tb\tc\n",
        "id\tname\taddress\tsoon\tTCP 1\n",
    ])
    def test_a_line_that_is_not_an_enrolment_is_left_out(self, text):
        assert accesscli.enrolments(text) == []

    def test_the_command_is_the_last_line_keel_prints(self):
        stdout = ("network.access made: fd12:3456:789a:1::1/64 (decision"
                  " 0098)\n" + LINE + "\n\n")

        assert accesscli.command_line(stdout) == LINE
        assert accesscli.notes(stdout) == [
            "network.access made: fd12:3456:789a:1::1/64 (decision 0098)"]

    def test_no_output_is_no_command(self):
        assert accesscli.command_line(" \n") == ""
        assert accesscli.notes("") == []

    def test_the_minutes_keel_gives(self):
        assert accesscli.minutes(VALID) == 15
        assert accesscli.minutes("") is None

    def test_the_expiry_of_the_enrolment_of_that_name(self):
        found = accesscli.enrolments(INVITES)

        assert accesscli.expiry_of(found, "phone") == "2026-11-25T18:30:00Z"
        assert accesscli.expiry_of(found, "desk") == ""

    def test_the_name_is_one_argument(self):
        assert accesscli.invite_argv("laptop ana") == [
            "access", "invite", "--name=laptop ana"]


# --- what the screen says ----------------------------------------------------

class TestTexts:
    def test_the_clock_of_an_expiry(self):
        assert accesscli.clock("2026-11-25T18:15:00Z") == (
            "18:15:00 UTC on 2026-11-25")
        assert accesscli.clock("soon") == "soon"

    @pytest.mark.parametrize("until, minutes, expected", [
        ("2026-11-25T18:15:00Z", 15,
         "at 18:15:00 UTC on 2026-11-25 (15 minutes from now)"),
        ("2026-11-25T18:15:00Z", None, "at 18:15:00 UTC on 2026-11-25"),
        ("", 15, "in 15 minutes"),
        ("", None, "after the time network.access.token_minutes gives"),
    ])
    def test_when_it_expires(self, until, minutes, expected):
        assert accesscli.expires_text(until, minutes) == expected

    def test_the_enrolment_screen_has_the_command_on_its_own_line(self):
        lines = accesscli.enrol_lines(
            "laptop-ana", LINE, "2026-11-25T18:15:00Z", 15,
            ["network.access made: fd12::1/64 (decision 0098)"])
        text = "\n".join(lines)

        assert LINE in lines
        assert lines[lines.index(LINE) - 1] == ""
        assert lines[lines.index(LINE) + 1] == ""
        assert lines[0] == "Administrator access: add the computer laptop-ana"
        assert "network.access made: fd12::1/64" in text
        assert "ONE USE ONLY" in text
        assert "18:15:00 UTC on 2026-11-25 (15 minutes from now)" in text
        assert "Linux or macOS" in text
        assert "sudo" in text

    def test_the_first_screen_with_computers(self):
        found = accesscli.network_of(json.dumps(NETWORK))

        text = accesscli.main_text(found)

        assert "keel-access" in text
        assert "fd12:3456:789a:1::1/64" in text
        assert "UDP 51822" in text
        assert "Computers: 2" in text

    def test_the_first_screen_before_the_access_network(self):
        text = accesscli.main_text(accesscli.network_of(json.dumps(NONE)))

        assert accesscli.NO_NETWORK in text

    def test_the_computers_screen(self):
        found = accesscli.network_of(json.dumps(NETWORK))

        text = accesscli.computers_text(found)

        assert "laptop-ana" in text
        assert ("address fd12:3456:789a:1::5b, enrolled 2026-11-25,"
                " last handshake 2026-11-25T18:20:00Z") in text
        assert "last handshake none" in text

    def test_the_computers_screen_with_none(self):
        found = accesscli.network_of(json.dumps(EMPTY))

        assert accesscli.NO_COMPUTER in accesscli.computers_text(found)

    def test_the_computers_screen_before_the_access_network(self):
        found = accesscli.network_of(json.dumps(NONE))

        assert accesscli.computers_text(found) == accesscli.NO_NETWORK

    def test_the_menus_name_each_computer_and_enrolment(self):
        found = accesscli.network_of(json.dumps(NETWORK))

        assert accesscli.computer_choices(found) == [
            ("laptop-ana", "enrolled 2026-11-25"),
            ("desk", "enrolled 2026-11-24")]
        assert accesscli.enrolment_choices(
            accesscli.enrolments(INVITES))[0] == (
            "laptop-ana", "until 18:15:00 UTC on 2026-11-25")

    def test_a_keel_run_is_its_command_output_and_verdict(self):
        result = make_result(["access", "remove", "desk"], 24, "",
                             "keel access: refused\n")

        text = accesscli.command_text(result)

        assert text.startswith("$ keel access remove desk\n")
        assert "keel access: refused" in text
        assert "keel access: exit 24, refused: the reason is above" in text


# --- the dialog flow ---------------------------------------------------------

class TestEntry:
    def test_the_entry_runs_the_screen_with_its_console(self, keel,
                                                        monkeypatch):
        seen = []
        monkeypatch.setattr(accessscreen, "run", seen.append)
        loaded = plugin.Plugin(str(ENTRY))
        console = FakeConsole()
        loaded.updateGlobals({"console": console})

        loaded.run()

        assert seen == [console]
        assert loaded.module.TITLE == accesscli.TITLE


class TestFirstScreen:
    def test_it_lists_then_offers_the_four_actions(self, keel):
        keel["answers"]["access list"] = [listed(NETWORK)]
        console = FakeConsole(menus=[("cancel", "")])

        accessscreen.run(console)

        assert commands(keel) == ["access list --json"]
        title, text, choices = menus(console)[0][1:]
        assert title == accesscli.TITLE
        assert "Computers: 2" in text
        assert [tag for tag, _ in choices] == [
            accessscreen.ADD, accessscreen.LIST, accessscreen.REMOVE,
            accessscreen.WAITING]

    def test_no_removal_without_a_computer(self, keel):
        keel["answers"]["access list"] = [listed(NONE)]
        console = FakeConsole(menus=[("cancel", "")])

        accessscreen.run(console)

        assert [tag for tag, _ in menus(console)[0][3]] == [
            accessscreen.ADD, accessscreen.LIST, accessscreen.WAITING]

    def test_a_list_keel_refuses_is_shown_and_ends_the_screen(self, keel):
        keel["answers"]["access list"] = [(2, "", "keel access: bad spec\n")]
        console = FakeConsole()

        accessscreen.run(console)

        assert len(messages(console)) == 1
        assert "keel access: bad spec" in messages(console)[0][2]

    def test_a_list_that_is_not_json_is_shown(self, keel):
        keel["answers"]["access list"] = [(0, "garbage\n")]
        console = FakeConsole()

        accessscreen.run(console)

        assert "printed no JSON object" in messages(console)[0][2]

    def test_no_keel_is_one_message(self, keel):
        keel["answers"]["access list"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole()

        accessscreen.run(console)

        assert messages(console) == [
            ("msgbox", accesscli.TITLE, keelcli.NOT_INSTALLED)]

    def test_after_an_action_the_first_screen_comes_again(self, keel):
        keel["answers"]["access list"] = [listed(NETWORK), listed(NETWORK)]
        console = FakeConsole(menus=[("ok", accessscreen.LIST),
                                     ("cancel", "")])

        accessscreen.run(console)

        assert commands(keel) == ["access list --json"] * 2
        assert "laptop-ana" in messages(console)[0][2]


class TestAddAComputer:
    def run_add(self, keel, inputs, menus_=None):
        keel["answers"].setdefault("access list", [listed(EMPTY)] * 2)
        console = FakeConsole(inputs=inputs, menus=menus_ or [
            ("ok", accessscreen.ADD), ("cancel", "")])
        accessscreen.run(console)
        return console

    def test_the_command_goes_to_the_plain_terminal_with_its_expiry(
            self, keel, terminal):
        keel["answers"]["access list"] = [listed(EMPTY), listed(EMPTY)]
        keel["answers"]["access invite"] = [(0, LINE + "\n", VALID)]
        keel["answers"]["access invites"] = [(0, INVITES)]

        console = self.run_add(keel, [("ok", " laptop-ana ")])

        assert commands(keel)[1:3] == ["access invite --name=laptop-ana",
                                       "access invites"]
        printed = terminal["printed"][0]
        assert LINE in printed
        assert any("18:15:00 UTC on 2026-11-25 (15 minutes from now)" in one
                   for one in printed)
        assert terminal["prompts"] == [meshscreen.PRESS_ENTER]
        # the secret is never in a dialog: its text is on dialog's argv
        assert not any(LINE in str(call) for call in console.calls)

    def test_the_first_enrolment_says_keel_made_the_network(self, keel,
                                                            terminal):
        made = "network.access made: fd12::1/64 (decision 0098)\n"
        keel["answers"]["access invite"] = [(0, made + LINE + "\n", VALID)]
        keel["answers"]["access invites"] = [(0, INVITES)]

        self.run_add(keel, [("ok", "laptop-ana")])

        assert "network.access made: fd12::1/64 (decision 0098)" in (
            terminal["printed"][0])

    def test_without_the_waiting_list_the_minutes_are_given(self, keel,
                                                            terminal):
        keel["answers"]["access invite"] = [(0, LINE + "\n", VALID)]
        keel["answers"]["access invites"] = [(16, "", "keel access: x\n")]

        self.run_add(keel, [("ok", "laptop-ana")])

        assert any("in 15 minutes" in one for one in terminal["printed"][0])

    def test_keel_gone_after_the_invite_still_shows_the_command(
            self, keel, terminal):
        keel["answers"]["access invite"] = [(0, LINE + "\n", VALID)]
        keel["answers"]["access invites"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        self.run_add(keel, [("ok", "laptop-ana")])

        assert LINE in terminal["printed"][0]

    def test_a_refusal_is_keels_words_and_no_command(self, keel, terminal):
        keel["answers"]["access invite"] = [(
            1, "", "keel access: the name desk is in use on this node\n")]

        console = self.run_add(keel, [("ok", "desk")])

        assert terminal["printed"] == []
        text = messages(console)[0][2]
        assert "the name desk is in use" in text
        assert "keel access: exit 1, refused: the reason is above" in text

    def test_an_invite_that_prints_nothing_is_shown(self, keel, terminal):
        keel["answers"]["access invite"] = [(0, "", "")]

        console = self.run_add(keel, [("ok", "desk")])

        assert terminal["printed"] == []
        assert messages(console)[0][2].startswith(
            "$ keel access invite --name=desk")

    def test_no_keel_for_the_invite_ends_quietly(self, keel, terminal):
        keel["answers"]["access invite"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        console = self.run_add(keel, [("ok", "desk")])

        assert terminal["printed"] == []
        assert messages(console) == [
            ("msgbox", accesscli.TITLE, keelcli.NOT_INSTALLED)]

    @pytest.mark.parametrize("answer", [("cancel", "desk"), ("ok", "  ")])
    def test_cancel_or_no_name_asks_keel_nothing(self, keel, terminal,
                                                 answer):
        self.run_add(keel, [answer])

        assert commands(keel) == ["access list --json"] * 2
        assert terminal["printed"] == []

    def test_the_wait_is_said_before_keel_runs(self, keel, terminal):
        keel["answers"]["access invite"] = [(0, LINE + "\n", VALID)]

        console = self.run_add(keel, [("ok", "desk")])

        assert ("infobox", accesscli.WAIT) in console.calls


class TestComputers:
    def test_the_list_is_one_message(self, keel):
        keel["answers"]["access list"] = [listed(NETWORK)]
        console = FakeConsole(menus=[("ok", accessscreen.LIST),
                                     ("cancel", "")])

        accessscreen.run(console)

        title, text = messages(console)[0][1:]
        assert title == accesscli.TITLE
        assert "desk" in text and "laptop-ana" in text


class TestRemoveAComputer:
    def run_remove(self, keel, choice, yesno):
        keel["answers"]["access list"] = [listed(NETWORK), listed(NETWORK)]
        console = FakeConsole(yesno=yesno, menus=[
            ("ok", accessscreen.REMOVE), choice, ("cancel", "")])
        accessscreen.run(console)
        return console

    def test_confirmed_it_is_removed_by_keel(self, keel):
        keel["answers"]["access remove"] = [
            (0, "removed desk: its packets get no answer from now on\n")]

        console = self.run_remove(keel, ("ok", "desk"), ["ok"])

        assert "access remove desk" in commands(keel)
        assert menus(console)[1][3] == [("laptop-ana", "enrolled 2026-11-25"),
                                        ("desk", "enrolled 2026-11-24")]
        assert "Remove the computer desk?" in console.calls[2][1]
        assert "its packets get no answer" in messages(console)[0][2]

    def test_no_at_the_question_removes_nothing(self, keel):
        console = self.run_remove(keel, ("ok", "desk"), ["cancel"])

        assert not any("remove" in one for one in commands(keel))
        assert messages(console) == []

    def test_back_from_the_choice_removes_nothing(self, keel):
        self.run_remove(keel, ("cancel", ""), [])

        assert not any("remove" in one for one in commands(keel))

    def test_no_keel_for_the_removal_ends_quietly(self, keel):
        keel["answers"]["access remove"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        console = self.run_remove(keel, ("ok", "desk"), ["ok"])

        assert messages(console) == [
            ("msgbox", accesscli.TITLE, keelcli.NOT_INSTALLED)]


class TestWaitingEnrolments:
    def run_waiting(self, keel, invites, menus_=(), yesno=()):
        keel["answers"]["access list"] = [listed(EMPTY), listed(EMPTY)]
        keel["answers"]["access invites"] = [invites]
        console = FakeConsole(yesno=list(yesno), menus=[
            ("ok", accessscreen.WAITING), *menus_, ("cancel", "")])
        accessscreen.run(console)
        return console

    def test_cancel_one_by_its_id(self, keel):
        keel["answers"]["access cancel"] = [
            (0, "cancelled the enrolment of phone\n")]

        console = self.run_waiting(keel, (0, INVITES), [("ok", "phone")],
                                   ["ok"])

        assert "access cancel 1122334455667788" in commands(keel)
        assert "Cancel the enrolment of phone?" in console.calls[2][1]
        assert "cancelled the enrolment of phone" in messages(console)[0][2]

    def test_no_at_the_question_cancels_nothing(self, keel):
        self.run_waiting(keel, (0, INVITES), [("ok", "phone")], ["cancel"])

        assert not any("cancel" in one for one in commands(keel))

    def test_back_from_the_list_cancels_nothing(self, keel):
        self.run_waiting(keel, (0, INVITES), [("cancel", "")])

        assert not any("cancel" in one for one in commands(keel))

    def test_none_waits(self, keel):
        console = self.run_waiting(keel, (0, "no enrolment waits\n"))

        assert messages(console)[0][2] == accesscli.NO_ENROLMENT

    def test_a_refusal_is_shown(self, keel):
        console = self.run_waiting(
            keel, (15, "", "keel access invites: must run as root\n"))

        assert "must run as root" in messages(console)[0][2]

    def test_no_keel_for_the_list_ends_quietly(self, keel):
        console = self.run_waiting(
            keel, keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED))

        assert messages(console) == [
            ("msgbox", accesscli.TITLE, keelcli.NOT_INSTALLED)]

    def test_no_keel_for_the_cancel_ends_quietly(self, keel):
        keel["answers"]["access cancel"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        console = self.run_waiting(keel, (0, INVITES), [("ok", "phone")],
                                   ["ok"])

        assert messages(console) == [
            ("msgbox", accesscli.TITLE, keelcli.NOT_INSTALLED)]
