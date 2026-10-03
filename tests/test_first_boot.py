"""The first boot screens: this node's role, then the Keel Cloud key.

Handbook decision 0020: the role is chosen at installation, by hand, on
each node, and a Keel Cloud API key is offered there and never required.
keelfirstboot.py is the entry point the inithooks hooks call; the steps of
a primary or a replica are confconsole's own overlay and database mode
screens. No dialog opens and no keel runs: keelcli.call is replaced, and
the console is the scripted fake of conftest.
"""

import os
import runpy
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import dbscreen
import keelcli
import keelfirstboot
import plugin
import wgscreen
from conftest import FakeConsole, make_result
from test_overlay_screen import keel_with_overlay

THIS_KEY = "d+/mhJ0q/+k98Qcrm0cE/3nDyD+zg3KbaFaMMOTAvVw="
PEER_KEY = "0niNkgzhpbKmTSrWCzukb6jaYogKZkGhW+xWlh52Mh8="
SERVER = {"engine": "mariadb", "role": "standalone"}
OVERLAY = {"address": "fd00:6b65:1::2/64"}
PEER = {"public_key": PEER_KEY, "allowed_ips": ["fd00:6b65:1::1/128"],
        "endpoint": "[2001:db8::10]:51820"}
ENTRY = (Path(__file__).resolve().parent.parent / "plugins.d" / "Instance"
         / "Keel_Cloud.py")


@pytest.fixture(autouse=True)
def cloud_on(cloud):
    """Keel Cloud available, so its screens are the ones under test; the
    tests of the gate turn it off again"""
    cloud.write_text("https://cloud.example\n")
    return cloud


@pytest.fixture
def keel(monkeypatch):
    """Replace keelcli.call; `answers` steer it by the command's first
    words, anything else answers 0 with no output."""
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
    monkeypatch.setattr(keelfirstboot.shutil, "which",
                        lambda name: f"/usr/bin/{name}")
    return state


@pytest.fixture
def spec(tmp_path, monkeypatch):
    path = tmp_path / "instance.yaml"
    monkeypatch.setenv("KEEL_SPEC", str(path))

    def _write(document):
        path.write_text(yaml.safe_dump(document))
        return path

    _write.path = path
    return _write


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    where = tmp_path / "secrets" / "cloud_api_key"
    monkeypatch.setattr(keelfirstboot, "DEFAULT_CLOUD_KEY", str(where))
    return where


def read(path):
    return yaml.safe_load(Path(path).read_text())


def commands(keel):
    return [" ".join(argv[:2]) for argv in keel["calls"]]


def boxes(console):
    return [call for call in console.calls if call[0] == "msgbox"]


class TestMain:
    """What the hooks run: which step, and when it is not asked at all"""

    @pytest.fixture
    def steps(self, monkeypatch):
        ran = []
        monkeypatch.setattr(keelfirstboot, "STEPS", {
            "role": lambda *args: ran.append(("role", *args)),
            "cloud": lambda *args: ran.append(("cloud", *args)),
        })
        monkeypatch.setattr(keelfirstboot, "make_console", lambda: "console")
        monkeypatch.setattr(keelfirstboot, "draw_on_terminal", lambda: True)
        return ran

    @pytest.mark.parametrize("argv", [[], ["other"], ["role", "cloud"]])
    def test_a_step_it_does_not_know_is_a_usage_error(
        self, argv, capsys, steps
    ):
        assert keelfirstboot.main(argv, {}) == 1
        assert "role|cloud" in capsys.readouterr().err
        assert steps == []

    def test_the_script_is_its_own_entry_point(self, monkeypatch, capsys):
        monkeypatch.setattr(keelfirstboot.sys, "argv", ["keelfirstboot.py"])

        with pytest.raises(SystemExit) as stopped:
            runpy.run_path(keelfirstboot.__file__, run_name="__main__")

        assert stopped.value.code == 1
        assert "role|cloud" in capsys.readouterr().err

    def test_the_role_is_asked_on_a_terminal(self, keel, spec, steps):
        spec({"version": 1})

        assert keelfirstboot.main(["role"], {}) == 0

        assert steps == [("role", "console", str(spec.path),
                          {"version": 1})]

    def test_a_description_that_does_not_read_is_said_and_not_asked(
        self, keel, spec, steps, capsys
    ):
        spec.path.write_text("version: [1")

        assert keelfirstboot.main(["role"], {}) == 0

        assert steps == []
        assert "not valid YAML" in capsys.readouterr().err

    def test_a_declared_role_is_not_asked(self, keel, spec, steps, capsys):
        spec({"version": 1, "database": {"server": SERVER}})

        assert keelfirstboot.main(["role"], {}) == 0

        assert steps == []
        assert "database.server.role is declared (standalone)" in (
            capsys.readouterr().err)

    def test_keel_init_asks_even_a_declared_role(self, keel, spec, steps):
        spec({"version": 1, "database": {"server": SERVER}})

        keelfirstboot.main(["role"], {"_TURNKEY_INIT": "1"})

        assert [one[0] for one in steps] == ["role"]

    def test_without_keel_nothing_is_asked(
        self, keel, spec, steps, monkeypatch, capsys
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelfirstboot.shutil, "which", lambda name: None)

        assert keelfirstboot.main(["cloud"], {}) == 0

        assert steps == []
        assert "keel is not installed" in capsys.readouterr().err

    def test_without_a_terminal_the_node_stays_standalone(
        self, keel, spec, steps, monkeypatch, capsys
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelfirstboot, "draw_on_terminal", lambda: False)

        assert keelfirstboot.main(["role"], {}) == 0

        assert steps == []
        assert "stays standalone" in capsys.readouterr().err

    def test_a_declared_key_is_not_asked(self, keel, spec, steps, capsys):
        spec({"version": 1, "hub": {"api_key": "skip"}})

        keelfirstboot.main(["cloud"], {})

        assert steps == []
        assert "hub.api_key is declared" in capsys.readouterr().err

    def test_a_preseeded_skip_is_not_asked(self, keel, spec, steps, capsys):
        spec({"version": 1})

        keelfirstboot.main(["cloud"], {"HUB_APIKEY": "SKIP"})

        assert steps == []
        assert keel["calls"] == []
        assert "HUB_APIKEY is SKIP" in capsys.readouterr().err

    @pytest.mark.parametrize("preseeded", ["SKIP", "skip", "KEY123"])
    def test_keel_init_ignores_the_preseed_and_asks(
        self, keel, spec, steps, key_file, preseeded
    ):
        # A preseeded SKIP was stored as the literal key "SKIP" under
        # keel-init (review of confconsole#15).
        spec({"version": 1})

        keelfirstboot.main(["cloud"], {"_TURNKEY_INIT": "1",
                                       "HUB_APIKEY": preseeded})

        assert [one[0] for one in steps] == ["cloud"]
        assert not key_file.exists()
        assert keel["calls"] == []

    def test_a_preseeded_key_is_stored_without_a_screen(
        self, keel, spec, steps, key_file, monkeypatch, capsys
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelfirstboot, "draw_on_terminal", lambda: False)

        keelfirstboot.main(["cloud"], {"HUB_APIKEY": "KEY123"})

        assert steps == []
        assert read(spec.path)["hub"] == {"api_key": {"file": str(key_file)}}
        assert key_file.read_text() == "KEY123\n"
        assert "stored" in capsys.readouterr().err

    def test_a_preseeded_key_that_cannot_be_stored_says_why(
        self, keel, spec, steps, key_file, capsys
    ):
        spec({"version": 1})
        keel["answers"]["spec validate"] = [(3, "", "hub: no")]

        keelfirstboot.main(["cloud"], {"HUB_APIKEY": "KEY123"})

        assert steps == []
        assert not key_file.exists()
        assert "hub: no" in capsys.readouterr().err


class TestTheTerminal:
    """dialog draws on standard output, which a hook may have piped

    Real descriptors: a pseudo terminal stands for the console, a pipe for
    the hook's pipe, and the function is pointed at them instead of 0
    and 1."""

    @pytest.fixture
    def fds(self):
        opened = []

        def _make():
            terminal, console = os.openpty()
            reading, writing = os.pipe()
            opened.extend([terminal, console, reading, writing])
            return {"console": console, "pipe": writing, "read": reading}

        yield _make
        for fd in opened:
            os.close(fd)

    def test_a_terminal_already_is_left_alone(self, fds):
        found = fds()
        assert keelfirstboot.draw_on_terminal(
            found["console"], found["console"]) is True

    def test_nothing_to_answer_on_is_no_terminal(self, fds):
        found = fds()
        assert keelfirstboot.draw_on_terminal(
            found["read"], found["console"]) is False

    def test_a_piped_stdout_draws_on_the_terminal_of_stdin(self, fds):
        found = fds()

        assert keelfirstboot.draw_on_terminal(
            found["console"], found["pipe"]) is True

        assert os.isatty(found["pipe"])

    def test_a_terminal_that_cannot_be_opened_is_none(
        self, fds, monkeypatch
    ):
        found = fds()
        monkeypatch.setattr(keelfirstboot, "terminal_path",
                            lambda stdin, tty: "/nonexistent/tty")

        assert keelfirstboot.draw_on_terminal(
            found["console"], found["pipe"]) is False
        assert not os.isatty(found["pipe"])

    def test_the_controlling_terminal_when_stdin_names_none(self, fds):
        found = fds()
        assert keelfirstboot.terminal_path(found["read"], "/dev/tty") == (
            "/dev/tty")

    def test_confconsoles_menu_passes_a_default_item_to_dialog(self):
        import confconsole

        seen = {}

        class Dialog:
            def menu(self, text, *args, **kwargs):
                seen.update(kwargs)
                return "ok", "Primary"

        console = object.__new__(confconsole.Console)
        console.console, console.height, console.width = Dialog(), 22, 65

        console.menu("t", "x", [("Primary", "p")], default_item="Primary")
        assert seen["default_item"] == "Primary"
        seen.clear()
        console.menu("t", "x", [("Primary", "p")])
        assert "default_item" not in seen

    @pytest.mark.parametrize("rows, height", [(24, 22), (25, 23), (50, 25)])
    def test_the_console_fits_the_terminal_it_draws_on(
        self, monkeypatch, rows, height
    ):
        # An LXC console is 24 rows: confconsole's 25 row boxes did not
        # fit it and were drawn over each other (role-a, 2026-09-30).
        monkeypatch.setattr(keelfirstboot.keelbanner, "terminal_size",
                            lambda: (rows, 80))

        console = keelfirstboot.make_console()

        assert (console.height, console.width) == (height, 65)


class TestTheRole:
    """One menu, Standalone first, and each choice's steps"""

    @pytest.fixture
    def flows(self, monkeypatch):
        ran = []
        for name in ("standalone", "primary", "replica"):
            monkeypatch.setitem(
                keelfirstboot.ROLES, name,
                lambda *args, name=name: ran.append((name, *args[3:])))
        return ran

    def test_the_menu_offers_standalone_first(self, keel, spec, flows):
        spec({"version": 1, "database": {"server": {"engine": "mariadb"}}})
        console = FakeConsole(menus=[("ok", "Standalone")])

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        _, title, text, choices = console.calls[0]
        assert title == keelfirstboot.ROLE_TITLE
        assert [tag for tag, _ in choices] == [
            "Standalone", "Primary", "Replica"]
        assert "Standalone is the default" in text
        assert flows == [("standalone", {"engine": "mariadb"}, "mariadb")]

    @pytest.mark.parametrize("engine", ["redis", "postgresql"])
    def test_an_engine_keel_does_not_replicate_is_not_asked(
        self, keel, spec, flows, capsys, engine
    ):
        # keel validates primary and replica for Redis and PostgreSQL but
        # applies neither; offering them would write a role nothing makes
        spec({"version": 1, "database": {"server": {"engine": engine}}})
        console = FakeConsole()

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert console.calls == []
        assert flows == []
        err = capsys.readouterr().err
        assert f"keel does not apply {engine} replication yet" in err
        assert "stays standalone" in err

    def test_the_declared_role_is_named_when_keel_init_asks_again(
        self, keel, spec, flows
    ):
        spec({"version": 1, "database": {"server": {
            **SERVER, "role": "primary"}}})
        console = FakeConsole(menus=[("ok", "Replica")])

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert "The description says: primary" in console.calls[0][2]
        assert console.menu_kwargs["default_item"] == "Primary"
        assert flows[0][0] == "replica"

    def test_a_node_with_no_role_yet_defaults_to_standalone(
        self, keel, spec, flows
    ):
        spec({"version": 1, "database": {"server": {"engine": "mariadb"}}})
        console = FakeConsole(menus=[("ok", "Standalone")])

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert console.menu_kwargs["default_item"] == "Standalone"

    def test_the_engine_comes_from_the_machine_when_undeclared(
        self, keel, spec, flows, monkeypatch
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelfirstboot, "database_server_installed",
                            lambda: True)
        monkeypatch.setattr(dbscreen, "observed_engine",
                            lambda: ("mariadb", "", ""))
        console = FakeConsole(menus=[("ok", "Primary")])

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert flows == [("primary", {}, "mariadb")]

    def test_no_server_binary_means_no_role_and_no_keel_inspect(
        self, keel, spec, flows, monkeypatch, capsys
    ):
        # 2026-10-02: keel inspect took 2 s on a Web container (8 s with a
        # quarter of a CPU) to say what the missing server binary says
        spec({"version": 1})
        monkeypatch.setattr(keelfirstboot, "database_server_installed",
                            lambda: False)
        monkeypatch.setattr(dbscreen, "observed_engine", pytest.fail)
        console = FakeConsole()

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert console.calls == []
        assert flows == []
        assert "no database server" in capsys.readouterr().err

    def test_a_machine_without_a_database_server_has_no_role_to_ask(
        self, keel, spec, flows, monkeypatch, capsys
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelfirstboot, "database_server_installed",
                            lambda: True)
        monkeypatch.setattr(dbscreen, "observed_engine",
                            lambda: ("", "nothing", ""))
        console = FakeConsole()

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert console.calls == []
        assert flows == []
        assert "no database server" in capsys.readouterr().err

    def test_a_menu_that_did_not_answer_changes_nothing(
        self, keel, spec, flows
    ):
        spec({"version": 1, "database": {"server": SERVER}})
        console = FakeConsole(menus=[("esc", "")])

        keelfirstboot.choose_role(console, str(spec.path), read(spec.path))

        assert flows == []


class TestTheServerBinaries:
    """keel's own table says which binaries prove a server is installed"""

    @pytest.fixture
    def engines(self, monkeypatch):
        """A keel.inspect.dbengines whose ENGINES name these patterns"""
        def install(*patterns):
            engine = type("Engine", (), {"server_binaries": patterns})
            module = type(sys)("keel.inspect.dbengines")
            module.ENGINES = (engine,)
            for name in ("keel", "keel.inspect"):
                monkeypatch.setitem(sys.modules, name, type(sys)(name))
            monkeypatch.setitem(sys.modules, "keel.inspect.dbengines",
                                module)
        return install

    def test_a_server_binary_present_is_installed(self, engines, tmp_path):
        engines("usr/sbin/mariadbd", "usr/lib/postgresql/*/bin/postgres")
        binary = tmp_path / "usr/lib/postgresql/17/bin/postgres"
        binary.parent.mkdir(parents=True)
        binary.touch()

        assert keelfirstboot.database_server_installed(str(tmp_path))

    def test_no_server_binary_is_not_installed(self, engines, tmp_path):
        engines("usr/sbin/mariadbd", "usr/sbin/mysqld")

        assert not keelfirstboot.database_server_installed(str(tmp_path))

    def test_without_keel_s_table_keel_is_asked(self, monkeypatch, tmp_path):
        monkeypatch.setitem(sys.modules, "keel.inspect.dbengines", None)

        assert keelfirstboot.database_server_installed(str(tmp_path))

    def test_a_table_of_another_shape_means_keel_is_asked(
        self, engines, monkeypatch, tmp_path
    ):
        engines()
        monkeypatch.delattr(sys.modules["keel.inspect.dbengines"], "ENGINES")

        assert keelfirstboot.database_server_installed(str(tmp_path))


class TestStandalone:
    def test_a_fresh_node_records_the_role_without_applying(
        self, keel, spec
    ):
        spec({"version": 1, "instance": {"hostname": "wp"}})
        console = FakeConsole()

        keelfirstboot.standalone(console, str(spec.path), read(spec.path),
                                 {}, "mariadb")

        assert read(spec.path) == {
            "version": 1, "instance": {"hostname": "wp"},
            "database": {"server": {"engine": "mariadb",
                                    "role": "standalone"}}}
        assert commands(keel) == ["spec validate"]

    def test_a_record_keel_refuses_leaves_the_file_and_says_so(
        self, keel, spec
    ):
        spec({"version": 1})
        keel["answers"]["spec validate"] = [(3, "", "bad")]
        console = FakeConsole()

        keelfirstboot.standalone(console, str(spec.path), read(spec.path),
                                 {}, "mariadb")

        assert read(spec.path) == {"version": 1}
        assert boxes(console)[0][1] == keelfirstboot.ROLE_TITLE

    def test_already_standalone_is_left_alone(self, keel, spec, monkeypatch):
        spec({"version": 1, "database": {"server": SERVER}})
        monkeypatch.setattr(keelfirstboot, "run_screen",
                            lambda *args: pytest.fail("no screen"))

        keelfirstboot.standalone(FakeConsole(), str(spec.path),
                                 read(spec.path), SERVER, "mariadb")

        assert keel["calls"] == []

    def test_a_primary_going_back_runs_the_standalone_screen(
        self, keel, spec, monkeypatch
    ):
        ran = []
        monkeypatch.setattr(keelfirstboot, "run_screen",
                            lambda console, role: ran.append(role))

        keelfirstboot.standalone(FakeConsole(), "p", {},
                                 {**SERVER, "role": "primary"}, "mariadb")

        assert ran == ["standalone"]


class TestTheScreensConfconsoleLoads:
    def test_a_mode_screen_runs_with_this_console(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "Cloud").mkdir()
        (tmp_path / "Cloud" / "02Replica.py").write_text(
            "def run():\n    console.msgbox('t', PLUGIN_PATH)\n")
        monkeypatch.setattr(keelfirstboot, "MODE_DIR", str(tmp_path))
        console = FakeConsole()

        keelfirstboot.run_screen(console, "replica")

        assert boxes(console) == [
            ("msgbox", "t", str(tmp_path / "Cloud" / "02Replica.py"))]

    def test_every_role_names_a_screen_that_exists(self):
        for relative in keelfirstboot.SCREENS.values():
            loaded = plugin.Plugin(os.path.join(keelfirstboot.MODE_DIR,
                                                relative))
            assert callable(loaded.module.run)


class TestPrimaryAndReplica:
    @pytest.fixture
    def steps(self, monkeypatch):
        state = {"overlay": THIS_KEY, "screens": [], "finished": []}
        monkeypatch.setattr(keelfirstboot, "overlay",
                            lambda console, path, role: state["overlay"])
        monkeypatch.setattr(
            keelfirstboot, "run_screen",
            lambda console, role: state["screens"].append(role))
        monkeypatch.setattr(
            keelfirstboot, "finish",
            lambda console, path, role: state["finished"].append(role))
        return state

    def test_a_primary_sets_up_the_overlay_then_its_mode(self, spec, steps):
        spec({"version": 1})
        console = FakeConsole()

        keelfirstboot.primary(console, str(spec.path), {}, {}, "mariadb")

        assert "Allow replication from" in boxes(console)[0][2]
        assert steps["screens"] == ["primary"]
        assert steps["finished"] == ["primary"]

    def test_a_primary_left_at_the_overlay_is_finished_later(
        self, spec, steps
    ):
        steps["overlay"] = None
        console = FakeConsole()

        keelfirstboot.primary(console, str(spec.path), {}, {}, "mariadb")

        assert steps["screens"] == []
        text = boxes(console)[0][2]
        assert "Overlay network" in text
        assert "Database mode > Cloud > Primary" in text

    def test_a_replica_waits_for_the_primary_to_accept_it(
        self, spec, steps
    ):
        spec({"version": 1, "network": {"overlay": {"wireguard": {
            **OVERLAY, "peers": [PEER]}}}})
        console = FakeConsole(yesno=["ok"])

        keelfirstboot.replica(console, str(spec.path), {}, {}, "mariadb")

        question = console.calls[0][1]
        assert THIS_KEY in question
        assert "fd00:6b65:1::2" in question
        assert "fd00:6b65:1::1" in question
        # the Primary screen shows the password once, when it generates
        # it; after that only the file on the primary holds it
        assert "shown when it was generated" in question
        assert dbscreen.secret_path({}) in question
        assert steps["screens"] == ["replica"]
        assert steps["finished"] == ["replica"]

    def test_a_replica_whose_primary_is_not_ready_finishes_later(
        self, spec, steps
    ):
        spec({"version": 1})
        console = FakeConsole(yesno=["cancel"])

        keelfirstboot.replica(console, str(spec.path), {}, {}, "mariadb")

        assert steps["screens"] == []
        text = boxes(console)[0][2]
        assert "Overlay network" not in text
        assert "Database mode > Cloud > Replica" in text

    def test_a_replica_left_at_the_overlay_is_finished_later(
        self, spec, steps
    ):
        steps["overlay"] = None
        console = FakeConsole()

        keelfirstboot.replica(console, str(spec.path), {}, {}, "mariadb")

        assert steps["screens"] == []
        assert "Overlay network" in boxes(console)[0][2]

    @pytest.mark.parametrize("mode, where", [
        ("simple", "Advanced > Overlay network: this node's address"),
        ("cloud_simple", "  Overlay network: this node's address"),
    ])
    def test_later_names_where_the_overlay_screen_is_in_this_mode(
        self, spec, steps, chains, mode, where
    ):
        # in a simple installation the overlay is behind Advanced
        spec({"version": 1, "appliance": {"name": "mariadb"},
              "installation": {"mode": mode}})
        steps["overlay"] = None
        console = FakeConsole()

        keelfirstboot.primary(console, str(spec.path), {}, {}, "mariadb")

        assert where in boxes(console)[0][2]


class TestFinish:
    def test_the_role_in_the_description_is_done(self, spec):
        spec({"version": 1, "database": {"server": {
            **SERVER, "role": "replica"}}})
        console = FakeConsole()

        keelfirstboot.finish(console, str(spec.path), "replica")

        assert "is a replica" in boxes(console)[0][2]

    def test_a_role_the_screen_did_not_write_is_finished_later(self, spec):
        spec({"version": 1, "database": {"server": SERVER}})
        console = FakeConsole()

        keelfirstboot.finish(console, str(spec.path), "primary")

        text = boxes(console)[0][2]
        assert "still standalone" in text
        assert "Database mode > Cloud > Primary" in text


class TestTheOverlayStep:
    @pytest.fixture
    def actions(self, monkeypatch, spec):
        """The overlay screen's own actions, each writing what it would"""
        ran = []

        def set_address(console, path, document, wireguard, key):
            # this node's own key, which Add peer refuses as a peer
            assert key == THIS_KEY.strip()
            ran.append("address")
            spec({"version": 1, "network": {"overlay": {
                "wireguard": OVERLAY}}})

        def add_peer(console, path, document, wireguard, key):
            assert key == THIS_KEY.strip()
            ran.append("peer")
            spec({"version": 1, "network": {"overlay": {"wireguard": {
                **OVERLAY, "peers": [PEER]}}}})

        monkeypatch.setitem(wgscreen.ACTIONS, wgscreen.ADDRESS, set_address)
        monkeypatch.setitem(wgscreen.ACTIONS, wgscreen.ADD, add_peer)
        return ran

    def tags(self, console, index):
        menus = [call for call in console.calls if call[0] == "menu"]
        return [tag for tag, _ in menus[index][3]]

    def test_the_key_the_address_then_continue(self, keel, spec, actions):
        spec({"version": 1})
        keel["answers"]["network wireguard key"] = [(0, THIS_KEY + "\n")]
        console = FakeConsole(menus=[
            ("ok", wgscreen.ADDRESS), ("ok", keelfirstboot.CONTINUE)])

        found = keelfirstboot.overlay(console, str(spec.path), "primary")

        assert found == THIS_KEY
        assert actions == ["address"]
        assert "confirm" in boxes(console)[0][2]
        assert self.tags(console, 0) == [wgscreen.ADDRESS,
                                         keelfirstboot.LATER]
        assert self.tags(console, 1) == [
            keelfirstboot.CONTINUE, wgscreen.ADD, wgscreen.ADDRESS,
            keelfirstboot.LATER]

    def test_a_replica_continues_only_once_the_primary_is_a_peer(
        self, keel, spec, actions
    ):
        spec({"version": 1, "network": {"overlay": {"wireguard": OVERLAY}}})
        keel["answers"]["network wireguard key"] = [(0, THIS_KEY)]
        console = FakeConsole(menus=[
            ("ok", wgscreen.ADD), ("ok", keelfirstboot.CONTINUE)])

        assert keelfirstboot.overlay(console, str(spec.path),
                                     "replica") == THIS_KEY

        assert self.tags(console, 0) == [wgscreen.ADD, wgscreen.ADDRESS,
                                         keelfirstboot.LATER]
        assert keelfirstboot.CONTINUE in self.tags(console, 1)

    @pytest.mark.parametrize("answer", [("ok", "Later"), ("cancel", "")])
    def test_later_or_back_leaves_the_step(self, keel, spec, actions,
                                           answer):
        spec({"version": 1})
        keel["answers"]["network wireguard key"] = [(0, THIS_KEY)]
        console = FakeConsole(menus=[answer])

        assert keelfirstboot.overlay(console, str(spec.path),
                                     "primary") is None

    def test_no_key_no_overlay(self, keel, spec):
        spec({"version": 1})
        keel["answers"]["network wireguard key"] = [(16, "", "no wg")]
        console = FakeConsole()

        assert keelfirstboot.overlay(console, str(spec.path),
                                     "primary") is None

    def test_a_description_that_stops_reading_leaves_the_step(
        self, keel, spec, monkeypatch
    ):
        spec({"version": 1})
        keel["answers"]["network wireguard key"] = [(0, THIS_KEY)]
        monkeypatch.setattr(keelcli, "load_description",
                            lambda path: ({}, "broken"))
        console = FakeConsole()

        assert keelfirstboot.overlay(console, str(spec.path),
                                     "primary") is None
        assert boxes(console)[-1][2] == "broken"


class TestTheCloudKey:
    def test_the_screen_says_the_key_is_optional_and_inert(
        self, keel, spec, key_file
    ):
        spec({"version": 1})
        console = FakeConsole(passwords=[("ok", "")])

        keelfirstboot.ask_key(console, str(spec.path), read(spec.path))

        _, title, text, _ = console.calls[0]
        assert title == keelfirstboot.CLOUD_TITLE
        assert "empty" in text
        assert ("The key takes effect once the Keel Cloud service exists;"
                " nothing on this appliance contacts any service now.") in text

    def test_the_box_is_sized_to_its_text(self, keel, spec, key_file,
                                          monkeypatch):
        # At dbscreen's 10 rows the text left the field no room on a 24
        # row console: "Can't make sub-window" (role-a, 2026-09-30).
        asked = []

        class Recorder:
            def _wrapper(self, dialog, text, height, width, **kwargs):
                asked.append((dialog, height, width))
                return "ok", ""

            def msgbox(self, *args, **kwargs):
                return "ok"

        spec({"version": 1})

        keelfirstboot.ask_key(Recorder(), str(spec.path), read(spec.path))

        assert asked == [("passwordbox", 0, 0)]

    def test_the_database_password_boxes_are_sized_to_their_text_too(self):
        # The Replica screen's box drew its field over its own frame and
        # lost its buttons at 10 rows (role-b, 2026-09-30).
        asked = []

        class Recorder:
            def _wrapper(self, dialog, text, height, width, **kwargs):
                asked.append((height, width))
                return "ok", " x "

        assert dbscreen.passwordbox(Recorder(), "t", "text") == "x"
        assert asked == [(0, 0)]

    def test_empty_means_standalone(self, keel, spec, key_file):
        spec({"version": 1})
        console = FakeConsole(passwords=[("ok", "")])

        keelfirstboot.ask_key(console, str(spec.path), read(spec.path))

        assert read(spec.path)["hub"] == {"api_key": "skip"}
        assert not key_file.exists()
        assert "standalone" in boxes(console)[0][2]

    def test_cancel_changes_nothing(self, keel, spec, key_file):
        spec({"version": 1})
        console = FakeConsole(passwords=[("cancel", "")])

        keelfirstboot.ask_key(console, str(spec.path), read(spec.path))

        assert read(spec.path) == {"version": 1}
        assert keel["calls"] == []
        assert boxes(console) == []

    @pytest.fixture
    def held(self, spec, key_file):
        """A node with a key this screen wrote"""
        key_file.parent.mkdir()
        key_file.write_text("OLD\n")
        return spec({"version": 1, "hub": {"api_key": {
            "file": str(key_file)}}})

    @pytest.mark.parametrize("menu", [("ok", "Keep"), ("cancel", "")])
    def test_a_held_key_is_kept_unless_asked_otherwise(
        self, keel, held, key_file, menu
    ):
        # Cancel or an empty field threw an existing key away under
        # keel-init or Instance > Keel Cloud (review of confconsole#15).
        console = FakeConsole(menus=[menu])

        keelfirstboot.ask_key(console, str(held), read(held))

        _, _, text, choices = console.calls[0]
        assert [tag for tag, _ in choices] == ["Keep", "Replace", "Remove"]
        assert str(key_file) in text
        assert key_file.read_text() == "OLD\n"
        assert read(held)["hub"] == {"api_key": {"file": str(key_file)}}
        assert keel["calls"] == []

    @pytest.mark.parametrize("answer", [("ok", ""), ("cancel", "")])
    def test_replace_with_nothing_keeps_the_key(
        self, keel, held, key_file, answer
    ):
        console = FakeConsole(menus=[("ok", "Replace")], passwords=[answer])

        keelfirstboot.ask_key(console, str(held), read(held))

        assert key_file.read_text() == "OLD\n"
        assert read(held)["hub"] == {"api_key": {"file": str(key_file)}}
        assert keel["calls"] == []

    def test_replace_writes_the_new_key(self, keel, held, key_file):
        console = FakeConsole(menus=[("ok", "Replace")],
                              passwords=[("ok", "NEW")])

        keelfirstboot.ask_key(console, str(held), read(held))

        assert key_file.read_text() == "NEW\n"
        assert "Saved" in boxes(console)[0][2]

    def test_a_key_is_a_secret_file_the_description_references(
        self, keel, spec, key_file
    ):
        spec({"version": 1, "hub": {"api_key": "skip"}})
        console = FakeConsole(passwords=[("ok", " KEY123 ")])

        keelfirstboot.ask_key(console, str(spec.path), read(spec.path))

        assert read(spec.path)["hub"] == {"api_key": {"file": str(key_file)}}
        assert key_file.read_text() == "KEY123\n"
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        assert "KEY123" not in spec.path.read_text()
        assert "KEY123" not in boxes(console)[0][2]

    def test_remove_clears_the_key_and_its_file(self, keel, held, key_file):
        console = FakeConsole(menus=[("ok", "Remove")])

        keelfirstboot.ask_key(console, str(held), read(held))

        assert read(held)["hub"] == {"api_key": "skip"}
        assert not key_file.exists()
        assert "standalone" in boxes(console)[0][2]

    def test_a_file_of_the_operators_own_is_left_where_it_is(
        self, keel, spec, key_file, tmp_path
    ):
        own = tmp_path / "mine"
        own.write_text("OLD\n")
        spec({"version": 1, "hub": {"api_key": {"file": str(own)}}})

        keelfirstboot.save_key(str(spec.path), read(spec.path), "")

        assert own.exists()

    def test_a_description_keel_refuses_writes_no_key(
        self, keel, spec, key_file
    ):
        spec({"version": 1})
        keel["answers"]["spec validate"] = [(3, "", "hub: bad")]
        console = FakeConsole(passwords=[("ok", "KEY123")])

        keelfirstboot.ask_key(console, str(spec.path), read(spec.path))

        assert read(spec.path) == {"version": 1}
        assert not key_file.exists()
        assert "was NOT changed" in boxes(console)[0][2]
        assert os.listdir(spec.path.parent) == ["instance.yaml"]

    def test_without_keel_nothing_is_written(self, keel, spec, key_file):
        spec({"version": 1})
        keel["answers"]["spec validate"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        problem = keelfirstboot.save_key(str(spec.path), read(spec.path),
                                         "KEY123")

        assert problem == keelcli.NOT_INSTALLED
        assert not key_file.exists()

    def test_a_description_that_cannot_be_staged_says_why(
        self, keel, tmp_path, key_file
    ):
        missing = tmp_path / "nowhere" / "instance.yaml"

        problem = keelfirstboot.save_key(str(missing), {"version": 1}, "K")

        assert str(missing) in problem
        assert keel["calls"] == []

    def test_a_key_that_cannot_be_written_leaves_the_description(
        self, keel, spec, key_file, monkeypatch
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelcli, "write_secret",
                            lambda path, value: f"{path}: Read-only")

        problem = keelfirstboot.save_key(str(spec.path), read(spec.path),
                                         "KEY123")

        assert "was NOT changed" in problem and "Read-only" in problem
        assert read(spec.path) == {"version": 1}
        assert os.listdir(spec.path.parent) == ["instance.yaml"]

    def test_a_commit_that_fails_takes_the_key_back(
        self, keel, spec, key_file, monkeypatch
    ):
        spec({"version": 1})
        monkeypatch.setattr(keelcli, "commit_spec",
                            lambda staged, path: f"{path}: Busy")

        problem = keelfirstboot.save_key(str(spec.path), read(spec.path),
                                         "KEY123")

        assert "was NOT changed" in problem and "Busy" in problem
        assert not key_file.exists()
        assert read(spec.path) == {"version": 1}

    def test_the_instance_menu_entry_opens_the_same_screen(
        self, keel, spec, key_file
    ):
        spec({"version": 1})
        loaded = plugin.Plugin(str(ENTRY))
        console = FakeConsole(passwords=[("ok", "KEY123")])
        loaded.updateGlobals({"console": console})

        loaded.run()

        assert read(spec.path)["hub"] == {"api_key": {"file": str(key_file)}}
        assert loaded.module.TITLE == keelfirstboot.CLOUD_TITLE

    def test_the_entry_says_when_the_description_does_not_read(
        self, keel, spec, key_file
    ):
        spec.path.write_text("version: [1")
        loaded = plugin.Plugin(str(ENTRY))
        console = FakeConsole()
        loaded.updateGlobals({"console": console})

        loaded.run()

        assert "not valid YAML" in boxes(console)[0][2]


class TestUntilKeelCloudExists:
    """Hidden by default: nobody can generate a key for a service that
    does not exist yet (the maintainer, step 8 review). keelmenu's
    CLOUD_ENDPOINT turns it on; until then nothing is asked or stored."""

    @pytest.fixture
    def steps(self, monkeypatch, cloud_on):
        cloud_on.unlink()
        ran = []
        monkeypatch.setattr(keelfirstboot, "STEPS", {
            "role": lambda *args: ran.append(("role", *args)),
            "cloud": lambda *args: ran.append(("cloud", *args)),
        })
        monkeypatch.setattr(keelfirstboot, "make_console", lambda: "console")
        monkeypatch.setattr(keelfirstboot, "draw_on_terminal", lambda: True)
        return ran

    @pytest.mark.parametrize("environ", [
        {}, {"_TURNKEY_INIT": "1"}, {"HUB_APIKEY": "KEY123"},
    ])
    def test_the_first_boot_asks_and_stores_no_key(
        self, keel, spec, steps, key_file, capsys, environ
    ):
        spec({"version": 1})

        assert keelfirstboot.main(["cloud"], environ) == 0

        assert steps == []
        assert keel["calls"] == []
        assert not key_file.exists()
        assert read(spec.path) == {"version": 1}
        assert "Keel Cloud is not available" in capsys.readouterr().err

    def test_the_role_is_still_asked(self, keel, spec, steps):
        spec({"version": 1})

        keelfirstboot.main(["role"], {})

        assert [one[0] for one in steps] == ["role"]

    def test_the_entry_run_by_name_says_so_and_asks_nothing(
        self, keel, spec, key_file, cloud_on
    ):
        cloud_on.unlink()
        spec({"version": 1})
        loaded = plugin.Plugin(str(ENTRY))
        console = FakeConsole()
        loaded.updateGlobals({"console": console})

        loaded.run()

        assert keel["calls"] == []
        (_, title, text), = boxes(console)
        assert title == keelfirstboot.CLOUD_TITLE
        assert "not available" in text


@pytest.mark.skipif(keel_with_overlay() is None,
                    reason="no keel 0.11 or later (set KEEL)")
class TestWithTheRealKeel:
    """What the first boot writes, judged by keel's own validation"""

    def validate(self, tmp_path, document):
        path = tmp_path / "instance.yaml"
        path.write_text(keelcli.render_spec(document))
        return subprocess.run(
            [keel_with_overlay(), "spec", "validate", "--no-secret-files",
             "--spec", str(path)], capture_output=True, text=True,
            check=False,
        )

    @pytest.mark.parametrize("document", [
        {"version": 1, "database": {"server": {"engine": "mariadb",
                                               "role": "standalone"}}},
        {"version": 1, "hub": {"api_key": "skip"}},
        {"version": 1, "hub": {"api_key": {
            "file": keelfirstboot.DEFAULT_CLOUD_KEY}}},
    ])
    def test_what_the_first_boot_records_validates(self, tmp_path,
                                                   document):
        done = self.validate(tmp_path, document)
        assert done.returncode == 0, done.stderr


class TestSaying:
    def test_what_is_not_asked_goes_to_stderr_which_is_the_journal(
        self, capsys
    ):
        keelfirstboot.say("role", "why")
        assert capsys.readouterr().err == "keelfirstboot role: why\n"
