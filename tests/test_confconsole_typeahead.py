"""A box of confconsole never takes a key typed before it was drawn.

The Mode screen of keel-init on a cloud advanced replica chose Simple by
itself: an Enter typed while WordPress installed waited in the terminal,
and the menu took it as soon as it was drawn (BR2, 2026-11-07). An
operator who presses Enter while a long step runs gets the same. Each box
now drops what was typed before it, and reads only the keys typed while
it is on the screen.
"""

import termios

from test_confconsole_boxes import Recorder, console  # noqa: F401


class Flushes:
    def __init__(self):
        self.calls = []

    def __call__(self, fd, queue):
        self.calls.append((fd, queue))


def test_a_menu_drops_the_keys_typed_before_it(console, monkeypatch):  # noqa: F811
    made = console()
    flushed = Flushes()
    order = []
    monkeypatch.setattr(termios, "tcflush", lambda fd, q: (flushed(fd, q), order.append("flush")))
    monkeypatch.setattr("os.isatty", lambda fd: True)
    menu = made.console.menu
    made.console.menu = lambda *a, **k: (order.append("menu"), menu(*a, **k))[1]
    made.menu("Installation mode", "How", [("Simple", "one node"), ("Cloud simple", "two")])
    assert flushed.calls == [(0, termios.TCIFLUSH)]
    assert order == ["flush", "menu"]


def test_every_box_drops_them(console, monkeypatch):  # noqa: F811
    made = console()
    flushed = Flushes()
    monkeypatch.setattr(termios, "tcflush", flushed)
    monkeypatch.setattr("os.isatty", lambda fd: True)
    made.msgbox("Title", "text")
    made.inputbox("Title", "text")
    assert len(flushed.calls) == 2


def test_no_terminal_no_flush(console, monkeypatch):  # noqa: F811
    made = console()
    flushed = Flushes()
    monkeypatch.setattr(termios, "tcflush", flushed)
    monkeypatch.setattr("os.isatty", lambda fd: False)
    made.msgbox("Title", "text")
    assert flushed.calls == []


def test_a_terminal_that_refuses_the_flush_still_shows_the_box(console, monkeypatch):  # noqa: F811
    made = console()

    def refuse(fd, queue):
        raise termios.error(25, "Inappropriate ioctl for device")

    monkeypatch.setattr(termios, "tcflush", refuse)
    monkeypatch.setattr("os.isatty", lambda fd: True)
    assert made.msgbox("Title", "text") == "ok"
