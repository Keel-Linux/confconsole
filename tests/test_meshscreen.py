"""The mesh and the pair of a cloud node: Invite a node, Join a mesh, the
waits, the pair, the VIP (handbook decision 0076).

keel's side is its contract for confconsole (keel docs/mesh.md): the
JSON of `keel mesh invite --json` and `keel mesh status --json`, and the
token on standard input. No dialog opens and no keel runs: keelcli.call
and keelcli.run_on_terminal are replaced, the terminal is captured, and
the console is the scripted fake of conftest.
"""

import json
from pathlib import Path

import pytest
import yaml

import dbscreen
import keelcli
import keelmode
import meshscreen
from conftest import DB_COLUMNS, FakeConsole, make_result

ME = "fd2a:9c41:7e03::1"
OTHER = "fd2a:9c41:7e03::4e1a"
THIRD = "fd2a:9c41:7e03::77"
VIP = "fd2a:9c41:7e03::ffff:1"
TOKEN = "keel2:AAAA-bbbb_CCCC"
LINE = f"keel mesh join - <<< {TOKEN}"
INVITED = {"format": 1, "line": LINE, "token": TOKEN, "vip": VIP,
           "expires": "2026-11-05T13:00:00Z", "invite_id": "3f9c",
           "assigned": f"{OTHER}/64", "https_port": 51820}
REFUSAL = "database.server.replication.primary: refused: becoming a replica"


def member(address, reachable=True):
    return {"public_key": "k=", "address": address,
            "allowed_ips": [f"{address}/128"], "endpoint": None,
            "handshake_age": 3, "reachable": reachable}


def status(in_mesh=True, others=(), etcd=None, vip=None, address=ME):
    return {"format": 1, "live": True, "in_mesh": in_mesh,
            "address": f"{address}/64" if in_mesh else None,
            "members": [member(one) for one in others],
            "invites": [],
            "etcd": etcd or {"state": "off"},
            "vip": {"declared": None, "proposed": None, "role": None,
                    "holder": None, **(vip or {})},
            "ready": True}


FORMED = {"state": "formed", "voters": 3, "healthy_voters": 3}


@pytest.fixture(autouse=True)
def no_server_binary(monkeypatch):
    """No database server on the machine, unless a test says otherwise:
    keel inspect is never asked"""
    monkeypatch.setattr(dbscreen, "database_server_installed", lambda: False)


@pytest.fixture
def keel(monkeypatch):
    """keelcli.call and run_on_terminal replaced. `status` is the list of
    status JSONs keel answers in turn, the last one again and again;
    `answers` steer the rest by the command's first words."""
    state = {"calls": [], "answers": {}, "status": [], "terminal": [],
             "codes": []}

    def fake_call(argv):
        state["calls"].append(list(argv))
        if argv == meshscreen.STATUS and state["status"]:
            found = state["status"][0]
            if len(state["status"]) > 1:
                state["status"].pop(0)
            if isinstance(found, tuple):
                return make_result(argv, *found)
            return make_result(argv, 0, json.dumps(found))
        for prefix, outcomes in state["answers"].items():
            if " ".join(argv).startswith(prefix) and outcomes:
                outcome = outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return make_result(argv, *outcome)
        return make_result(argv)

    def fake_terminal(argv, text):
        state["terminal"].append((list(argv), text))
        if state["codes"]:
            outcome = state["codes"].pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return 0

    monkeypatch.setattr(keelcli, "call", fake_call)
    monkeypatch.setattr(keelcli, "run_on_terminal", fake_terminal)
    return state


@pytest.fixture
def terminal(monkeypatch):
    """What reached the terminal outside dialog, and the Enters typed"""
    shown = {"lines": [], "prompts": []}
    monkeypatch.setattr(meshscreen, "print_plain",
                        lambda lines: shown["lines"].append(list(lines)))
    monkeypatch.setattr(meshscreen, "read_line",
                        lambda prompt: shown["prompts"].append(prompt) or "")
    return shown


@pytest.fixture
def record(tmp_path, monkeypatch):
    """Where keel keeps the pair record, under the test's directory"""
    where = tmp_path / "vip"
    where.mkdir()
    monkeypatch.setattr(meshscreen, "PAIR_RECORD",
                        str(where / "{vip}.pair"))
    return where / f"{VIP}.pair"


@pytest.fixture
def spec(tmp_path, monkeypatch):
    path = tmp_path / "instance.yaml"
    monkeypatch.setenv("KEEL_SPEC", str(path))

    def _write(document):
        path.write_text(yaml.safe_dump(document))
        return path

    _write.path = path
    return _write


def read(path):
    return yaml.safe_load(Path(path).read_text())


def commands(keel):
    return [" ".join(argv[:3]) for argv in keel["calls"]
            if argv != meshscreen.STATUS]


def boxes(console):
    return [call for call in console.calls if call[0] == "msgbox"]


def titles(console):
    return [call[1] for call in console.calls
            if call[0] in ("msgbox", "menu", "pause", "inputbox")]


def cloud(mode="cloud_simple", name="mariadb", **more):
    return {"version": 1, "appliance": {"name": name},
            "installation": {"mode": mode},
            "overlays": dict(keelmode.column(
                keelmode.Facts(name, columns=DB_COLUMNS), mode, {})),
            **more}


def node(spec, role, mode="cloud_simple", engine="mariadb", files=False):
    return meshscreen.Node(str(spec.path), mode, role, engine, files)


class TestTheScreenTitles:
    """The commissioning driver matches on them: they do not change"""

    def test_they_are_these_strings(self):
        assert meshscreen.ROLE_TITLE == "Role of this node"
        assert meshscreen.INVITE_TITLE == "Invite a node"
        assert meshscreen.JOIN_TITLE == "Join a mesh"
        assert meshscreen.MESH_TITLE == "Make the mesh"
        assert meshscreen.WAIT_TITLE == "Waiting for the nodes"
        assert meshscreen.ACCEPT_TITLE == "Paste accept line"
        assert meshscreen.INVITER_TITLE == "Primary of the pair"
        assert meshscreen.PAIR_TITLE == "Pair with the primary"
        assert meshscreen.VIP_TITLE == "Take the VIP"
        assert meshscreen.STATUS_TITLE == "Status of this node"


class TestWhatPairs:
    def facts(self, name, columns, engines=frozenset()):
        return keelmode.Facts(name, columns=columns, engines=engines)

    def test_an_engine_keel_replicates_is_a_database_pair(self):
        found = meshscreen.node_of("p", {"installation": {
            "mode": "cloud_simple"}}, self.facts(
            "mariadb", DB_COLUMNS, frozenset({"mariadb", "redis"})),
            "primary")

        assert (found.engine, found.files, found.pairs) == (
            "mariadb", False, True)

    def test_a_declared_server_names_its_engine(self):
        found = meshscreen.node_of("p", {"database": {"server": {
            "engine": "postgresql"}}}, None, "replica")

        assert found.engine == "postgresql"

    def test_web_is_a_pair_of_files(self):
        columns = {"syncthing": {"cloud_simple": "enabled"}}

        found = meshscreen.node_of("p", {"installation": {
            "mode": "cloud_simple"}}, self.facts("web", columns), "primary")

        assert (found.engine, found.files) == ("", True)

    def test_a_chain_that_names_no_engine_asks_the_machine(
        self, monkeypatch
    ):
        # keel-mariadb's manifest adds no overlay that provides mariadb
        monkeypatch.setattr(dbscreen, "find_engine",
                            lambda server: "mariadb")

        found = meshscreen.node_of("p", {"installation": {
            "mode": "cloud_simple"}}, self.facts("mariadb", {}), "replica")

        assert found.engine == "mariadb"

    def test_a_machine_engine_keel_does_not_replicate_pairs_nothing(
        self, monkeypatch
    ):
        monkeypatch.setattr(dbscreen, "find_engine", lambda server: "redis")

        assert not meshscreen.node_of("p", {}, None, "primary").pairs

    def test_core_pairs_nothing(self):
        found = meshscreen.node_of("p", {"installation": {
            "mode": "cloud_simple"}}, self.facts("core", {}), "primary")

        assert not found.pairs

    def test_a_witness_pairs_nothing_whatever_its_chain(self):
        found = meshscreen.node_of("p", {}, self.facts(
            "mariadb", DB_COLUMNS, frozenset({"mariadb"})), "witness")

        assert not found.pairs

    def test_cloud_advanced_waits_for_two_members(self):
        assert meshscreen.Node("p", "cloud_advanced", "primary").needed == 2
        assert meshscreen.Node("p", "cloud_simple", "primary").needed == 1


class TestWhatKeelSays:
    def test_a_member_at_the_assigned_address_has_joined(self):
        found = status(others=[OTHER])

        assert meshscreen.member_at(found, f"{OTHER}/64")
        assert not meshscreen.member_at(found, f"{THIRD}/64")

    def test_a_member_keel_did_not_reach_has_not(self):
        found = status()
        found["members"] = [member(OTHER, reachable=False)]

        assert not meshscreen.member_at(found, OTHER)

    def test_etcd_is_formed_with_three_voters(self):
        assert meshscreen.etcd_formed(status(etcd=FORMED))
        assert not meshscreen.etcd_formed(status(etcd={
            "state": "formed", "voters": 2}))
        # three voters, one not healthy: a promote now gets no lease
        assert not meshscreen.etcd_formed(status(etcd={
            "state": "formed", "voters": 3, "healthy_voters": 2}))
        assert not meshscreen.etcd_formed(status(etcd={
            "state": "not_formed", "voters": None}))

    def test_odd_json_reads_as_nothing(self):
        odd = {"members": "x", "etcd": [], "vip": 1}

        assert meshscreen.members(odd) == []
        assert meshscreen.etcd_of(odd) == {}
        assert meshscreen.vip_of(odd) == {}

    def test_the_wait_screen_names_the_members_etcd_and_the_vip(self):
        found = status(others=[OTHER], etcd={"state": "not_formed"},
                       vip={"proposed": VIP})
        found["members"].append(member(THIRD, reachable=None))
        found["members"].append(member("fd00::9", reachable=False))

        text = meshscreen.describe(found)

        assert f"This node: {ME}/64" in text
        assert f"Member: {OTHER}, reached" in text
        assert f"Member: {THIRD}, no handshake yet" in text
        assert "Member: fd00::9, not reached" in text
        assert "etcd: not_formed, voters 0" in text
        assert f"VIP: {VIP}, holder none yet" in text

    def test_a_command_says_its_exit(self):
        text = meshscreen.command_text(make_result(
            ["mesh", "join", "-"], 23, "", "bad checksum"))

        assert "bad checksum" in text
        assert "keel mesh: exit 23, the line is mistyped" in text

    def test_a_command_with_no_subcommand_is_said_too(self):
        result = keelcli.Result(("keel",), 1, "", "")

        assert "keel : exit 1" in meshscreen.command_text(result)

    def test_status_that_is_not_json_is_shown(self, keel):
        keel["status"] = [(0, "not json")]
        console = FakeConsole()

        assert meshscreen.status(console, "t") is None
        assert "printed no JSON object" in boxes(console)[0][2]

    def test_status_that_fails_is_shown(self, keel):
        keel["status"] = [(16, "", "etcd: no")]
        console = FakeConsole()

        assert meshscreen.status(console, "t") is None
        assert "etcd: no" in boxes(console)[0][2]

    def test_status_without_keel_is_said(self, keel):
        keel["status"] = []
        keel["answers"]["mesh status"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole()

        assert meshscreen.status(console, "t") is None
        assert boxes(console)[0][2] == keelcli.NOT_INSTALLED


class TestTheTerminal:
    def test_the_line_reaches_the_terminal_whole(self, capsys):
        long = "keel mesh join - <<< keel2:" + "A" * 300

        meshscreen.print_plain(["Invite a node", long])

        out = capsys.readouterr().out
        assert out.startswith(meshscreen.CLEAR)
        assert f"\n{long}\n" in out

    def test_a_line_is_read_and_nobody_there_is_empty(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda prompt: "typed")
        assert meshscreen.read_line("? ") == "typed"

        def eof(prompt):
            raise EOFError

        monkeypatch.setattr("builtins.input", eof)
        assert meshscreen.read_line("? ") == ""

    def test_keel_on_the_terminal_without_keel_is_said(self, keel,
                                                       terminal):
        keel["codes"] = [keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole()

        assert meshscreen.on_terminal(console, "t", ["x"], ["mesh"],
                                      "") is None
        assert boxes(console)[0][2] == keelcli.NOT_INSTALLED

    def test_the_pause_closes_by_itself(self):
        console = FakeConsole()

        assert meshscreen.pause(console, "t", "x") == "ok"
        assert console.calls[0] == ("pause", "t", "x", (16, 72, 5))


class TestTheWait:
    def test_it_asks_again_until_done(self, keel):
        keel["status"] = [status(), status(others=[OTHER])]
        console = FakeConsole()

        assert meshscreen.wait(console, "t", "intro",
                               lambda found: bool(found["members"]))
        assert [one[0] for one in console.calls] == ["pause"]

    def test_back_then_later_stops_it(self, keel):
        keel["status"] = [status()]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        assert not meshscreen.wait(console, "t", "intro", lambda f: False)

    def test_back_then_check_again_goes_on(self, keel):
        keel["status"] = [status(), status(others=[OTHER])]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.CHECK)])

        assert meshscreen.wait(console, "t", "intro",
                               lambda found: bool(found["members"]))

    def test_an_action_that_says_done_ends_it(self, keel):
        keel["status"] = [status()]
        console = FakeConsole(pauses=["cancel", "cancel"],
                              menus=[("ok", "A"), ("ok", "B")])
        ran = []

        assert meshscreen.wait(console, "t", "intro", lambda f: False, [
            ("A", "a", lambda c: ran.append("a")),
            ("B", "b", lambda c: True)])
        assert ran == ["a"]
        tags = [tag for tag, _ in console.calls[1][3]]
        assert tags == [meshscreen.CHECK, "A", "B", meshscreen.LATER]

    def test_a_status_that_fails_stops_it(self, keel):
        keel["status"] = [(16, "", "")]

        assert not meshscreen.wait(FakeConsole(), "t", "i", lambda f: True)

    def test_an_hour_of_nothing_ends_it(self, keel, monkeypatch):
        monkeypatch.setattr(meshscreen, "WAIT_ROUNDS", 2)
        keel["status"] = [status()]
        console = FakeConsole()

        assert not meshscreen.wait(console, "t", "i", lambda f: False)
        assert boxes(console)[0][2] == meshscreen.TIMED_OUT


class TestThePrimary:
    """Cloud simple: the mesh, the invite, the VIP, the pair, promote"""

    def test_the_whole_flow_in_cloud_simple(self, spec, keel, terminal,
                                            record):
        spec(cloud())
        keel["status"] = [status(in_mesh=False), status(),
                          status(), status(), status(others=[OTHER]),
                          status(others=[OTHER])]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]
        record.write_text("")
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert commands(keel) == [
            "mesh create", "spec validate --no-secret-files",
            "mesh invite --json", "spec validate --no-secret-files",
            "spec apply --system-only", "vip promote", "vip status",
            "mesh status", "database status"]
        found = read(spec.path)
        assert found["appliance"]["vip"] == VIP
        assert found["overlays"]["vip"] == "enabled"
        assert found["database"]["server"] == {
            "engine": "mariadb", "role": "primary",
            "listen": [ME, "::1", "127.0.0.1"]}
        assert titles(console) == [
            "Make the mesh", "Waiting for the nodes",
            "Take the VIP", "Status of this node"]
        # the line, plain and whole, never inside a dialog
        assert LINE in terminal["lines"][0]
        assert terminal["lines"][0][0] == "Invite a node"
        for call in console.calls:
            assert TOKEN not in str(call)

    def test_the_line_is_shown_though_keel_refuses_a_server_before_the_pair(
        self, spec, keel, terminal
    ):
        # BR1, 2026-11-06: an apply before the pair record failed with
        # "holds no pair record" (exit 16), and the line never reached
        # tty1. The primary does not apply until the pair exists.
        import re

        spec(cloud())
        keel["status"] = [status(), status(), status(others=[OTHER])]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]
        keel["answers"]["spec apply"] = [
            (16, "database.server: refused: holds no pair record", "")]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        meshscreen.primary(console, node(spec, "primary"))

        shown = "\n".join(terminal["lines"][0])
        # what the commissioning driver captures from the raw stream
        assert re.search(r"keel[12]:[A-Za-z0-9_.~+/=-]+", shown).group(0) \
            == TOKEN
        assert re.search(r"VIP:? +(\S+)", shown).group(1) == VIP
        # one screen, one Enter (the commissioning contract: invite {ret})
        assert terminal["prompts"] == [meshscreen.PRESS_ENTER]
        assert "spec apply --system-only" not in commands(keel)[:3]

    def test_an_earlier_invite_still_pending_moves_this_one_a_port_on(self):
        found = status()
        found["invites"] = [
            {"invite_id": "a", "https_port": 51820, "used": False},
            {"invite_id": "b", "https_port": 51830, "used": True},
            "odd"]

        assert meshscreen.invite_argv(found) == [
            "mesh", "invite", "--json", "--port", "51821"]
        assert meshscreen.invite_argv(status()) == meshscreen.INVITE

    def test_cloud_advanced_invites_twice_and_waits_for_etcd(
        self, spec, keel, terminal, record
    ):
        spec(cloud("cloud_advanced", appliance={"name": "mariadb",
                                                "vip": VIP}))
        record.write_text("")
        second = {**INVITED, "assigned": f"{THIRD}/64"}
        keel["status"] = [
            status(), status(others=[OTHER]), status(others=[OTHER]),
            status(others=[OTHER]), status(others=[OTHER, THIRD]),
            status(others=[OTHER, THIRD]), status(others=[OTHER, THIRD]),
            status(others=[OTHER, THIRD]),
            status(others=[OTHER, THIRD], etcd=FORMED)]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED)),
                                          (0, json.dumps(second))]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary", "cloud_advanced"))

        assert commands(keel).count("mesh invite --json") == 2
        assert "mesh create" not in commands(keel)
        texts = ["\n".join(lines) for lines in terminal["lines"]]
        assert "the replica (node 2)" in texts[0]
        assert "the witness (node 3, Keel Core)" in texts[1]
        assert any("etcd to have 3 voters" in call[2]
                   for call in console.calls if call[0] == "pause")
        assert keel["calls"][-4][:2] == ["vip", "promote"]

    def test_a_node_with_enough_members_invites_nobody(self, spec, keel,
                                                       record):
        spec(cloud(appliance={"name": "mariadb", "vip": VIP},
                   overlays={"vip": "enabled"}))
        record.write_text("")
        keel["status"] = [status(others=[OTHER])]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "mesh invite --json" not in commands(keel)

    def test_core_makes_the_mesh_only(self, spec, keel, terminal):
        spec(cloud(name="core"))
        keel["status"] = [status(), status(), status(others=[OTHER])]
        keel["answers"]["mesh invite"] = [(0, json.dumps(
            {**INVITED, "vip": None}))]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary", engine=""))

        assert commands(keel) == ["mesh invite --json", "mesh status"]
        assert "carries no service address" in "\n".join(
            terminal["lines"][0])
        assert "appliance" not in read(spec.path) or "vip" not in read(
            spec.path)["appliance"]

    def test_a_pair_of_files_writes_no_server(self, spec, keel, terminal,
                                              record):
        spec(cloud(name="web"))
        record.write_text("")
        keel["status"] = [status(), status(), status(others=[OTHER])]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]

        meshscreen.primary(FakeConsole(), node(spec, "primary", engine="",
                                               files=True))

        found = read(spec.path)
        assert found["appliance"]["vip"] == VIP
        assert "database" not in found
        assert "database status" not in commands(keel)
        assert "vip status" in commands(keel)

    def test_an_invite_with_no_vip_cannot_pair(self, spec, keel):
        spec(cloud())
        keel["status"] = [status()]
        keel["answers"]["mesh invite"] = [(0, json.dumps(
            {**INVITED, "vip": None}), "the overlay is too narrow")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        said = boxes(console)[0][2]
        assert "carries no VIP" in said
        assert "the overlay is too narrow" in said

    def test_an_invite_keel_refuses_is_shown(self, spec, keel):
        spec(cloud())
        keel["status"] = [status()]
        keel["answers"]["mesh invite"] = [(24, "", "no endpoint")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "no endpoint" in boxes(console)[0][2]
        assert boxes(console)[-1][1] == "Not finished yet"
        assert "Database mode > Cloud > Primary" in boxes(console)[-1][2]

    def test_an_invite_that_prints_no_json_stops(self, spec, keel):
        spec(cloud())
        keel["status"] = [status()]
        keel["answers"]["mesh invite"] = [(0, "keel mesh join ...")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "printed no JSON" in boxes(console)[0][2]

    def test_a_mesh_keel_could_not_make_stops(self, spec, keel):
        spec(cloud())
        keel["status"] = [status(in_mesh=False)]
        keel["answers"]["mesh create"] = [(16, "", "wg: no")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "wg: no" in boxes(console)[0][2]
        assert "mesh invite --json" not in commands(keel)

    def test_without_keel_nothing_is_made(self, spec, keel):
        spec(cloud())
        keel["status"] = [status(in_mesh=False)]
        keel["answers"]["mesh create"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        meshscreen.primary(FakeConsole(), node(spec, "primary"))

        assert "mesh invite --json" not in commands(keel)

    @pytest.mark.parametrize("failing", [0, 1])
    def test_a_status_that_fails_stops_the_primary(self, spec, keel,
                                                   failing):
        spec(cloud())
        found = [status(in_mesh=False), status()]
        found[failing] = (16, "", "")
        keel["status"] = found

        meshscreen.primary(FakeConsole(), node(spec, "primary"))

        assert "mesh invite --json" not in commands(keel)

    def test_a_status_that_fails_after_the_invite_stops(self, spec, keel,
                                                        terminal):
        spec(cloud(name="core"))
        keel["status"] = [status(), status(others=[OTHER]), (16, "", "")]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]

        meshscreen.primary(FakeConsole(), node(spec, "primary", engine=""))

        assert "mesh status" not in commands(keel)

    def test_the_vip_overlay_keel_refuses_stops(self, spec, keel):
        spec(cloud())
        keel["status"] = [status()]
        keel["answers"]["spec validate"] = [(3, "", "vip: no")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "vip: no" in boxes(console)[0][2]
        assert "mesh invite --json" not in commands(keel)

    def test_a_description_that_does_not_read_stops(self, spec, keel):
        spec.path.write_text("version: [1")
        keel["status"] = [status()]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "not valid YAML" in boxes(console)[0][2]

    def test_the_join_left_for_later(self, spec, keel, terminal):
        spec(cloud(name="core"))
        keel["status"] = [status()]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        meshscreen.primary(console, node(spec, "primary", engine=""))

        assert boxes(console)[-1][1] == "Not finished yet"
        assert "keel-init" in boxes(console)[-1][2]

    def test_etcd_left_for_later(self, spec, keel, terminal):
        spec(cloud("cloud_advanced", name="core"))
        keel["status"] = [status(others=[OTHER, THIRD])]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        meshscreen.primary(console, node(spec, "primary", "cloud_advanced",
                                         engine=""))

        assert boxes(console)[-1][1] == "Not finished yet"

    def test_the_line_again_and_the_accept_line(self, spec, keel, terminal):
        spec(cloud(name="core"))
        keel["status"] = [status(), status(), status(), status(),
                          status(others=[OTHER])]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]
        accept = "keel mesh accept keel1a:Zz9-_"
        console = FakeConsole(
            pauses=["cancel", "cancel"],
            menus=[("ok", meshscreen.SHOW_AGAIN),
                   ("ok", meshscreen.ACCEPT_TITLE)],
            inputs=[("ok", f"  {accept}  ")])

        meshscreen.primary(console, node(spec, "primary", engine=""))

        assert len(terminal["lines"]) == 3
        assert LINE in terminal["lines"][1]
        assert keel["terminal"] == [(["mesh", "accept", "-"],
                                     "keel1a:Zz9-_\n")]
        assert "keel mesh: exit 0" in [
            call[2] for call in console.calls
            if call[0] == "msgbox" and call[1] == "Paste accept line"][0]

    @pytest.mark.parametrize("typed", [("cancel", ""), ("ok", "nonsense")])
    def test_no_accept_line_accepts_nothing(self, keel, terminal, typed):
        console = FakeConsole(inputs=[typed])

        assert meshscreen.accept(console) is False
        assert keel["terminal"] == []

    def test_an_accept_without_keel_says_it_once(self, keel, terminal):
        keel["codes"] = [keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole(inputs=[("ok", "keel1a:x")])

        meshscreen.accept(console)

        assert [one[2] for one in boxes(console)] == [keelcli.NOT_INSTALLED]

    def test_the_pair_left_for_later(self, spec, keel, record):
        spec(cloud(appliance={"name": "mariadb", "vip": VIP},
                   overlays={"vip": "enabled"}))
        keel["status"] = [status(others=[OTHER])]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        meshscreen.primary(console, node(spec, "primary"))

        assert "vip promote" not in commands(keel)

    def test_take_it_now_does_not_wait_for_the_record(self, spec, keel):
        spec(cloud(appliance={"name": "mariadb", "vip": VIP},
                   overlays={"vip": "enabled"}))
        keel["status"] = [status(others=[OTHER])]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.TAKE_NOW)])

        meshscreen.primary(console, node(spec, "primary"))

        assert "vip promote" in commands(keel)

    def test_a_promote_keel_refuses_is_shown(self, spec, keel, record):
        spec(cloud(appliance={"name": "mariadb", "vip": VIP},
                   overlays={"vip": "enabled"}))
        record.write_text("")
        keel["status"] = [status(others=[OTHER])]
        keel["answers"]["vip promote"] = [(24, "", "no pair record")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert "no pair record" in boxes(console)[0][2]
        assert "vip status" not in commands(keel)

    def test_the_vip_screen_needs_a_description(self, spec, keel):
        spec.path.write_text("version: [1")

        assert not meshscreen.take_vip(FakeConsole(), node(spec, "primary"))

    def test_a_primary_that_holds_the_vip_takes_it_not_again(self, spec,
                                                            keel):
        spec(cloud(appliance={"name": "mariadb", "vip": VIP}))
        keel["status"] = [status(vip={"declared": VIP, "role": "primary",
                                      "holder": ME})]

        assert meshscreen.take_vip(FakeConsole(), node(spec, "primary"))
        assert commands(keel) == []

    def test_declaring_the_primary_stops_where_keel_does(self, spec, keel):
        spec(cloud())
        keel["status"] = [(16, "", "")]

        assert not meshscreen.declare_primary(FakeConsole(),
                                              node(spec, "primary"), VIP)
        spec.path.write_text("version: [1")
        assert not meshscreen.declare_primary(FakeConsole(),
                                              node(spec, "primary"), VIP)

    def test_a_primary_declared_already_is_not_written_again(self, spec,
                                                            keel):
        document = keelcli.with_server(
            meshscreen.with_vip(cloud(), VIP),
            {"engine": "mariadb", "role": "primary",
             "listen": [ME, "::1", "127.0.0.1"]})
        spec(document)
        keel["status"] = [status()]

        assert meshscreen.declare_primary(FakeConsole(),
                                          node(spec, "primary"), VIP)
        assert commands(keel) == []

    def test_an_invite_whose_primary_keel_refuses_shows_no_line(
        self, spec, keel, terminal
    ):
        spec(cloud())
        keel["status"] = [status()]
        keel["answers"]["mesh invite"] = [(0, json.dumps(INVITED))]
        keel["answers"]["spec validate"] = [(0, "", ""), (3, "", "role")]
        console = FakeConsole()

        meshscreen.primary(console, node(spec, "primary"))

        assert terminal["lines"] == []
        assert "role" in boxes(console)[0][2]

    def test_a_primary_keel_refuses_to_write_stops(self, spec, keel):
        spec(cloud())
        keel["status"] = [status()]
        keel["answers"]["spec validate"] = [(3, "", "no")]

        assert not meshscreen.declare_primary(FakeConsole(),
                                              node(spec, "primary"), VIP)


class TestJoinAMesh:
    def test_the_line_goes_on_standard_input(self, keel, terminal):
        console = FakeConsole(inputs=[("ok", f" {LINE} ")])

        assert meshscreen.join(console)

        assert keel["terminal"] == [(["mesh", "join", "-"], TOKEN + "\n")]
        (_, title, text, init), = console.calls
        assert title == "Join a mesh"
        assert init == ""
        assert terminal["lines"][0][0] == "Join a mesh"
        assert "keel mesh accept" in terminal["lines"][0][2]
        assert terminal["prompts"] == [meshscreen.PRESS_ENTER]

    def test_an_accept_line_pasted_here_is_sent_back(self, keel, terminal):
        console = FakeConsole(inputs=[("ok", "keel mesh accept keel1a:x"),
                                      ("cancel", "")])

        assert not meshscreen.join(console)

        assert "goes on the INVITING node" in boxes(console)[0][2]
        assert keel["terminal"] == []

    def test_no_token_is_asked_again(self, keel, terminal):
        console = FakeConsole(inputs=[("ok", "hello"), ("ok", TOKEN)])

        assert meshscreen.join(console)

        assert "not an invite line" in boxes(console)[0][2]

    def test_a_mistyped_line_is_asked_again(self, keel, terminal):
        keel["codes"] = [23, 0]
        console = FakeConsole(inputs=[("ok", TOKEN), ("ok", TOKEN)])

        assert meshscreen.join(console)

        assert "mistyped" in boxes(console)[0][2]

    def test_a_refused_join_stops(self, keel, terminal):
        keel["codes"] = [24]
        console = FakeConsole(inputs=[("ok", TOKEN)])

        assert not meshscreen.join(console)
        assert "refused" in boxes(console)[0][2]

    def test_without_keel_it_stops(self, keel, terminal):
        keel["codes"] = [keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        assert not meshscreen.join(FakeConsole(inputs=[("ok", TOKEN)]))

    def test_the_line_box_runs_in_a_private_directory(self, keel, terminal):
        import os

        seen = []

        class Watching(FakeConsole):
            def inputbox(self, title, text, init="", **kwargs):
                seen.append(os.environ.get("TMPDIR", ""))
                return super().inputbox(title, text, init, **kwargs)

        meshscreen.ask_line(Watching(inputs=[("ok", "x")]), "t", "x")

        assert os.path.basename(seen[0]).startswith(dbscreen.PRIVATE_PREFIX)


class TestTheReplica:
    def joined_states(self, *more):
        return [status(in_mesh=False), status(others=[OTHER],
                                              vip={"proposed": VIP}), *more]

    def test_the_whole_flow_in_cloud_simple(self, spec, keel, terminal):
        spec(cloud())
        keel["status"] = self.joined_states(
            status(others=[OTHER], vip={"proposed": VIP}),
            status(others=[OTHER], vip={"declared": VIP,
                                        "holder": OTHER}))
        console = FakeConsole(inputs=[("ok", LINE)], yesno=["ok"])

        meshscreen.replica(console, node(spec, "replica"))

        found = read(spec.path)
        assert found["appliance"]["vip"] == VIP
        assert found["overlays"]["vip"] == "enabled"
        assert found["database"]["server"] == {
            "engine": "mariadb", "role": "replica",
            "listen": [ME, "::1", "127.0.0.1"],
            "replication": {"primary": {"host": OTHER}}}
        assert commands(keel) == [
            "spec validate --no-secret-files", f"vip pair {OTHER}",
            "spec apply --system-only", "vip status", "mesh status",
            "database status"]
        assert "REPLACES the data" in [
            call[1] for call in console.calls if call[0] == "yesno"][0]
        assert keelcli.NO_FAILOVER in [
            call[2] for call in boxes(console)
            if call[1] == "Pair with the primary"][-1]
        assert titles(console)[-1] == "Status of this node"

    def test_the_local_database_is_dropped_only_after_a_yes(self, spec,
                                                            keel):
        spec(cloud())
        keel["status"] = [status(others=[OTHER], vip={"proposed": VIP}),
                          status(others=[OTHER], vip={"proposed": VIP,
                                                      "holder": OTHER})]
        keel["answers"]["spec apply"] = [(16, REFUSAL, ""), (0, "", "")]
        console = FakeConsole(yesno=["ok", "ok"])

        meshscreen.replica(console, node(spec, "replica"))

        assert keel["calls"][-4][-1] == "--destroy-local-database"

    def test_cloud_advanced_pairs_once_etcd_has_three_voters(self, spec,
                                                             keel):
        spec(cloud("cloud_advanced"))
        keel["status"] = [
            status(others=[OTHER], vip={"proposed": VIP}),
            status(others=[OTHER, THIRD], vip={"proposed": VIP},
                   etcd=FORMED),
            status(others=[OTHER, THIRD], vip={"proposed": VIP},
                   etcd=FORMED),
            status(others=[OTHER, THIRD], etcd=FORMED,
                   vip={"holder": OTHER})]
        console = FakeConsole(yesno=["ok"])

        meshscreen.replica(console, node(spec, "replica", "cloud_advanced"))

        assert f"vip pair {OTHER}" in commands(keel)
        assert keelcli.ADVANCED_FAILOVER in [
            call[2] for call in boxes(console)
            if call[1] == "Pair with the primary"][-1]

    def test_with_several_members_the_operator_names_the_primary(
        self, spec, keel
    ):
        spec(cloud("cloud_advanced"))
        keel["status"] = [status(others=[THIRD, OTHER], etcd=FORMED,
                                 vip={"proposed": VIP, "holder": OTHER})]
        console = FakeConsole(menus=[("ok", OTHER)], yesno=["ok"])

        meshscreen.replica(console, node(spec, "replica", "cloud_advanced"))

        (_, title, _, choices), = [one for one in console.calls
                                   if one[0] == "menu"]
        assert title == "Primary of the pair"
        assert [tag for tag, _ in choices] == [THIRD, OTHER]
        assert f"vip pair {OTHER}" in commands(keel)

    def test_no_primary_named_stops(self, spec, keel):
        spec(cloud())
        keel["status"] = [status(others=[THIRD, OTHER])]

        meshscreen.replica(FakeConsole(menus=[("esc", "")]),
                           node(spec, "replica"))

        assert commands(keel) == []

    def test_no_member_has_no_primary(self, spec, keel):
        spec(cloud())
        keel["status"] = [status()]
        console = FakeConsole()

        meshscreen.replica(console, node(spec, "replica"))

        assert boxes(console)[0][1] == "Primary of the pair"

    def test_a_join_left_is_finished_later(self, spec, keel, terminal):
        spec(cloud())
        keel["status"] = [status(in_mesh=False)]
        console = FakeConsole(inputs=[("cancel", "")])

        meshscreen.replica(console, node(spec, "replica"))

        assert "Database mode > Cloud > Replica" in boxes(console)[-1][2]

    def test_a_status_that_fails_stops_the_replica(self, spec, keel):
        keel["status"] = [(16, "", "")]

        meshscreen.replica(FakeConsole(), node(spec, "replica"))

        assert commands(keel) == []

    def test_etcd_left_for_later(self, spec, keel):
        spec(cloud("cloud_advanced"))
        keel["status"] = [status(others=[OTHER])]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        meshscreen.replica(console, node(spec, "replica", "cloud_advanced"))

        assert "vip pair" not in " ".join(commands(keel))

    def test_a_join_with_no_vip_cannot_pair(self, spec, keel):
        spec(cloud())
        keel["status"] = [status(others=[OTHER])]
        console = FakeConsole()

        meshscreen.replica(console, node(spec, "replica"))

        assert "received no VIP" in boxes(console)[0][2]

    def test_no_to_the_copy_changes_nothing(self, spec, keel):
        spec(cloud())
        keel["status"] = [status(others=[OTHER], vip={"proposed": VIP})]
        console = FakeConsole(yesno=["cancel"])

        meshscreen.replica(console, node(spec, "replica"))

        assert commands(keel) == []
        assert read(spec.path) == cloud()

    def test_a_pair_keel_refuses_leaves_the_description_unapplied(
        self, spec, keel
    ):
        spec(cloud())
        keel["status"] = [status(others=[OTHER], vip={"proposed": VIP})]
        keel["answers"]["vip pair"] = [(24, "", "another pair has it")]
        console = FakeConsole(yesno=["ok"])

        meshscreen.replica(console, node(spec, "replica"))

        assert "another pair has it" in boxes(console)[0][2]
        assert "spec apply --system-only" not in commands(keel)
        assert read(spec.path)["appliance"]["vip"] == VIP

    def test_a_pair_of_files(self, spec, keel):
        spec(cloud(name="web"))
        keel["status"] = [status(others=[OTHER], vip={"proposed": VIP,
                                                      "holder": OTHER})]
        console = FakeConsole()

        meshscreen.replica(console, node(spec, "replica", engine="",
                                         files=True))

        assert "database" not in read(spec.path)
        assert commands(keel) == [
            "spec validate --no-secret-files", f"vip pair {OTHER}",
            "spec apply --system-only", "vip status", "mesh status"]
        assert [call[1] for call in console.calls if call[0] == "yesno"] \
            == []

    def test_a_pair_of_files_keel_refuses_to_write_stops(self, spec, keel):
        spec(cloud(name="web"))
        keel["status"] = [status(others=[OTHER], vip={"proposed": VIP})]
        keel["answers"]["spec validate"] = [(3, "", "no")]

        meshscreen.replica(FakeConsole(), node(spec, "replica", engine="",
                                               files=True))

        assert "vip pair" not in " ".join(commands(keel))

    def test_a_pair_of_files_whose_apply_fails_stops(self, spec, keel):
        spec(cloud(name="web"))
        keel["status"] = [status(others=[OTHER], vip={"proposed": VIP,
                                                      "holder": OTHER})]
        keel["answers"]["spec apply"] = [(16, "", "syncthing: no")]
        console = FakeConsole()

        meshscreen.replica(console, node(spec, "replica", engine="",
                                         files=True))

        assert "vip status" not in commands(keel)
        assert "syncthing: no" in boxes(console)[-1][2]

    def test_the_pair_step_needs_the_status_and_the_description(
        self, spec, keel
    ):
        keel["status"] = [(16, "", "")]
        assert not meshscreen.pair_replica(FakeConsole(),
                                           node(spec, "replica"), OTHER)

    def test_core_joins_and_pairs_nothing(self, spec, keel, terminal):
        spec(cloud(name="core"))
        keel["status"] = [status(others=[OTHER])]

        meshscreen.replica(FakeConsole(), node(spec, "replica", engine=""))

        assert commands(keel) == ["mesh status"]


class TestTheWitness:
    def test_it_joins_and_waits_for_etcd(self, spec, keel, terminal):
        spec(cloud("cloud_advanced", name="core"))
        keel["status"] = [status(in_mesh=False),
                          status(others=[ME]),
                          status(others=[ME, OTHER], etcd=FORMED)]
        console = FakeConsole(inputs=[("ok", LINE)])

        meshscreen.witness(console, node(spec, "witness", "cloud_advanced",
                                         engine=""))

        assert commands(keel) == ["mesh status"]
        assert "appliance" in read(spec.path)
        assert "vip" not in read(spec.path)["appliance"]
        assert titles(console)[-1] == "Status of this node"

    def test_a_join_left_is_said(self, spec, keel, terminal):
        keel["status"] = [status(in_mesh=False)]
        console = FakeConsole(inputs=[("cancel", "")])

        meshscreen.witness(console, node(spec, "witness", "cloud_advanced",
                                         engine=""))

        assert boxes(console)[-1][1] == "Not finished yet"

    def test_etcd_left_for_later(self, spec, keel):
        keel["status"] = [status(others=[ME])]
        console = FakeConsole(pauses=["cancel"],
                              menus=[("ok", meshscreen.LATER)])

        meshscreen.witness(console, node(spec, "witness", "cloud_advanced",
                                         engine=""))

        assert boxes(console)[-1][1] == "Not finished yet"


class TestTheStatusScreen:
    def test_without_keel_it_says_so(self, keel):
        keel["answers"]["vip status"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole()

        meshscreen.done(console, meshscreen.Node("p", "cloud_simple",
                                                 "primary", "mariadb"))

        assert [one[2] for one in boxes(console)] == [keelcli.NOT_INSTALLED]


class TestFromTheMenu:
    def test_a_simple_node_has_no_cloud_flow(self, spec, keel):
        spec({"version": 1, "installation": {"mode": "simple"}})
        console = FakeConsole()

        meshscreen.from_menu(console, "primary")

        assert "not in a cloud mode" in boxes(console)[0][2]
        assert keel["calls"] == []

    def test_a_cloud_node_runs_the_flow_of_its_role(self, spec, keel,
                                                    manifests, monkeypatch):
        spec(cloud())
        ran = []
        monkeypatch.setitem(meshscreen.ROLES, "replica",
                            lambda console, found: ran.append(found))

        meshscreen.from_menu(FakeConsole(), "replica")

        assert ran == [meshscreen.Node(str(spec.path), "cloud_simple",
                                       "replica", "mariadb")]

    def test_a_description_that_does_not_read_is_shown(self, spec, keel):
        spec.path.write_text("version: [1")
        console = FakeConsole()

        meshscreen.from_menu(console, "primary")

        assert "not valid YAML" in boxes(console)[0][2]
