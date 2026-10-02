"""Which Keel screens a machine shows, read from its appliance manifest.

Handbook decision 0041: the manifests under /usr/share/keel say which
overlays and data services an appliance's chain carries, and the spec
says the installation mode. The maintainer's screenshots of Keel Web
showed Database mode, which configures a database Keel Web does not
have, and the WireGuard overlay of a simple installation in the first
menu. These tests replace keel's resolution (keel.manifest.facts.gather)
with chains written here; TestWithTheRealKeel runs keel's own where it is
installed.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest
import yaml

import keelmenu
from conftest import CORE, WEB, overlay, resolved

PLUGINS = Path(keelmenu.PLUGINS)
DATABASE = str(PLUGINS / "Instance" / "Database_mode")
OVERLAY = str(PLUGINS / "Instance" / "Overlay_network.py")
CLOUD = str(PLUGINS / "Instance" / "Keel_Cloud.py")
VIEW = str(PLUGINS / "Instance" / "View_spec.py")


@pytest.fixture
def spec(tmp_path, monkeypatch):
    path = tmp_path / "instance.yaml"
    monkeypatch.setenv("KEEL_SPEC", str(path))

    def _write(name=None, mode="simple", **more):
        document = {"version": 1, **more}
        if name:
            document["appliance"] = {"name": name}
        if mode:
            document["installation"] = {"mode": mode}
        path.write_text(yaml.safe_dump(document))
        return path

    return _write


class TestTheChain:
    def test_overlays_and_the_engines_they_provide(self, chains):
        chain = keelmenu.chain_of("mariadb")

        assert chain.overlays == frozenset(CORE + ["mariadb"])
        assert chain.engines == frozenset(["mariadb"])
        assert chains["asked"] == [("/", "mariadb")]

    def test_the_services_an_application_consumes(self, chains):
        chains["app"] = resolved(
            [overlay("nginx")],
            services={"db": {"engine": ["mariadb", "postgresql"]},
                      "cache": {"engine": "redis"}})

        assert keelmenu.chain_of("app").engines == frozenset(
            ["mariadb", "postgresql", "redis"])

    def test_an_application_with_no_services(self, chains):
        chains["app"] = resolved([overlay("nginx")], services=None)
        chains["app"].application = types.SimpleNamespace(item={})

        assert keelmenu.chain_of("app").engines == frozenset()

    def test_a_chain_keel_cannot_resolve_is_unknown(self, chains):
        assert keelmenu.chain_of("absent") is None

    def test_keel_failing_is_unknown_not_a_broken_menu(self, chains):
        chains["broken"] = OSError("unreadable")

        assert keelmenu.chain_of("broken") is None

    def test_without_keel_the_chain_is_unknown(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "keel.manifest.facts", None)

        assert keelmenu.chain_of("web") is None


class TestTheMachine:
    def test_the_spec_names_the_appliance_and_the_mode(self, chains, spec):
        spec("web", "cloud_simple")

        found = keelmenu.machine()

        assert found.chain.overlays == frozenset(WEB)
        assert found.mode == "cloud_simple"
        assert found.uses_overlay is False

    def test_a_spec_that_names_no_appliance_leaves_the_chain_unknown(
        self, chains, spec
    ):
        spec(None, None)

        found = keelmenu.machine()

        assert found.chain is None
        assert found.mode == ""
        assert chains["asked"] == []

    @pytest.mark.parametrize("text", ["- a list\n", "appliance: web\n"
                                      "installation: simple\n"])
    def test_sections_that_are_not_mappings_count_as_absent(
        self, chains, spec, text
    ):
        spec().write_text(text)

        found = keelmenu.machine()

        assert found.chain is None
        assert found.mode == ""

    def test_an_enabled_wireguard_overlay_is_in_use(self, chains, spec):
        spec("web", overlays={"wireguard": "enabled"})

        assert keelmenu.machine().uses_overlay is True

    def test_a_declared_overlay_address_is_in_use(self, chains, spec):
        spec("web", network={"overlay": {"wireguard": {
            "address": "fd00:6b65:1::1/64"}}})

        assert keelmenu.machine().uses_overlay is True


def machine(name, mode="simple", uses_overlay=False, chains=None):
    chain = keelmenu.chain_of(name) if name else None
    return keelmenu.Machine(chain, mode, uses_overlay)


class TestDatabaseMode:
    @pytest.mark.parametrize("name", ["web", "core"])
    def test_hidden_where_the_chain_has_no_database(self, chains, name):
        assert keelmenu.place(DATABASE, machine(name)) == keelmenu.HIDE

    @pytest.mark.parametrize("name", ["mariadb", "wordpress"])
    def test_shown_where_a_mariadb_service_is_in_the_chain(
        self, chains, name
    ):
        assert keelmenu.place(DATABASE, machine(name)) == keelmenu.SHOW

    def test_postgresql_counts_and_redis_does_not(self, chains):
        chains["pg"] = resolved([overlay("postgresql", "postgresql")])
        chains["cache"] = resolved([overlay("redis", "redis")])

        assert keelmenu.place(DATABASE, machine("pg")) == keelmenu.SHOW
        assert keelmenu.place(DATABASE, machine("cache")) == keelmenu.HIDE

    def test_an_unknown_chain_shows_it_as_before(self):
        # every machine of before 0041 has no manifest; hiding a screen
        # it needs is worse than offering one that says it has no server
        assert keelmenu.place(DATABASE, machine(None)) == keelmenu.SHOW


class TestOverlayNetwork:
    @pytest.mark.parametrize("mode", ["cloud_simple", "cloud_advanced"])
    def test_in_the_menu_in_the_cloud_modes(self, chains, mode):
        assert keelmenu.place(OVERLAY, machine("web", mode)) == keelmenu.SHOW

    @pytest.mark.parametrize("mode", ["simple", ""])
    def test_behind_advanced_in_a_simple_installation(self, chains, mode):
        assert keelmenu.place(OVERLAY, machine("web", mode)) == (
            keelmenu.ADVANCED)

    def test_in_the_menu_once_this_node_uses_the_overlay(self, chains):
        found = machine("web", "simple", uses_overlay=True)

        assert keelmenu.place(OVERLAY, found) == keelmenu.SHOW

    def test_hidden_where_the_chain_carries_no_wireguard(self, chains):
        chains["bare"] = resolved([overlay("installer")])

        assert keelmenu.place(OVERLAY, machine("bare", "cloud_simple")) == (
            keelmenu.HIDE)

    def test_an_unknown_chain_keeps_it_behind_advanced(self):
        assert keelmenu.place(OVERLAY, machine(None, "")) == keelmenu.ADVANCED


class TestKeelCloud:
    def test_hidden_by_default(self, chains, cloud):
        assert keelmenu.cloud_available() is False
        assert keelmenu.place(CLOUD, machine("web")) == keelmenu.HIDE

    def test_an_empty_flag_is_still_off(self, cloud):
        cloud.write_text("\n")

        assert keelmenu.cloud_available() is False

    def test_shown_once_an_endpoint_is_configured(self, chains, cloud):
        cloud.write_text("https://cloud.keellinux.org\n")

        assert keelmenu.cloud_available() is True
        assert keelmenu.place(CLOUD, machine("web")) == keelmenu.SHOW


class TestOtherScreens:
    def test_a_screen_with_no_rule_is_shown(self, chains):
        assert keelmenu.place(VIEW, machine("core")) == keelmenu.SHOW


class Entry:
    def __init__(self, path):
        self.path = path


class TestArrange:
    def test_a_menu_without_keel_screens_does_not_read_the_machine(self):
        plugins = [Entry("/elsewhere/Lets_Encrypt/get_certificate.py")]

        def never():
            raise AssertionError("the machine was read")

        assert keelmenu.arrange(plugins, never) == (plugins, [])

    def test_keel_web_simple(self, chains, spec, cloud):
        spec("web")
        plugins = [Entry(path) for path in (DATABASE, CLOUD, OVERLAY, VIEW)]

        shown, advanced = keelmenu.arrange(plugins)

        assert [one.path for one in shown] == [VIEW]
        assert [one.path for one in advanced] == [OVERLAY]

    def test_a_mariadb_appliance_in_a_cloud_mode(self, chains, spec, cloud):
        spec("mariadb", "cloud_advanced")
        cloud.write_text("https://cloud.example\n")
        plugins = [Entry(path) for path in (DATABASE, CLOUD, OVERLAY, VIEW)]

        shown, advanced = keelmenu.arrange(plugins)

        assert [one.path for one in shown] == [DATABASE, CLOUD, OVERLAY,
                                               VIEW]
        assert advanced == []


class FakeMenu:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def menu(self, title, text, choices, **kwargs):
        self.calls.append((title, text, choices))
        return self.answer


class TestTheAdvancedMenu:
    ITEMS = [("Overlay network", "WireGuard mesh: this node and peers")]
    PATHS = {"Overlay network": OVERLAY}

    def test_a_choice_opens_its_screen(self):
        console = FakeMenu(("ok", "Overlay network"))

        assert keelmenu.advanced(console, self.ITEMS, self.PATHS,
                                 "/back") == OVERLAY
        (title, text, choices), = console.calls
        assert title == keelmenu.ADVANCED_TAG
        assert choices == self.ITEMS
        assert "simple installation" in text

    def test_back_returns_to_the_menu_it_came_from(self):
        console = FakeMenu(("cancel", ""))

        assert keelmenu.advanced(console, self.ITEMS, self.PATHS,
                                 "/back") == "/back"

    def test_the_entry_itself_says_what_is_behind_it(self):
        tag, text = keelmenu.ADVANCED_ITEM

        assert tag == keelmenu.ADVANCED_TAG
        assert text


class TestWhereTheOverlayScreenIs:
    def test_in_the_instance_menu(self, chains, spec):
        spec("web", "cloud_simple")

        assert keelmenu.overlay_where() == "Overlay network"

    def test_behind_advanced(self, chains, spec):
        spec("web")

        assert keelmenu.overlay_where() == "Advanced > Overlay network"


class TestWithTheRealKeel:
    """keel's own resolution, on manifests shaped like the images'"""

    @pytest.fixture
    def root(self, tmp_path):
        try:
            importlib.import_module("keel.manifest.facts")
        except ImportError:
            pytest.skip("keel is not installed")
        share = tmp_path / "usr" / "share" / "keel"
        (share / "appliances").mkdir(parents=True)
        (share / "overlays").mkdir()

        def write(kind, name, **fields):
            doc = {"manifest_version": 1, "kind": kind, "name": name,
                   "title": name.title(), "summary": f"The {name}"}
            doc.update(fields)
            folder = "appliances" if kind == "appliance" else "overlays"
            (share / folder / f"{name}.yaml").write_text(yaml.safe_dump(doc))

        states = {"simple": "disabled", "cloud_simple": "enabled",
                  "cloud_advanced": "enabled"}
        for name in ("wireguard", "nginx"):
            write("overlay", name)
        write("overlay", "mariadb", provides={"engine": "mariadb"})
        write("appliance", "core", base="none",
              overlays={"wireguard": states})
        write("appliance", "web", base="core", overlays={"nginx": states})
        write("appliance", "db", base="core", overlays={"mariadb": states})
        return str(tmp_path)

    def test_web_has_wireguard_and_no_database(self, root):
        chain = keelmenu.chain_of("web", root)

        assert chain.overlays == frozenset(["wireguard", "nginx"])
        assert chain.engines == frozenset()

    def test_a_database_appliance_provides_mariadb(self, root):
        assert keelmenu.chain_of("db", root).engines == frozenset(
            ["mariadb"])
