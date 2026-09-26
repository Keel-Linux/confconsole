"""The Instance menu entries, loaded the way confconsole loads them.

Each entry is loaded through `plugin.Plugin`, given a fake console the
way `PluginManager.updateGlobals` does, and run with `keelcli.call`
replaced, so no dialog opens and no keel runs. The entries only collect
input, call the helper and show its text.
"""

import json
from pathlib import Path

import pytest

import keelcli
import plugin
from conftest import FakeConsole

INSTANCE_DIR = (
    Path(__file__).resolve().parent.parent / "plugins.d" / "Instance"
)
ENTRIES = ["View_spec.py", "Apply_spec.py", "Show_drift.py", "Export_spec.py"]
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


class TestLoader:
    def test_the_directory_holds_four_executable_entries(self):
        manager = plugin.PluginManager(str(INSTANCE_DIR), {})

        names = sorted(
            Path(path).name
            for path, item in manager.path_map.items()
            if isinstance(item, plugin.Plugin)
        )

        assert names == sorted(ENTRIES)
        assert (INSTANCE_DIR / "description").read_text().strip()

    @pytest.mark.parametrize("name", ENTRIES)
    def test_every_entry_has_a_docstring_for_the_menu(self, entry, name):
        loaded, _ = entry(name)

        assert loaded.module.__doc__.strip()
        assert callable(loaded.module.run)


@pytest.mark.parametrize("name", ENTRIES)
def test_missing_keel_shows_one_message_and_returns(entry, keel, name):
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
