"""Shared fixtures for the confconsole tests.

confconsole is installed flat under /usr/lib/confconsole, so the modules
are imported from the repository root. `netinfo` comes from the Debian
package turnkey-netinfo, which is not on PyPI; when it is not importable a
stub module with the same two names is registered so the parsers can be
tested on any host. Nothing here touches the live system.
"""

import importlib
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STUB_HOSTNAME = "core"


class FakeInterfaceInfo:
    """Stand-in for netinfo.InterfaceInfo, controlled by the tests."""

    address = None
    netmask = None
    gateway = None

    def __init__(self, ifname):
        self.ifname = ifname

    def get_gateway(self, error=False):
        return self.gateway


def _install_netinfo_stub():
    try:
        importlib.import_module("netinfo")
    except ModuleNotFoundError:
        stub = types.ModuleType("netinfo")
        stub.InterfaceInfo = FakeInterfaceInfo
        stub.get_hostname = lambda: STUB_HOSTNAME
        sys.modules["netinfo"] = stub


def _install_dialog_stubs():
    """Register stand-ins for the two modules confconsole.py imports that
    are not on PyPI as such (pythondialog needs the dialog binary, systemd
    needs libsystemd). The dialog tests never open a dialog: the test
    replaces TurnkeyConsole.console with a scripted fake."""
    try:
        importlib.import_module("dialog")
    except ModuleNotFoundError:
        stub = types.ModuleType("dialog")

        class DialogError(Exception):
            pass

        class Dialog:
            OK = "ok"

            def __init__(self, *args, **kwargs):
                pass

            def add_persistent_args(self, args):
                pass

        stub.DialogError = DialogError
        stub.Dialog = Dialog
        sys.modules["dialog"] = stub
    try:
        importlib.import_module("systemd.journal")
    except ModuleNotFoundError:
        import logging

        package = types.ModuleType("systemd")
        journal = types.ModuleType("systemd.journal")

        class JournalHandler(logging.NullHandler):
            def __init__(self, *args, **kwargs):
                super().__init__()

        journal.JournalHandler = JournalHandler
        package.journal = journal
        sys.modules["systemd"] = package
        sys.modules["systemd.journal"] = journal


def _install_requests_stub():
    """The Let's Encrypt screen imports requests (python3-requests) to
    read the terms of service; the tests replace its `get`, so a host
    without the package gets a module with that one name, which refuses
    to be called for real."""
    try:
        importlib.import_module("requests")
    except ModuleNotFoundError:
        stub = types.ModuleType("requests")

        def get(url, **kwargs):
            raise AssertionError(f"requests.get({url!r}) must be replaced")

        stub.get = get
        sys.modules["requests"] = stub


_install_netinfo_stub()
_install_dialog_stubs()
_install_requests_stub()


@pytest.fixture
def ifutil():
    import ifutil as module

    return module


@pytest.fixture
def confconsole():
    import confconsole as module

    return module


@pytest.fixture
def hostname(ifutil, monkeypatch):
    """Pin the hostname the parsers insert, independent of the host."""
    monkeypatch.setattr(ifutil, "get_hostname", lambda: STUB_HOSTNAME)
    return STUB_HOSTNAME


@pytest.fixture
def interfaces_file(tmp_path):
    """Write a scratch /etc/network/interfaces and return its path."""

    def _write(text):
        path = tmp_path / "interfaces"
        path.write_text(text)
        return str(path)

    return _write


UNCONFIGURED = """# UNCONFIGURED INTERFACES
# remove the above line if you edit this file

auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
    hostname core

iface eth0 inet6 dhcp
    hostname core
"""

STATIC_V4 = """# UNCONFIGURED INTERFACES

auto eth0
iface eth0 inet static
    address 192.0.2.10
    netmask 255.255.255.0
    gateway 192.0.2.1
    dns-nameservers 2001:db8::53 192.0.2.53
    hostname core
    post-up /usr/local/bin/announce

iface eth0 inet6 static
    address 2001:db8:1::10
    netmask 64
    gateway 2001:db8:1::1
"""

MANUAL_HEADERLESS = """auto eth0
iface eth0 inet manual
"""

INET6_ONLY = """# UNCONFIGURED INTERFACES

auto eth0
iface eth0 inet6 static
    address 2001:db8:1::10
    netmask 64
    gateway 2001:db8:1::1
    dns-nameservers 2001:db8::53
"""


class FakeConsole:
    """Answers form/yesno/inputbox/msgbox from scripted queues, records
    calls."""

    OK = "ok"

    def __init__(self, forms=(), yesno=(), inputs=(), passwords=(),
                 menus=()):
        self.forms = list(forms)
        self.yesnos = list(yesno)
        self.inputs = list(inputs)
        self.passwords = list(passwords)
        self.menus = list(menus)
        self.calls = []
        self.msgbox_kwargs = {}

    @property
    def console(self):
        # Console.console is the pythondialog Dialog; the fake stands in
        # for both, so a textbox reached through it is recorded here.
        return self

    def textbox(self, path, height, width, **kwargs):
        import os
        import stat

        mode = stat.S_IMODE(os.stat(path).st_mode)
        with open(path) as fob:
            self.calls.append(
                ("textbox", kwargs.get("title"), fob.read(), path, mode)
            )
        return self.OK

    def _wrapper(self, dialog, text, *args, **kwargs):
        # Only the password box is reached through the wrapper by the
        # code under test; anything else is a test that went wrong.
        assert dialog == "passwordbox", dialog
        self.calls.append(("passwordbox", kwargs.get("title"), text, kwargs))
        return self.passwords.pop(0)

    def inputbox(self, title, text, init="", **kwargs):
        self.calls.append(("inputbox", title, text, init))
        return self.inputs.pop(0)

    def form(self, title, text, fields, **kwargs):
        self.calls.append(("form", text, fields, kwargs))
        return self.forms.pop(0)

    def yesno(self, text, autosize=False):
        self.calls.append(("yesno", text))
        return self.yesnos.pop(0)

    def msgbox(self, title, text, **kwargs):
        self.calls.append(("msgbox", title, text))
        self.msgbox_kwargs = kwargs
        return self.OK

    def infobox(self, text):
        self.calls.append(("infobox", text))
        return self.OK

    def menu(self, title, text, choices, **kwargs):
        """Answers from `menus` when a test scripts them; opening a menu
        nobody scripted is a failure, as it always was"""
        if not self.menus:
            raise AssertionError("menu must not be opened by these tests")
        self.calls.append(("menu", title, text, choices))
        self.menu_kwargs = kwargs
        return self.menus.pop(0)


@pytest.fixture
def tc(confconsole):
    """A TurnkeyConsole bound to eth0 with a fake console, no __init__."""

    def _make(forms=(), yesno=()):
        console = object.__new__(confconsole.TurnkeyConsole)
        console.console = FakeConsole(forms, yesno)
        console.ifname = "eth0"
        return console

    return _make


@pytest.fixture
def net_stubs(confconsole, monkeypatch):
    """Stub the ifutil readers the menus use; return a dict to steer them.

    `real_get_ipv6conf` keeps the unstubbed function for a test that wants
    the real preference order with `ip` output replaced instead."""
    state = {
        "ifnames": ["eth0"],
        "ipconf": (None, None, None, []),
        "ipv6conf": (None, None),
        "methods": {"inet": None, "inet6": None},
        "default_nic": "eth0",
        "real_get_ipv6conf": confconsole.ifutil.get_ipv6conf,
    }
    monkeypatch.setattr(
        confconsole.TurnkeyConsole,
        "_get_filtered_ifnames",
        classmethod(lambda cls: list(state["ifnames"])),
    )
    monkeypatch.setattr(
        confconsole.TurnkeyConsole,
        "_get_default_nic",
        classmethod(lambda cls: state["default_nic"]),
    )
    monkeypatch.setattr(
        confconsole.ifutil,
        "get_ipconf",
        lambda ifname, error=False: state["ipconf"],
    )
    monkeypatch.setattr(
        confconsole.ifutil, "get_ipv6conf", lambda ifname: state["ipv6conf"]
    )
    monkeypatch.setattr(
        confconsole.ifutil,
        "get_ifmethod",
        lambda ifname, inet_family="inet": state["methods"][inet_family],
    )
    return state


# --- the database mode screens (test_database_mode, test_database_handout)

MODE_DIR = ROOT / "plugins.d" / "Instance" / "Database_mode"
# What a MariaDB appliance boots with once inspect has described it: the
# engine is known, so a screen never has to ask the machine what it runs.
BASE = {
    "version": 1,
    "instance": {"hostname": "mariadb"},
    "database": {"server": {"engine": "mariadb", "role": "standalone"}},
}


def make_result(argv, code=0, stdout="", stderr=""):
    import keelcli

    return keelcli.Result(("keel", *argv), code, stdout, stderr)


@pytest.fixture
def keel(monkeypatch):
    """Replace keelcli.call; `calls` records argv, `answers` steers it."""
    import keelcli

    state = {"calls": [], "answers": [], "default": (0, "", "")}

    def fake_call(argv):
        state["calls"].append(list(argv))
        if state["answers"]:
            outcome = state["answers"].pop(0)
        else:
            outcome = state["default"]
        if isinstance(outcome, Exception):
            raise outcome
        return make_result(argv, *outcome)

    monkeypatch.setattr(keelcli, "call", fake_call)
    return state


@pytest.fixture
def spec(tmp_path, monkeypatch):
    """A description on disk that KEEL_SPEC points at."""
    import yaml

    path = tmp_path / "instance.yaml"
    path.write_text(yaml.safe_dump(BASE))
    monkeypatch.setenv("KEEL_SPEC", str(path))
    return path


@pytest.fixture
def screen(monkeypatch):
    """Load one mode screen with a fake console, the way confconsole does"""
    import plugin

    monkeypatch.delenv("KEEL_SPEC", raising=False)

    def _load(relative, **console_kwargs):
        loaded = plugin.Plugin(str(MODE_DIR / relative))
        console = FakeConsole(**console_kwargs)
        loaded.updateGlobals({"console": console})
        return loaded, console

    return _load


# --- the manifest of the machine (test_keelmenu, test_instance_menu)

CORE = ["installer", "wireguard", "etcd", "crowdsec"]
WEB = CORE + ["nginx", "coraza", "anubis"]


def overlay(name, engine=None):
    manifest = {"name": name}
    if engine:
        manifest["provides"] = {"engine": engine}
    return types.SimpleNamespace(name=name, manifest=manifest)


def resolved(overlays, services=None):
    application = None
    if services is not None:
        application = types.SimpleNamespace(item={"services": services})
    return types.SimpleNamespace(overlays=tuple(overlays),
                                 application=application)


@pytest.fixture
def chains(monkeypatch):
    """keel.manifest.facts.gather over the chains a test puts here"""
    table = {}
    asked = []

    def gather(root, name):
        asked.append((root, name))
        found = table.get(name)
        if isinstance(found, Exception):
            raise found
        return types.SimpleNamespace(resolved=found)

    package = types.ModuleType("keel")
    manifest = types.ModuleType("keel.manifest")
    facts = types.ModuleType("keel.manifest.facts")
    facts.gather = gather
    package.manifest = manifest
    manifest.facts = facts
    monkeypatch.setitem(sys.modules, "keel", package)
    monkeypatch.setitem(sys.modules, "keel.manifest", manifest)
    monkeypatch.setitem(sys.modules, "keel.manifest.facts", facts)
    table["core"] = resolved(overlay(name) for name in CORE)
    table["web"] = resolved(overlay(name) for name in WEB)
    table["mariadb"] = resolved(
        [overlay(name) for name in CORE] + [overlay("mariadb", "mariadb")])
    table["wordpress"] = resolved(
        [overlay(name) for name in WEB] + [overlay("mariadb", "mariadb")],
        services={"db": {"engine": "mariadb"}})
    table["asked"] = asked
    return table


@pytest.fixture
def cloud(tmp_path_factory, monkeypatch):
    """The Keel Cloud flag, off until a test writes it"""
    import keelmenu

    # outside tmp_path, where the spec is: tests list that directory
    flag = tmp_path_factory.mktemp("keel-cloud") / "cloud-endpoint"
    monkeypatch.setattr(keelmenu, "CLOUD_ENDPOINT", str(flag))
    # the tests write it as themselves; on a machine root must own it
    monkeypatch.setattr(keelmenu, "CLOUD_OWNER", os.getuid())
    # and writable by its owner alone, whatever the umask of the run
    before = os.umask(0o022)
    yield flag
    os.umask(before)
