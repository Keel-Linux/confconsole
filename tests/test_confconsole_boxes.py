"""confconsole's boxes fit the terminal, and a menu is as wide as its text.

The maintainer's screenshots of Keel Web on an 80x24 Proxmox console
showed menu descriptions cut at the box's right border and boxes drawn
over the backtitle: every box was 65 by 25 whatever the terminal. The
Console now asks keelfit for the room the terminal leaves.
"""

import pytest

import keelbanner
import keelfit


class Recorder:
    """Stands for pythondialog's Dialog: records what each box was given"""

    OK = "ok"

    def __init__(self):
        self.calls = []

    def _record(self, name, text, *args, **kwargs):
        self.calls.append((name, text, args, kwargs))
        return ("ok", "x") if name in ("menu", "inputbox", "form") else "ok"

    def menu(self, text, *args, **kwargs):
        return self._record("menu", text, *args, **kwargs)

    def msgbox(self, text, *args, **kwargs):
        return self._record("msgbox", text, *args, **kwargs)

    def inputbox(self, text, *args, **kwargs):
        return self._record("inputbox", text, *args, **kwargs)

    def form(self, text, *args, **kwargs):
        return self._record("form", text, *args, **kwargs)


@pytest.fixture
def console(confconsole, monkeypatch):
    def _make(rows=24, cols=80):
        monkeypatch.setattr(keelbanner, "terminal_size", lambda: (rows, cols))
        made = confconsole.Console("Keel Linux")
        made.console = Recorder()
        return made

    return _make


LONG = [
    ("Networking", "Configure appliance networking"),
    ("Instance", "Instance spec: view, apply, drift, export, database mode,"
     " overlay network, Keel Cloud"),
]


class TestMenu:
    def test_a_short_menu_keeps_the_usual_width(self, console):
        made = console()

        made.menu("Title", "text", [("Quit", "Quit the console")])

        (_, _, args, kwargs), = made.console.calls
        assert args == (20, 65)
        assert kwargs["choices"] == [("Quit", "Quit the console")]

    def test_a_long_description_widens_the_box_to_the_terminal(
        self, console
    ):
        made = console(30, 120)

        made.menu("Title", "text", LONG)

        (_, _, (height, width), kwargs), = made.console.calls
        assert height == 25
        assert width == len("Networking") + 2 + len(LONG[1][1]) + 8
        assert kwargs["choices"] == LONG

    def test_at_80_columns_a_description_too_long_ends_in_an_ellipsis(
        self, console
    ):
        made = console()

        made.menu("Title", "text", LONG)

        (_, _, (_, width), kwargs), = made.console.calls
        assert width == 76
        (_, short), (_, cut) = kwargs["choices"]
        assert short == LONG[0][1]
        assert cut.endswith("...")
        assert len("Networking") + 2 + len(cut) + 8 == 76

    def test_a_long_line_of_text_widens_the_box(self, console):
        made = console()

        made.menu("Title", "key: " + "k" * 60, [("Quit", "Quit")])

        (_, _, (_, width), _), = made.console.calls
        assert width == 65 + 4

    def test_the_menu_height_and_default_item_still_reach_dialog(
        self, console
    ):
        made = console()

        made.menu("Title", "text", LONG, default_item="Instance")

        (_, _, _, kwargs), = made.console.calls
        assert kwargs["menu_height"] == 3
        assert kwargs["default_item"] == "Instance"


class TestOtherBoxes:
    def test_a_message_never_taller_than_the_terminal_leaves(self, console):
        made = console()

        made.msgbox("Title", "text")

        (_, _, args, _), = made.console.calls
        assert args == (20, 65)

    def test_a_message_given_its_size_keeps_it(self, console):
        # the usage screen sizes its own box from the room
        made = console()

        made.msgbox("Title", "text", height=22, width=70)

        (_, _, args, _), = made.console.calls
        assert args == (22, 70)

    def test_an_autosized_message_is_sized_to_its_text_and_the_room(
        self, console
    ):
        made = console()

        made.msgbox("Title", "x" * 100 + "\nshort", autosize=True)

        (_, _, args, _), = made.console.calls
        assert args == (2 + 1 + 1 + 5, 76)

    def test_an_autosized_question_is_sized_the_same_way(self, console):
        made = console()
        made.console.yesno = lambda text, *args, **kwargs: (
            made.console._record("yesno", text, *args, **kwargs))

        made.yesno("Apply it?", autosize=True)

        (_, _, args, _), = made.console.calls
        assert args[1] == keelfit.MIN_TEXT_WIDTH

    def test_an_input_box_fits(self, console):
        made = console(20, 60)

        made.inputbox("Title", "text")

        (_, _, args, _), = made.console.calls
        assert args == (16, 56)

    def test_a_form_fits(self, console):
        made = console(20, 60)

        made.form("Title", "text", [])

        (_, _, _, kwargs), = made.console.calls
        assert (kwargs["height"], kwargs["width"]) == (16, 56)
