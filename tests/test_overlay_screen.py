"""The overlay screen: what it builds, stages, applies and says.

Handbook decision 0020, step 2. The screen shows this node's public key
and overlay address, adds and removes peers in the instance description
and hands it to keel, which brings the overlay up under the window of
decision 0018. No dialog opens and, except in the last class, no keel
runs: keelcli.call is replaced. The last class hands the descriptions
the screen builds to a real `keel spec validate` when one is on PATH.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import keelcli
import plugin
import wgcli
import wgscreen
from conftest import FakeConsole

ENTRY = (
    Path(__file__).resolve().parent.parent
    / "plugins.d" / "Instance" / "Overlay_network.py"
)
THIS_KEY = "d+/mhJ0q/+k98Qcrm0cE/3nDyD+zg3KbaFaMMOTAvVw="
PEER_KEY = "0niNkgzhpbKmTSrWCzukb6jaYogKZkGhW+xWlh52Mh8="
OTHER_KEY = "nb9/izIukqWXM7gnBpe7hki4jKZZChWOW1wEfONn82E="
BASE = {"version": 1, "instance": {"hostname": "node1"}}
OVERLAY = {
    "address": "fd00:6b65:1::1/64",
    "peers": [{"public_key": PEER_KEY, "allowed_ips": ["fd00:6b65:1::2/128"],
               "endpoint": "[2001:db8::20]:51820"}],
}
APPLIED = (
    "network.overlay: bring the overlay wg0 up on a new"
    " /etc/wireguard/wg0.conf (wg-quick down, then up); it reverts in 120 s"
    " unless `keel network confirm` is run from a new session: done\n"
)


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
    state["answers"]["network wireguard key"] = [(0, THIS_KEY + "\n")]
    return state


@pytest.fixture
def spec(tmp_path, monkeypatch):
    path = tmp_path / "instance.yaml"
    monkeypatch.setenv("KEEL_SPEC", str(path))

    def _write(document):
        path.write_text(yaml.safe_dump(document))
        return path

    return _write


def read(path):
    return yaml.safe_load(Path(path).read_text())


def commands(keel):
    return [" ".join(argv[:3]) for argv in keel["calls"]]


class TestBuild:
    def test_overlay_of_reads_only_a_mapping(self):
        assert wgcli.overlay_of({}) == {}
        assert wgcli.overlay_of({"network": []}) == {}
        assert wgcli.overlay_of({"network": {"overlay": 1}}) == {}
        assert wgcli.overlay_of({"network": {"overlay": {
            "wireguard": "x"}}}) == {}
        assert wgcli.overlay_of({"network": {"overlay": {
            "wireguard": OVERLAY}}}) == OVERLAY

    def test_with_overlay_is_a_copy_that_keeps_the_rest(self):
        document = {**BASE, "network": {"managed_by": "host"}}
        found = wgcli.with_overlay(document, OVERLAY)
        assert found["network"] == {"managed_by": "host",
                                    "overlay": {"wireguard": OVERLAY}}
        assert document == {**BASE, "network": {"managed_by": "host"}}

    def test_the_address_and_the_port(self):
        found = wgcli.with_address({"listen_port": 1}, " fd00:1::1/64 ", "")
        assert found == {"address": "fd00:1::1/64"}
        found = wgcli.with_address({}, "fd00:1::1/64", "51821")
        assert found["listen_port"] == 51821
        assert wgcli.with_address({}, "x", "port")["listen_port"] == "port"

    @pytest.mark.parametrize("typed, expected", [
        ("fd00:6b65:1::2", "fd00:6b65:1::2/128"),
        ("fd00:6b65:1::2/64", "fd00:6b65:1::2/128"),
        (" 10.66.0.2/24 ", "10.66.0.2/32"),
        ("node2", "node2"),
    ])
    def test_the_other_node_is_routed_as_one_host(self, typed, expected):
        assert wgcli.host_prefix(typed) == expected

    def test_a_peer_leaves_blank_fields_out(self):
        assert wgcli.peer_entry(f" {PEER_KEY} ", "", "fd00::2", "") == {
            "public_key": PEER_KEY, "allowed_ips": ["fd00::2/128"]}
        assert wgcli.peer_entry(PEER_KEY, "[2001:db8::20]:51820", "fd00::2",
                                "25") == {
            "public_key": PEER_KEY, "endpoint": "[2001:db8::20]:51820",
            "allowed_ips": ["fd00::2/128"], "persistent_keepalive": 25}

    def test_a_peer_with_the_same_key_is_replaced_not_added(self):
        moved = {"public_key": PEER_KEY, "allowed_ips": ["fd00::9/128"]}
        found = wgcli.with_peer({**OVERLAY, "peers": OVERLAY["peers"]
                                 + ["junk"]}, moved)
        assert found["peers"] == [moved]
        other = {"public_key": OTHER_KEY, "allowed_ips": ["fd00::3/128"]}
        assert wgcli.with_peer(OVERLAY, other)["peers"][-1] == other
        assert wgcli.with_peer({}, other)["peers"] == [other]

    def test_removing_a_peer(self):
        assert wgcli.without_peer(OVERLAY, PEER_KEY)["peers"] == []
        assert wgcli.without_peer(OVERLAY, OTHER_KEY) == OVERLAY

    def test_the_remove_menu(self):
        # the key and the address the peer routes, which name it and fit
        # an 80 column console; the endpoint is on the first screen
        assert wgcli.peer_choices(OVERLAY) == [
            (PEER_KEY, "fd00:6b65:1::2/128")]
        assert wgcli.peer_choices({"peers": [{"public_key": PEER_KEY}]}) == [
            (PEER_KEY, "-")]

    def test_the_peers_addresses_are_what_a_primary_authorizes(self):
        document = wgcli.with_overlay({}, {
            "address": "fd00:6b65:1::1/64",
            "peers": [
                {"public_key": PEER_KEY,
                 "allowed_ips": ["fd00:6b65:1::2/128", "10.9.0.2/32"]},
                {"public_key": OTHER_KEY,
                 "allowed_ips": ["FD00:6B65:1:0:0:0:0:3/128"]},
                "not a peer",
            ],
        })

        assert wgcli.peer_addresses(document) == [
            "fd00:6b65:1::2", "10.9.0.2", "fd00:6b65:1::3"]

    def test_a_routed_range_or_a_typo_is_not_a_replica(self):
        # A peer can route a whole prefix behind it; that range is not
        # one replica's address, and MariaDB may not hold it (keel 0.11.1
        # refuses an IPv6 prefix whose zero groups the text compresses).
        document = wgcli.with_overlay({}, {"peers": [
            {"public_key": PEER_KEY,
             "allowed_ips": ["fd00:6b65:2::/64", "nonsense", 7]},
            {"public_key": OTHER_KEY, "allowed_ips": "fd00:6b65:1::3/128"},
        ]})

        assert wgcli.peer_addresses(document) == []
        assert wgcli.peer_addresses({}) == []


class TestTexts:
    def test_the_address_is_the_mesh_s_not_the_lan_s(self):
        # The maintainer read the suggested fdXX::1/64 as "a private LAN
        # address" (step 8 review): the text says whose address it is,
        # that it is random, which node keeps it and what the port is.
        text = wgscreen.ADDRESS_TEXT
        assert "Keel's private mesh" in text
        assert "not an address on your LAN" in text
        assert "randomly generated" in text
        assert "The first node keeps it" in text
        assert "::2, ::3" in text and "same /64" in text
        assert "UDP port the other nodes reach" in text
        assert len(text) < 420

    def test_the_add_peer_form_fits_a_24_row_console(self):
        # its text and four fields filled all 24 rows, over the
        # backtitle (cc-core, 2026-10-02): the box keeps within 20
        import keelbanner

        rows = keelbanner.text_rows(wgscreen.PEER_TEXT, 72)

        assert rows + 4 + 2 + keelbanner.BOX_CHROME + 1 <= 20
        assert "endpoint" in wgscreen.PEER_TEXT.lower()
        assert "Keepalive" in wgscreen.PEER_TEXT

    def test_the_first_screen(self):
        text = wgcli.overlay_text(THIS_KEY, OVERLAY)
        assert f"This node's public key: {THIS_KEY}" in text
        assert "Mesh address (not your LAN): fd00:6b65:1::1/64" in text
        assert "UDP port: 51820" in text
        assert f"Peers (1):\n  {PEER_KEY}  fd00:6b65:1::2/128\n" in text
        assert "THIS node's side" in text

    def test_the_first_screen_fits_a_24_row_console(self):
        # Two peers on two lines each pushed the menu over its buttons
        # on an 80x24 console (cc-core, 2026-10-02): one line a peer, at
        # most three of them, every line within the 72 columns inside
        # the widest box, and room left for the three choices
        many = {**OVERLAY, "peers": [
            {"public_key": key, "allowed_ips": [f"fd00:6b65:1::{n}/128"]}
            for n, key in enumerate([PEER_KEY, OTHER_KEY, THIS_KEY,
                                     PEER_KEY[::-1], OTHER_KEY[::-1]], 2)]}

        lines = wgcli.overlay_text(THIS_KEY, many).splitlines()

        assert "  and 3 more: Remove peer lists every one" in lines
        assert sum(PEER_KEY in line or OTHER_KEY in line
                   for line in lines) == 2
        assert max(len(line) for line in lines
                   if line != wgcli.THIS_NODE) <= 72
        wrapped = sum(max(1, -(-len(line) // 72)) for line in lines)
        assert wrapped <= 20 - 5 - 5

    def test_an_empty_overlay(self):
        text = wgcli.overlay_text(THIS_KEY, {})
        assert wgcli.NO_ADDRESS in text
        assert "No peer yet." in text

    def test_a_pending_change_says_how_to_keep_it(self):
        result = make_result(wgcli.APPLY, 0, APPLIED)
        assert wgcli.is_pending(result)
        text = wgcli.applied_text(result)
        assert "REVERTS BY ITSELF" in text
        assert "keel network confirm" in text
        assert "the spec was applied" in text

    def test_nothing_pending_says_nothing_of_confirming(self):
        failed = APPLIED.replace(": done\n", ": failed: wg-quick exited 1;"
                                 " reverted to the previous file\n")
        for result in (make_result(wgcli.APPLY, 0, "unchanged\n"),
                       make_result(wgcli.APPLY, 16, failed),
                       make_result(wgcli.APPLY, 0, APPLIED.replace(
                           ": done\n", "\n"))):
            assert not wgcli.is_pending(result)
            assert "REVERTS" not in wgcli.applied_text(result)

    def test_any_pending_network_change_says_how_to_confirm(self):
        """Not only an overlay this run brought up: an uplink change, one
        brought up before a later step failed, or one an earlier run left
        waiting, which keel names when it refuses another"""
        uplink = (
            "network: bring eth0 up on a new /etc/network/interfaces; it"
            " reverts in 120 s unless `keel network confirm` is run from a"
            " new session over the new configuration: done\n"
        )
        waiting = (
            "network.overlay: refused: a network change is waiting for its"
            " confirmation: keel network confirm from a new session, or let"
            " it revert, before another one\n"
        )
        for result in (make_result(wgcli.APPLY, 0, uplink),
                       make_result(wgcli.APPLY, 16, "tls: failed\n" + APPLIED),
                       make_result(wgcli.APPLY, 16, waiting)):
            assert wgcli.is_pending(result)
            text = wgcli.applied_text(result)
            assert "REVERTS BY ITSELF" in text
            assert "Confirm from a NEW session" in text
            assert "keel network confirm" in text

    def test_the_confirm_and_key_verdicts(self):
        assert "confirmed: the network change stays" in wgcli.command_text(
            "confirm", make_result(wgcli.CONFIRM, 0))
        assert "not confirmed" in wgcli.command_text(
            "confirm", make_result(wgcli.CONFIRM, 21))

    def test_nothing_waiting_is_not_called_a_change_that_reverts(self):
        """The maintainer's screenshot 040: another session had confirmed
        the change, and the screen said it would revert. keel says why it
        refused; the verdict line claims nothing keel did not say."""
        nothing = make_result(
            wgcli.CONFIRM, 21, "", "Error: no network change is waiting for"
            " a confirmation; the last one, of /etc/wireguard/wg0.conf, was"
            " reverted\n")
        text = wgcli.command_text("confirm", nothing)
        assert "not confirmed" in text
        assert "reverts when" not in text
        assert "the reason is above" in text
        assert "no public key" in wgcli.command_text(
            "key", make_result(wgcli.KEY, 16))

    def test_a_rollback_that_failed_too_still_waits(self):
        """keel keeps the marker and the timer when it could not put the
        previous file back, so the change still reverts by itself"""
        stuck = APPLIED.replace(
            ": done\n", ": failed: wg-quick exited 1; putting the previous"
            " file back failed too (full); the revert timer will try"
            " again\n")
        result = make_result(wgcli.APPLY, 16, stuck)
        assert wgcli.is_pending(result)
        assert "REVERTS BY ITSELF" in wgcli.applied_text(result)

    def test_the_package_asks_for_a_keel_with_skip_uplink(self):
        """An older keel dies in argparse on --skip-uplink, and before
        0.11.2 refuses the confirmation from an LXC console"""
        control = (Path(__file__).resolve().parent.parent / "debian"
                   / "control").read_text()
        assert " keel (>= 0.11.2),\n" in control
        assert FIRST_WITH_OVERLAY == (0, 11)

    def test_apply_moves_the_overlay_and_never_the_uplink(self):
        """The database screens pass --skip-network; this one must not,
        since bringing the overlay up is what it is for, but it passes
        --skip-uplink, so adding a peer never moves network.interfaces"""
        assert "--skip-network" in keelcli.APPLY
        assert "--skip-network" not in wgcli.APPLY
        assert "--skip-uplink" in wgcli.APPLY
        assert wgcli.APPLY[:3] == ["spec", "apply", "--system-only"]


class TestScreen:
    def test_the_entry_hands_its_console_to_the_screen(self, keel, spec):
        spec(BASE)
        loaded = plugin.Plugin(str(ENTRY))
        console = FakeConsole(menus=[("cancel", "")])
        loaded.updateGlobals({"console": console})

        loaded.module.run()

        assert loaded.name == "Overlay network.py"
        assert "WireGuard" in loaded.module.__doc__
        assert console.calls[0][0] == "menu"

    def test_without_an_address_only_the_address_is_offered(self, keel,
                                                            spec):
        spec(BASE)
        console = FakeConsole(menus=[("cancel", "")])

        wgscreen.run(console)

        _, title, text, choices = console.calls[0]
        assert title == wgcli.TITLE
        assert THIS_KEY in text
        assert [tag for tag, _ in choices] == [wgscreen.ADDRESS]
        assert keel["calls"][0][:3] == ["network", "wireguard", "key"]

    def test_with_peers_every_action_is_offered(self, keel, spec):
        spec(wgcli.with_overlay(BASE, OVERLAY))
        console = FakeConsole(menus=[("cancel", "")])

        wgscreen.run(console)

        assert [tag for tag, _ in console.calls[0][3]] == [
            wgscreen.ADDRESS, wgscreen.ADD, wgscreen.REMOVE]

    def test_no_keel_or_no_key_stops_at_once(self, keel, spec):
        spec(BASE)
        keel["answers"]["network wireguard key"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED),
            (16, "", "Error: wg is not installed: the overlay needs the"
             " wireguard-tools package\n"),
        ]
        for expected in (keelcli.NOT_INSTALLED, "wireguard-tools"):
            console = FakeConsole()
            wgscreen.run(console)
            assert expected in console.calls[-1][2]

    def test_an_unreadable_description_is_said(self, keel, spec):
        spec(["not", "a", "mapping"])
        console = FakeConsole()

        wgscreen.run(console)

        assert "not a mapping" in console.calls[-1][2]

    def test_the_first_address_is_keel_s_suggestion(self, keel, spec):
        path = spec(BASE)
        keel["answers"]["network wireguard suggest-address"] = [
            (0, "fd12:3456:789a::1/64\n")]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADDRESS), ("cancel", "")],
            forms=[("ok", ["fd12:3456:789a::1/64", ""])],
        )

        wgscreen.run(console)

        form = [call for call in console.calls if call[0] == "form"][0]
        assert form[2][0][3] == "fd12:3456:789a::1/64"
        assert read(path)["network"]["overlay"]["wireguard"] == {
            "address": "fd12:3456:789a::1/64"}
        assert "spec validate --no-secret-files" in commands(keel)
        assert "spec apply --system-only" in commands(keel)

    def test_no_suggestion_leaves_the_field_blank(self, keel, spec):
        spec(BASE)
        keel["answers"]["network wireguard suggest-address"] = [(1, "")]
        console = FakeConsole(menus=[("ok", wgscreen.ADDRESS),
                                     ("cancel", "")],
                              forms=[("cancel", [])])

        wgscreen.run(console)

        form = [call for call in console.calls if call[0] == "form"][0]
        assert form[2][0][3] == ""

    def test_adding_a_peer_then_confirming_from_the_console(self, keel,
                                                             spec):
        path = spec(wgcli.with_overlay(BASE, {"address":
                                               "fd00:6b65:1::1/64"}))
        keel["answers"]["spec apply"] = [(0, APPLIED)]
        keel["answers"]["network confirm"] = [(0, "confirmed from the"
                                              " console /dev/tty1\n")]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", [PEER_KEY, "fd00:6b65:1::2", "[2001:db8::20]:51820",
                           "25"])],
            yesno=["ok"],
        )

        wgscreen.run(console)

        assert read(path)["network"]["overlay"]["wireguard"]["peers"] == [{
            "public_key": PEER_KEY, "endpoint": "[2001:db8::20]:51820",
            "allowed_ips": ["fd00:6b65:1::2/128"],
            "persistent_keepalive": 25}]
        assert commands(keel)[-1] == "network confirm"
        texts = [call[2] for call in console.calls if call[0] == "msgbox"]
        assert "REVERTS BY ITSELF" in texts[0]
        assert "confirmed: the network change stays" in texts[1]

    def test_confirming_from_a_new_session_instead(self, keel, spec):
        spec(wgcli.with_overlay(BASE, OVERLAY))
        keel["answers"]["spec apply"] = [(0, APPLIED)]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", [OTHER_KEY, "fd00:6b65:1::3", "", ""])],
            yesno=["cancel"],
        )

        wgscreen.run(console)

        assert "network confirm" not in commands(keel)

    def test_a_confirm_keel_cannot_run(self, keel, spec):
        spec(wgcli.with_overlay(BASE, OVERLAY))
        keel["answers"]["spec apply"] = [(0, APPLIED)]
        keel["answers"]["network confirm"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", [OTHER_KEY, "fd00:6b65:1::3", "", ""])],
            yesno=["ok"],
        )

        wgscreen.run(console)

        assert console.calls[-2][2] == keelcli.NOT_INSTALLED

    def test_a_refused_apply_asks_nothing(self, keel, spec):
        spec(wgcli.with_overlay(BASE, OVERLAY))
        keel["answers"]["spec apply"] = [
            (16, "network.overlay: refused: the wireguard kernel module is"
             " not loaded ... modprobe wireguard\n")]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", [OTHER_KEY, "fd00:6b65:1::3", "", ""])],
        )

        wgscreen.run(console)

        texts = [call[2] for call in console.calls if call[0] == "msgbox"]
        assert "modprobe wireguard" in texts[0]
        assert not [call for call in console.calls if call[0] == "yesno"]

    def test_apply_without_keel(self, keel, spec):
        spec(wgcli.with_overlay(BASE, OVERLAY))
        keel["answers"]["spec apply"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", [OTHER_KEY, "fd00:6b65:1::3", "", ""])],
        )

        wgscreen.run(console)

        assert console.calls[-2][2] == keelcli.NOT_INSTALLED

    def test_an_invalid_peer_leaves_the_description_alone(self, keel, spec):
        path = spec(wgcli.with_overlay(BASE, OVERLAY))
        before = path.read_text()
        keel["answers"]["spec validate"] = [
            (3, "", "Error: network.overlay.wireguard.peers[1].public_key:"
             " not a WireGuard key\n")]
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", ["abc", "fd00:6b65:1::3", "", ""])],
        )

        wgscreen.run(console)

        assert path.read_text() == before
        assert "not a WireGuard key" in console.calls[-2][2]
        assert "spec apply --system-only" not in commands(keel)

    @pytest.mark.parametrize("step", ["stage", "validate", "commit"])
    def test_a_description_that_cannot_be_written(self, keel, spec,
                                                  monkeypatch, step):
        path = spec(wgcli.with_overlay(BASE, OVERLAY))
        before = path.read_text()
        if step == "stage":
            monkeypatch.setattr(keelcli, "stage_spec",
                                lambda document, where: ("", "no space"))
        elif step == "validate":
            keel["answers"]["spec validate"] = [
                keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        else:
            monkeypatch.setattr(keelcli, "commit_spec",
                                lambda staged, where: "permission denied")
        console = FakeConsole(
            menus=[("ok", wgscreen.ADD), ("cancel", "")],
            forms=[("ok", [OTHER_KEY, "fd00:6b65:1::3", "", ""])],
        )

        wgscreen.run(console)

        assert path.read_text() == before
        assert "spec apply --system-only" not in commands(keel)
        expected = {"stage": "no space", "validate": keelcli.NOT_INSTALLED,
                    "commit": "permission denied"}[step]
        assert console.calls[-2][2] == expected

    def test_a_cancelled_form_changes_nothing(self, keel, spec):
        spec(wgcli.with_overlay(BASE, OVERLAY))
        console = FakeConsole(menus=[("ok", wgscreen.ADD), ("cancel", "")],
                              forms=[("cancel", [])])

        wgscreen.run(console)

        assert commands(keel) == ["network wireguard key"]

    def test_removing_a_peer_asks_first(self, keel, spec):
        path = spec(wgcli.with_overlay(BASE, OVERLAY))
        console = FakeConsole(
            menus=[("ok", wgscreen.REMOVE), ("ok", PEER_KEY),
                   ("ok", wgscreen.REMOVE), ("ok", PEER_KEY),
                   ("ok", wgscreen.REMOVE), ("cancel", ""),
                   ("cancel", "")],
            yesno=["cancel", "ok"],
        )

        wgscreen.run(console)

        assert read(path)["network"]["overlay"]["wireguard"]["peers"] == []
        assert commands(keel).count("spec apply --system-only") == 1


FIRST_WITH_OVERLAY = (0, 11)


def keel_with_overlay() -> str | None:
    """The keel command, when it is one that knows network.overlay

    `KEEL` names it (a checkout's wrapper, say), else the one on PATH.
    An older keel rejects the section as an unknown key, which says
    nothing about what the screen builds, so the class skips.
    """
    command = os.environ.get("KEEL") or shutil.which("keel")
    if command is None:
        return None
    done = subprocess.run([command, "--version"], capture_output=True,
                          text=True, check=False)
    try:
        version = tuple(int(part) for part in done.stdout.split(".")[:2])
    except ValueError:
        return None
    return command if version >= FIRST_WITH_OVERLAY else None


@pytest.mark.skipif(keel_with_overlay() is None,
                    reason="no keel 0.11 or later (set KEEL)")
class TestWithTheRealKeel:
    """What the screen writes, judged by keel's own validation"""

    def validate(self, tmp_path, document):
        path = tmp_path / "instance.yaml"
        path.write_text(keelcli.render_spec(document))
        return subprocess.run(
            [keel_with_overlay(), "spec", "validate", "--no-secret-files",
             "--spec", str(path)], capture_output=True, text=True,
            check=False,
        )

    def test_an_address_and_a_peer_validate(self, tmp_path):
        overlay = wgcli.with_address({}, "fd00:6b65:1::1/64", "")
        overlay = wgcli.with_peer(overlay, wgcli.peer_entry(
            PEER_KEY, "[2001:db8::20]:51820", "fd00:6b65:1::2/64", "25"))
        done = self.validate(tmp_path, wgcli.with_overlay(BASE, overlay))
        assert done.returncode == 0, done.stderr

    def test_what_keel_refuses_it_says(self, tmp_path):
        overlay = wgcli.with_peer(
            wgcli.with_address({}, "fd00:6b65:1::1/64", "port"),
            wgcli.peer_entry("abc", "2001:db8::20:51820", "node2", "x"))
        done = self.validate(tmp_path, wgcli.with_overlay(BASE, overlay))
        assert done.returncode == keelcli.SPEC_INVALID
        for words in ("listen_port", "not a WireGuard key", "brackets",
                      "allowed_ips", "persistent_keepalive"):
            assert words in done.stderr
