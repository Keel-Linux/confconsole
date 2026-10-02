"""What confconsole shows the operator names Keel Linux, not TurnKey.

The backtitle at the top of every screen, the appliance name the menus
are titled with, and the text of the screens a Keel appliance ships are
checked for TurnKey's name and addresses. What stays, and why, is
ALLOWED: the names of commands a screen runs or tells the operator to
run, kept so that existing installs and documentation keep working.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Every Python file whose strings reach a screen.
SHOWN = [
    "confconsole.py",
    "plugins.d/Mail_Relaying/mail_relay.py",
    "plugins.d/Lets_Encrypt/get_certificate.py",
    "plugins.d/Lets_Encrypt/dns_01.py",
    "plugins.d/System_Settings/Secupdates_adv_conf.py",
    "plugins.d/System_Settings/Security_Update.py",
]
# Command names, not branding: the lexicon wrapper confconsole installs
# and the security update command inithooks installs.
ALLOWED = ["turnkey-lexicon", "turnkey-install-security-updates"]


def strings(path: str) -> list[str]:
    """Every string literal of the Python file at PATH but its docstrings
    and the names it imports"""
    tree = ast.parse((ROOT / path).read_text())
    skipped = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False) is not None:
                skipped.add(id(node.body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
    ]


def names_turnkey(text: str) -> bool:
    for allowed in ALLOWED:
        text = text.replace(allowed, "")
    return "turnkey" in text.lower() or "tklbam" in text.lower()


class FakePluginManager:
    def updateGlobals(self, values):
        self.globals = values


@pytest.fixture
def console_title(confconsole, monkeypatch):
    """The backtitle and appname a TurnkeyConsole is created with."""
    seen = {}

    class FakeConsole:
        def __init__(self, title, width, height):
            seen["title"] = title

    monkeypatch.setattr(confconsole, "Console", FakeConsole)
    monkeypatch.setattr(confconsole.netinfo, "get_hostname", lambda: "web")
    monkeypatch.setattr(confconsole, "APPNAME_PATH", "/nonexistent/appname")
    tc = confconsole.TurnkeyConsole(FakePluginManager(), object())
    return seen["title"], tc.appname


def test_backtitle_names_keel_linux(console_title):
    title, _ = console_title
    assert title == "Keel Linux Configuration Console"


def test_appname_without_etc_appname_names_keel_linux(console_title):
    _, appname = console_title
    assert appname == "Keel Linux WEB"


def test_first_boot_screens_carry_the_inithooks_backtitle():
    # The role and Keel Cloud screens run between the inithooks dialogs,
    # whose backtitle is "Keel Linux - First boot configuration"
    # (Keel-Linux/inithooks libinithooks/dialog_wrapper.py); the same words
    # keep the top line still as the operator moves from one to the next.
    import keelfirstboot

    assert keelfirstboot.BACKTITLE == "Keel Linux - First boot configuration"


def test_etc_appname_still_wins(confconsole, monkeypatch, tmp_path):
    path = tmp_path / "appname"
    path.write_text("My Site\n")
    monkeypatch.setattr(confconsole, "Console", lambda *args: None)
    monkeypatch.setattr(confconsole, "APPNAME_PATH", str(path))
    tc = confconsole.TurnkeyConsole(FakePluginManager(), object())
    assert tc.appname == "My Site"


@pytest.mark.parametrize("path", SHOWN)
def test_no_screen_text_names_turnkey(path):
    shown = [text for text in strings(path) if names_turnkey(text)]
    assert shown == []
