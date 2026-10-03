"""The Instance menu entries, loaded the way confconsole loads them.

Each entry is loaded through `plugin.Plugin`, given a fake console the
way `PluginManager.updateGlobals` does, and run with `keelcli.call`
replaced, so no dialog opens and no keel runs. The entries only collect
input, call the helper and show its text.
"""

import json
from pathlib import Path

import pytest
import yaml

import keelbanner
import keelcli
import keelfit
import keelmenu
import plugin
from conftest import FakeConsole

INSTANCE_DIR = (
    Path(__file__).resolve().parent.parent / "plugins.d" / "Instance"
)
ENTRIES = ["View_spec.py", "Apply_spec.py", "Show_drift.py", "Export_spec.py",
           "Overlay_network.py", "Keel_Cloud.py"]
SPEC = "/etc/keel/instance.yaml"


def make_result(argv, code=0, stdout="", stderr=""):
    return keelcli.Result(("keel", *argv), code, stdout, stderr)


@pytest.fixture
def entry(monkeypatch):
    """Load an entry with a fake console; return (plugin, console)."""
    monkeypatch.delenv("KEEL_SPEC", raising=False)

    def _load(name, **console_kwargs):
        loaded = plugin.Plugin(str(INSTANCE_DIR / name))
        console = FakeConsole(**console_kwargs)
        loaded.updateGlobals({"console": console})
        return loaded, console

    return _load


@pytest.fixture
def keel(monkeypatch):
    """Replace keelcli.call; `calls` records argv, `outcome` steers it."""
    state = {"calls": [], "outcome": make_result([])}

    def fake_call(argv):
        state["calls"].append(argv)
        if isinstance(state["outcome"], Exception):
            raise state["outcome"]
        return make_result(argv, *state["outcome"][1:])

    monkeypatch.setattr(keelcli, "call", fake_call)
    return state


def messages(console):
    return [call for call in console.calls if call[0] == "msgbox"]


MODE_ENTRIES = [
    "Database_mode/01Standalone.py",
    "Database_mode/Cloud/01Primary.py",
    "Database_mode/Cloud/02Replica.py",
    "Database_mode/Cloud/03Promote_this_replica.py",
]


class TestLoader:
    def test_the_menu_holds_the_spec_entries_and_the_mode_screens(self):
        manager = plugin.PluginManager(str(INSTANCE_DIR), {})

        found = sorted(
            str(Path(path).relative_to(INSTANCE_DIR))
            for path, item in manager.path_map.items()
            if isinstance(item, plugin.Plugin)
        )

        assert found == sorted(ENTRIES + MODE_ENTRIES)
        assert (INSTANCE_DIR / "description").read_text().strip()

    @pytest.mark.parametrize(
        "directory", ["Database_mode", "Database_mode/Cloud"]
    )
    def test_every_submenu_describes_itself(self, directory):
        assert (INSTANCE_DIR / directory / "description").read_text().strip()

    def test_the_modes_are_offered_in_the_order_decision_0013_settled(self):
        """Standalone, then Cloud, and inside Cloud primary before replica

        The menu is sorted by path, so the numeric prefixes are the order
        and the displayed names have them stripped.
        """
        inside = sorted(
            path.name
            for path in (INSTANCE_DIR / "Database_mode").iterdir()
            if path.name != "__pycache__"
        )

        assert inside == ["01Standalone.py", "Cloud", "description"]
        assert [
            plugin.Plugin(
                str(INSTANCE_DIR / "Database_mode" / "Cloud" / name)
            ).name
            for name in sorted(
                one.name
                for one in (INSTANCE_DIR / "Database_mode" / "Cloud").iterdir()
                if one.suffix == ".py"
            )
        ] == ["Primary.py", "Replica.py", "Promote this replica.py"]

    @pytest.mark.parametrize("name", ENTRIES)
    def test_every_entry_has_a_docstring_for_the_menu(self, entry, name):
        loaded, _ = entry(name)

        assert loaded.module.__doc__.strip()
        assert callable(loaded.module.run)


@pytest.mark.parametrize("name", ENTRIES)
def test_missing_keel_shows_one_message_and_returns(entry, keel, name,
                                                     cloud):
    cloud.write_text("https://cloud.example\n")  # Keel Cloud's screen open
    keel["outcome"] = keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)
    loaded, console = entry(
        name, yesno=["ok"], inputs=[("ok", "/root/instance.yaml")]
    )

    loaded.run()

    assert messages(console) == [
        ("msgbox", loaded.module.TITLE, keelcli.NOT_INSTALLED)
    ]
    assert len(keel["calls"]) == 1


class TestViewSpec:
    def test_validates_without_secret_files_and_shows_the_file(
        self, entry, keel, monkeypatch, tmp_path
    ):
        spec = tmp_path / "instance.yaml"
        spec.write_text("version: 1\n")
        monkeypatch.setenv("KEEL_SPEC", str(spec))
        keel["outcome"] = (
            None, 0, f"{spec}: ok (secret files not checked)\n"
        )
        loaded, console = entry("View_spec.py")

        loaded.run()

        assert keel["calls"] == [
            ["spec", "validate", "--no-secret-files", "--spec", str(spec)]
        ]
        (_, title, text), = messages(console)
        assert title == "Instance spec"
        assert "version: 1" in text
        assert text.endswith("keel validate: exit 0, the spec is valid")


class TestApplySpec:
    def test_confirms_then_applies_non_interactively(self, entry, keel):
        keel["outcome"] = (
            None, 0, f"{SPEC} applied to /etc/inithooks.conf\n"
        )
        loaded, console = entry("Apply_spec.py", yesno=["ok"])

        loaded.run()

        assert keel["calls"] == [
            ["spec", "apply", "--spec", SPEC, "--non-interactive"]
        ]
        question = console.calls[0]
        assert question[0] == "yesno"
        command = f"keel spec apply --spec {SPEC} --non-interactive"
        assert command in question[1]
        (_, _, text), = messages(console)
        assert text.endswith("keel apply: exit 0, the spec was applied")

    def test_declining_runs_nothing(self, entry, keel):
        loaded, console = entry("Apply_spec.py", yesno=["cancel"])

        loaded.run()

        assert keel["calls"] == []
        assert messages(console) == []

    def test_an_invalid_spec_maps_to_its_message(self, entry, keel):
        keel["outcome"] = (None, 3, "", "Error: instance.hostname: empty\n")
        loaded, console = entry("Apply_spec.py", yesno=["ok"])

        loaded.run()

        (_, _, text), = messages(console)
        assert "Error: instance.hostname: empty" in text
        assert "exit 3, the spec is valid YAML but fails validation" in text


class TestShowDrift:
    @pytest.fixture(autouse=True)
    def terminal(self, monkeypatch):
        monkeypatch.setattr(keelbanner, "terminal_size", lambda: (24, 80))

    def test_a_table_too_wide_for_80_columns_is_stacked(self, entry, keel):
        long = "network.interfaces.eth0.ipv6.method"
        document = {"fields": [{"field": long, "status": "drift",
                                "declared": "x" * 30, "observed": "auto",
                                "reason": ""}],
                    "counts": {"drift": 1}, "drift": True}
        keel["outcome"] = (None, 14, json.dumps(document))
        loaded, console = entry("Show_drift.py")

        loaded.run()

        (_, _, text), = messages(console)
        assert text.splitlines()[:2] == [
            f"{long}: drift", f"    declared {'x' * 30}, observed auto"]

    def test_renders_the_json_as_a_table(self, entry, keel):
        document = {
            "fields": [
                {
                    "field": "instance.hostname",
                    "status": "drift",
                    "declared": "blog",
                    "observed": "core",
                    "reason": "",
                }
            ],
            "counts": {"same": 0, "drift": 1},
            "drift": True,
        }
        keel["outcome"] = (None, 14, json.dumps(document))
        loaded, console = entry("Show_drift.py")

        loaded.run()

        assert keel["calls"] == [["diff", "--spec", SPEC, "--format", "json"]]
        (_, title, text), = messages(console)
        assert title == "Instance drift"
        lines = text.splitlines()
        assert lines[0].split() == ["field", "status", "declared", "observed"]
        assert lines[1].split() == [
            "instance.hostname", "drift", "blog", "core"
        ]
        assert "diff: 0 same, 1 drift" in text
        assert text.endswith(
            "keel diff: exit 14, drift found: at least one declared field"
            " differs on the machine"
        )


class TestExportSpec:
    def test_inspects_to_the_typed_path_and_shows_the_report(
        self, entry, keel, tmp_path
    ):
        output = tmp_path / "instance.yaml"
        report = tmp_path / "instance.report.txt"
        report.write_text("instance.hostname: /etc/hostname\n")
        keel["outcome"] = (None, 13)
        loaded, console = entry(
            "Export_spec.py", inputs=[("ok", f" {output} ")]
        )

        loaded.run()

        assert keel["calls"] == [
            ["inspect", "--output", str(output), "--report", str(report)]
        ]
        prompt = console.calls[0]
        assert prompt[0] == "inputbox"
        assert prompt[3] == "/root/instance.yaml"
        (_, title, text), = messages(console)
        assert title == "Export instance spec"
        assert f"spec: {output}\nreport: {report}" in text
        assert "instance.hostname: /etc/hostname" in text
        assert "exit 13, spec written, but some fields could not be" in text

    @pytest.mark.parametrize(
        "answer", [("cancel", "/root/x.yaml"), ("ok", "  ")]
    )
    def test_cancel_or_an_empty_path_runs_nothing(self, entry, keel, answer):
        loaded, console = entry("Export_spec.py", inputs=[answer])

        loaded.run()

        assert keel["calls"] == []
        assert messages(console) == []


# --- what the Instance menu offers, from the appliance manifest (0041)

PLAIN = ["View spec", "Apply spec", "Show drift", "Export spec"]


@pytest.fixture
def instance(tmp_path, monkeypatch, chains, cloud):
    """The Instance menu, loaded as confconsole loads it, on a machine
    whose spec names `appliance` in `mode`; returns (menu, console)"""
    spec = tmp_path / "instance.yaml"
    monkeypatch.setenv("KEEL_SPEC", str(spec))

    def _load(appliance, mode="simple", menus=(("cancel", ""),), **more):
        document = {"version": 1, "appliance": {"name": appliance},
                    "installation": {"mode": mode}, **more}
        spec.write_text(yaml.safe_dump(document))
        manager = plugin.PluginManager(str(INSTANCE_DIR), {})
        menu = plugin.PluginDir(str(INSTANCE_DIR))
        menu.plugins = list(manager.getByDir(manager.plugin_path))
        for one in menu.plugins:
            one.parent = menu.path
        console = FakeConsole(menus=list(menus))
        menu.updateGlobals({"console": console})
        return menu, console

    return _load


def tags(console, which=0):
    menus = [call for call in console.calls if call[0] == "menu"]
    return [tag for tag, _ in menus[which][3]]


class TestTheMenuThisMachineShows:
    @pytest.mark.parametrize("appliance", ["web", "core"])
    def test_keel_web_and_core_have_no_database_mode(
        self, instance, appliance
    ):
        menu, console = instance(appliance)

        assert menu.run() == "advanced"

        assert sorted(tags(console)) == sorted(PLAIN + ["Advanced"])

    def test_behind_advanced_in_a_simple_installation_is_the_overlay(
        self, instance
    ):
        menu, console = instance(
            "web", menus=[("ok", "Advanced"), ("ok", "Overlay network")])

        assert menu.run() == str(INSTANCE_DIR / "Overlay_network.py")

        assert tags(console, 1) == ["Overlay network"]

    @pytest.mark.parametrize("appliance", ["web", "core"])
    def test_a_configured_overlay_stays_behind_advanced(self, instance,
                                                        appliance):
        # the same two menus before and after the first peer, so the
        # screen is where the operator found it (keel-web-2, 2026-10-03)
        overlay = {"overlay": {"wireguard": {
            "address": "fd00:6b65:1::1/64", "peers": [{
                "public_key": "0niNkgzhpbKmTSrWCzukb6jaYogKZkGhW+xWlh52Mh8=",
                "allowed_ips": ["fd00:6b65:1::2/128"]}]}}}
        menu, console = instance(
            appliance, menus=[("ok", "Advanced"), ("ok", "Overlay network")],
            overlays={"wireguard": "enabled"}, network=overlay)

        assert menu.run() == str(INSTANCE_DIR / "Overlay_network.py")

        assert sorted(tags(console)) == sorted(PLAIN + ["Advanced"])
        assert tags(console, 1) == ["Overlay network"]

    @pytest.mark.parametrize("mode", ["cloud_simple", "cloud_advanced"])
    def test_a_cloud_mode_with_an_overlay_has_no_empty_advanced(
        self, instance, mode
    ):
        menu, console = instance("web", mode,
                                 overlays={"wireguard": "enabled"})

        menu.run()

        assert sorted(tags(console)) == sorted(PLAIN + ["Overlay network"])

    def test_back_from_advanced_reopens_the_instance_menu(self, instance):
        menu, console = instance(
            "core", menus=[("ok", "Advanced"), ("cancel", "")])

        assert menu.run() == menu.path

    @pytest.mark.parametrize("mode", ["cloud_simple", "cloud_advanced"])
    def test_a_cloud_mode_shows_the_overlay_and_no_advanced(
        self, instance, mode
    ):
        menu, console = instance("web", mode)

        menu.run()

        assert sorted(tags(console)) == sorted(PLAIN + ["Overlay network"])

    def test_a_database_appliance_shows_database_mode(self, instance):
        menu, console = instance("mariadb")

        menu.run()

        assert "Database mode" in tags(console)

    def test_keel_cloud_appears_once_its_endpoint_is_set(
        self, instance, cloud
    ):
        cloud.write_text("https://cloud.example\n")
        menu, console = instance("web")

        menu.run()

        assert "Keel cloud" in tags(console)

    def test_a_choice_in_the_menu_opens_its_screen(self, instance):
        menu, _ = instance("web", menus=[("ok", "View spec")])

        assert menu.run() == str(INSTANCE_DIR / "View_spec.py")

    def test_a_tag_no_entry_has_is_confconsoles_own_action(self, instance):
        menu, _ = instance("web", menus=[("ok", "Reboot")])

        assert menu.run() == "_adv_reboot"

    def test_back_from_a_submenu_goes_to_its_parent(self, instance):
        menu, _ = instance("web")
        menu.parent = "/parent"

        assert menu.run() == "/parent"


def all_menus():
    """Every Keel menu: the Instance tree's, each with every entry"""
    manager = plugin.PluginManager(str(INSTANCE_DIR), {})
    menus = {"Instance": manager.getByDir(manager.plugin_path)}
    for path, item in manager.path_map.items():
        if isinstance(item, plugin.PluginDir):
            menus[path] = manager.getByDir(path)
    found = {}
    for name, entries in menus.items():
        items, _ = plugin.menu_items(list(entries))
        found[name] = [(tag, text.strip()) for tag, text in items]
    found["Instance"].append(keelmenu.ADVANCED_ITEM)
    return found


class TestNothingIsCutAt80Columns:
    """Every Keel menu fits the box an 80 column terminal leaves"""

    COLS = keelbanner.available(24, 80)[1]

    @pytest.mark.parametrize("name, items", sorted(all_menus().items()))
    def test_every_instance_menu(self, name, items):
        width = keelfit.menu_width(items, 65, self.COLS)

        assert keelfit.fit_choices(items, width) == items, name

    def test_the_overlay_screens_menus(self):
        import keelfirstboot
        import wgscreen

        wireguard = {"address": "fd00::1/64", "peers": [{
            "public_key": "k" * 44, "allowed_ips": ["fd00::2/128"],
            "endpoint": "[2001:db8::20]:51820"}]}
        menus = [
            wgscreen.choices(wireguard),
            wgscreen.choices(wireguard, waiting=True),
            keelfirstboot.overlay_choices("primary", wireguard),
            keelfirstboot.overlay_choices("replica", {}),
            keelfirstboot.ROLE_CHOICES,
            keelfirstboot.KEY_CHOICES,
            [keelmenu.ADVANCED_ITEM],
        ]
        for items in menus:
            width = keelfit.menu_width(items, 65, self.COLS)
            assert keelfit.fit_choices(items, width) == items
