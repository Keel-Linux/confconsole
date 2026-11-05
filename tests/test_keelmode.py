"""The Installation mode step: the modes the manifest allows, the column
written, the one move of decision 0057.

Handbook decisions 0028 and 0076. No dialog opens and no keel runs: the
facts are the `manifests` fixture's (keel.manifest.facts.gather), the
console is the scripted fake, and keelcli.call is replaced.
"""

from pathlib import Path

import pytest
import yaml

import keelcli
import keelmode
from conftest import (ALL_MODES, CORE_COLUMNS, DB_COLUMNS, FakeConsole,
                      make_result)


@pytest.fixture
def keel(monkeypatch):
    """keelcli.call replaced: `answers` steer it by the command's first
    words, anything else answers 0"""
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
    return [" ".join(argv[:3]) for argv in keel["calls"]]


def boxes(console):
    return [call for call in console.calls if call[0] == "msgbox"]


def facts(name="core", modes=ALL_MODES, columns=None, witness=False):
    return keelmode.Facts(name, tuple(modes), witness,
                          columns or CORE_COLUMNS)


class TestTheApplianceIsNamed:
    def manifest(self, root, name, base):
        where = Path(root) / keelmode.APPLIANCES
        where.mkdir(parents=True, exist_ok=True)
        (where / f"{name}.yaml").write_text(
            yaml.safe_dump({"name": name, "base": base}))

    def test_the_declared_name_is_kept(self, tmp_path):
        assert keelmode.appliance_name(
            {"appliance": {"name": "wordpress"}}, str(tmp_path)) == (
            "wordpress", "")

    def test_the_top_of_the_installed_chain_is_the_appliance(
        self, tmp_path
    ):
        self.manifest(tmp_path, "core", "none")
        self.manifest(tmp_path, "web", "core")
        self.manifest(tmp_path, "wordpress", "web")
        (tmp_path / keelmode.APPLIANCES / "README").write_text("x")

        assert keelmode.appliance_name({}, str(tmp_path)) == (
            "wordpress", "")

    def test_two_tops_are_named_and_neither_is_taken(self, tmp_path):
        self.manifest(tmp_path, "core", "none")
        self.manifest(tmp_path, "lnmp", "core")
        self.manifest(tmp_path, "lnpp", "core")

        name, problem = keelmode.appliance_name({}, str(tmp_path))

        assert name == ""
        assert problem == "lnmp and lnpp are installed, and none is built"\
            " on the other"

    def test_a_machine_of_before_0041_has_no_manifest(self, tmp_path):
        name, problem = keelmode.appliance_name({}, str(tmp_path))

        assert name == ""
        assert "no appliance manifest" in problem

    def test_a_directory_with_no_manifest_in_it_has_none(self, tmp_path):
        (tmp_path / keelmode.APPLIANCES).mkdir(parents=True)

        assert "no appliance manifest" in keelmode.appliance_name(
            {}, str(tmp_path))[1]

    @pytest.mark.parametrize("text", ["- a list\n", "base: [\n"])
    def test_a_manifest_that_does_not_read_names_no_base(
        self, tmp_path, text
    ):
        where = tmp_path / keelmode.APPLIANCES
        where.mkdir(parents=True)
        (where / "odd.yaml").write_text(text)

        assert keelmode.appliance_name({}, str(tmp_path)) == ("odd", "")

    def test_a_manifest_that_cannot_be_opened_names_no_base(self, tmp_path):
        assert keelmode.base_of(str(tmp_path / "absent.yaml")) == ""


class TestTheFacts:
    def test_they_are_keels_own(self, manifests):
        found, problem = keelmode.facts_of({"appliance": {"name": "core"}})

        assert problem == ""
        assert found.name == "core"
        assert found.modes == ALL_MODES
        assert found.witness is True
        assert list(found.columns) == list(CORE_COLUMNS)

    def test_the_engines_of_the_chain_come_with_them(self, manifests):
        found, _ = keelmode.facts_of({"appliance": {"name": "mariadb"}})

        assert found.engines == frozenset({"mariadb"})

    def test_a_chain_that_does_not_resolve_says_why(self, manifests):
        found, problem = keelmode.facts_of({"appliance": {"name": "nope"}})

        assert found is None
        assert "nope is not an installed appliance" in problem

    def test_a_chain_with_no_resolution_and_no_reason_still_says(
        self, manifests
    ):
        manifests.table["odd"] = type(manifests.table["core"])(
            problems=(), resolved=None)

        assert "does not resolve" in keelmode.facts_of(
            {"appliance": {"name": "odd"}})[1]

    def test_a_keel_that_fails_is_an_unknown_chain(self, manifests):
        manifests.table["core"] = RuntimeError("boom")

        found, problem = keelmode.facts_of({"appliance": {"name": "core"}})

        assert found is None
        assert "boom" in problem

    def test_without_keel_there_are_none(self, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules,
                            "keel.manifest.facts", None)

        found, problem = keelmode.facts_of({"appliance": {"name": "core"}})

        assert found is None
        assert problem == keelcli.NOT_INSTALLED

    def test_no_name_no_facts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(keelmode, "ROOT", str(tmp_path))

        found, problem = keelmode.facts_of({}, str(tmp_path))

        assert found is None
        assert "no appliance manifest" in problem


class TestTheColumn:
    def test_every_overlay_at_the_modes_column(self):
        assert keelmode.column(facts(), "cloud_advanced", {}) == {
            "installer": "enabled", "wireguard": "enabled",
            "etcd": "enabled", "crowdsec": "enabled", "vip": "disabled"}

    def test_a_node_of_a_pair_keeps_its_vip_overlay(self):
        found = keelmode.column(facts(), "cloud_advanced", {
            "appliance": {"vip": "fd00::ffff:1"}})

        assert found["vip"] == "enabled"

    def test_an_ask_takes_the_operators_answer(self):
        columns = {"crowdsec": {"simple": "ask"}}

        assert keelmode.column(facts(columns=columns), "simple", {},
                               {"crowdsec": "enabled"}) == {
            "crowdsec": "enabled"}
        assert keelmode.asked(facts(columns=columns), "simple") == [
            "crowdsec"]

    def test_the_description_gets_the_name_the_mode_and_the_column(self):
        document = {"version": 1, "appliance": {"vip": "fd00::ffff:1"},
                    "installation": {"other": 1}}

        found = keelmode.with_mode(document, facts(), "simple")

        assert found["appliance"] == {"vip": "fd00::ffff:1", "name": "core"}
        assert found["installation"] == {"other": 1, "mode": "simple"}
        assert found["overlays"]["wireguard"] == "disabled"
        assert document["installation"] == {"other": 1}


class TestUnattended:
    def test_a_declared_mode_is_for_the_screen(self, spec):
        assert keelmode.unattended(str(spec.path), {
            "installation": {"mode": "simple"}}) is None

    def test_no_facts_is_said_and_not_asked(self, spec, capsys,
                                            monkeypatch, tmp_path):
        monkeypatch.setattr(keelmode, "ROOT", str(tmp_path))

        assert keelmode.unattended(str(spec.path), {"version": 1}) == 0

        assert "no appliance manifest" in capsys.readouterr().err

    def test_several_modes_are_asked(self, spec, manifests):
        assert keelmode.unattended(str(spec.path), {
            "appliance": {"name": "core"}}) is None

    def test_one_mode_is_recorded_and_applied_with_no_screen(
        self, spec, manifests, keel, capsys
    ):
        manifests("redis", CORE_COLUMNS, modes=["simple"])
        spec({"version": 1, "appliance": {"name": "redis"}})

        assert keelmode.unattended(str(spec.path), read(spec.path)) == 0

        assert read(spec.path)["installation"] == {"mode": "simple"}
        assert commands(keel) == ["spec validate --no-secret-files",
                                  "spec apply --system-only"]
        assert "simple, the one mode redis allows: keel apply: exit 0" in (
            capsys.readouterr().err)

    def test_one_mode_with_a_question_is_asked(self, spec, manifests):
        manifests("odd", {"crowdsec": {"simple": "ask"}}, modes=["simple"])

        assert keelmode.unattended(str(spec.path), {
            "appliance": {"name": "odd"}}) is None

    def test_one_mode_keel_refuses_is_said(self, spec, manifests, keel,
                                           capsys):
        manifests("redis", CORE_COLUMNS, modes=["simple"])
        spec({"version": 1, "appliance": {"name": "redis"}})
        keel["answers"]["spec validate"] = [(3, "", "overlays: no")]

        keelmode.unattended(str(spec.path), read(spec.path))

        assert read(spec.path) == {"version": 1,
                                   "appliance": {"name": "redis"}}
        err = capsys.readouterr().err
        assert "was NOT recorded" in err and "overlays: no" in err


class TestTheScreen:
    def test_it_offers_the_modes_the_manifest_allows(self, spec, manifests,
                                                     keel):
        manifests("lnmp", DB_COLUMNS, modes=["simple", "cloud_simple"])
        spec({"version": 1, "appliance": {"name": "lnmp"}})
        console = FakeConsole(menus=[("ok", "Cloud simple")])

        keelmode.choose(console, str(spec.path), read(spec.path))

        _, title, text, choices = console.calls[0]
        assert title == keelmode.TITLE == "Installation mode"
        assert [tag for tag, _ in choices] == ["Simple", "Cloud simple"]
        assert "Choose the same mode on every node" in text
        assert console.menu_kwargs == {"no_cancel": True,
                                       "default_item": "Simple"}
        found = read(spec.path)
        assert found["installation"] == {"mode": "cloud_simple"}
        assert found["overlays"]["wireguard"] == "enabled"
        assert found["overlays"]["mariadb"] == "enabled"
        assert commands(keel)[-1] == "spec apply --system-only"
        (_, title, said), = boxes(console)
        assert title == "Installation mode"
        assert "installation.mode: cloud_simple" in said
        assert "keel apply: exit 0" in said

    def test_an_ask_is_a_yes_or_no(self, spec, manifests, keel):
        manifests("odd", {"crowdsec": {"simple": "ask"}}, modes=["simple"])
        spec({"version": 1, "appliance": {"name": "odd"}})
        console = FakeConsole(menus=[("ok", "Simple")], yesno=["cancel"])

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert "Turn on the overlay crowdsec?" in console.calls[1][1]
        assert read(spec.path)["overlays"] == {"crowdsec": "disabled"}

    def test_a_menu_that_did_not_answer_writes_nothing(self, spec,
                                                       manifests, keel):
        spec({"version": 1, "appliance": {"name": "core"}})
        console = FakeConsole(menus=[("esc", "")])

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert keel["calls"] == []

    def test_no_facts_is_shown(self, spec, tmp_path, monkeypatch):
        monkeypatch.setattr(keelmode, "ROOT", str(tmp_path))
        console = FakeConsole()

        keelmode.choose(console, str(spec.path), {"version": 1})

        assert "no appliance manifest" in boxes(console)[0][2]

    def test_a_description_keel_refuses_is_shown(self, spec, manifests,
                                                 keel):
        spec({"version": 1, "appliance": {"name": "core"}})
        keel["answers"]["spec validate"] = [(3, "", "bad")]
        console = FakeConsole(menus=[("ok", "Simple")])

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert "was NOT changed" in boxes(console)[0][2]
        assert commands(keel) == ["spec validate --no-secret-files"]

    def test_a_keel_that_went_away_before_the_apply_is_said(
        self, spec, manifests, keel
    ):
        spec({"version": 1, "appliance": {"name": "core"}})
        keel["answers"]["spec apply"] = [
            keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]
        console = FakeConsole(menus=[("ok", "Simple")])

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert boxes(console)[0][2] == keelcli.NOT_INSTALLED


class TestKeelInitOnANodeWithAMode:
    """The mode is chosen once; only cloud simple moves, to cloud
    advanced (decision 0057)"""

    @pytest.mark.parametrize("mode", ["simple", "cloud_advanced"])
    def test_the_mode_is_shown_and_not_changed(self, spec, manifests, keel,
                                               mode):
        spec({"version": 1, "appliance": {"name": "core"},
              "installation": {"mode": mode}})
        console = FakeConsole()

        keelmode.choose(console, str(spec.path), read(spec.path))

        (_, title, text), = boxes(console)
        assert title == "Installation mode"
        assert f"installed in the {keelmode.LABEL[mode]} mode" in text
        assert keel["calls"] == []

    def test_cloud_simple_with_no_cloud_advanced_is_only_shown(
        self, spec, manifests, keel
    ):
        manifests("two", CORE_COLUMNS, modes=["simple", "cloud_simple"])
        spec({"version": 1, "appliance": {"name": "two"},
              "installation": {"mode": "cloud_simple"}})
        console = FakeConsole()

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert "Cloud simple mode" in boxes(console)[0][2]

    @pytest.mark.parametrize("answer", [("ok", "Keep"), ("esc", "")])
    def test_keep_changes_nothing(self, spec, manifests, keel, answer):
        spec({"version": 1, "appliance": {"name": "core"},
              "installation": {"mode": "cloud_simple"}})
        console = FakeConsole(menus=[answer])

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert [tag for tag, _ in console.calls[0][3]] == [
            "Keep", "Cloud advanced"]
        assert keel["calls"] == []

    def test_the_move_writes_cloud_advanced_and_keeps_the_vip_on(
        self, spec, manifests, keel
    ):
        spec({"version": 1,
              "appliance": {"name": "mariadb", "vip": "fd00::ffff:1"},
              "installation": {"mode": "cloud_simple"},
              "overlays": {"vip": "enabled"}})
        console = FakeConsole(menus=[("ok", "Cloud advanced")])

        keelmode.choose(console, str(spec.path), read(spec.path))

        found = read(spec.path)
        assert found["installation"] == {"mode": "cloud_advanced"}
        assert found["overlays"]["etcd"] == "enabled"
        assert found["overlays"]["vip"] == "enabled"
        said = boxes(console)[-1][2]
        assert "keel mesh etcd form --dry-run" in said

    def test_a_move_keel_refuses_says_nothing_of_the_next_steps(
        self, spec, manifests, keel
    ):
        spec({"version": 1, "appliance": {"name": "core"},
              "installation": {"mode": "cloud_simple"}})
        keel["answers"]["spec validate"] = [(3, "", "bad")]
        console = FakeConsole(menus=[("ok", "Cloud advanced")])

        keelmode.choose(console, str(spec.path), read(spec.path))

        assert len(boxes(console)) == 1


class TestSaying:
    def test_it_goes_to_stderr(self, capsys):
        keelmode.say("why")

        assert capsys.readouterr().err == "keelfirstboot mode: why\n"

    def test_an_unknown_mode_is_none(self):
        assert keelmode.mode_of({"installation": {"mode": "other"}}) == ""
        assert keelmode.mode_of({"installation": "simple"}) == ""
