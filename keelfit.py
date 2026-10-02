"""The size of a dialog box, so that no text is cut at its edge.

confconsole drew every menu 65 columns wide and 25 rows tall. On an
80x24 console (lxc-console, pct console, Proxmox's noVNC) a description
longer than the box was cut at its right border, mid-word, and the box
was drawn over the backtitle. A menu now takes the width its widest line
needs, up to what the terminal leaves (``keelbanner.available``), and a
box is never taller or wider than that. A description is shortened, with
an ellipsis, only when even the full width is not enough; the Keel
screens' own descriptions are written to fit at 80 columns, and a test
holds them to it.

The constants are dialog 1.3's, measured on trixie: a menu whose widest
tag, two columns and widest item fill W - 6 columns is drawn whole, and
two more keep one column clear on each side; a line of a box's text
takes W - 4.
"""

import keelbanner

TAG_GAP = 2
MENU_CHROME = 8
# the frame and one column of margin each side of a box's text
TEXT_CHROME = 4
# the rows of a message box that are not its text (keelbanner measured)
BOX_CHROME = keelbanner.BOX_CHROME
# a short message keeps a box its buttons sit well in
MIN_TEXT_WIDTH = 40
ELLIPSIS = "..."


def room() -> tuple[int, int]:
    """The rows and columns a box may take on this terminal"""
    return keelbanner.available(*keelbanner.terminal_size())


def box(height: int, width: int, space: tuple[int, int]) -> tuple[int, int]:
    """`height` by `width`, cut to the `space` the terminal leaves"""
    rows, cols = space
    return min(height, rows), min(width, cols)


def text_width(space: tuple[int, int]) -> int:
    """The columns a line of text has inside the widest box"""
    return space[1] - TEXT_CHROME


def text_box(text: str, space: tuple[int, int]) -> tuple[int, int]:
    """A message box for `text`: as wide as its longest line, as tall as
    its rows once wrapped, at most the `space` the terminal leaves (a
    longer text scrolls inside it). dialog's own autosize drew over the
    backtitle on 24 rows and wrapped well short of the terminal's width.
    """
    rows, cols = space
    longest = max(len(line) for line in text.split("\n"))
    width = min(cols, max(MIN_TEXT_WIDTH, longest + TEXT_CHROME))
    needed = keelbanner.text_rows(text, width - TEXT_CHROME) + BOX_CHROME
    return min(rows, needed), width


def _widths(choices: list[tuple[str, str]]) -> tuple[int, int]:
    tag = max((len(one) for one, _ in choices), default=0)
    item = max((len(one) for _, one in choices), default=0)
    return tag, item


def menu_width(choices: list[tuple[str, str]], width: int,
               cols: int, text: str = "") -> int:
    """At least `width`, as wide as the widest choice and the longest
    line of `text` (a public key wraps badly), at most `cols`"""
    needed = width
    if choices:
        tag, item = _widths(choices)
        needed = max(needed, tag + TAG_GAP + item + MENU_CHROME)
    line = max((len(one) for one in text.splitlines()), default=0)
    if line:
        needed = max(needed, line + TEXT_CHROME)
    return min(cols, needed)


def clip(text: str, room: int) -> str:
    """`text` in `room` columns, its end an ellipsis when it was cut"""
    if len(text) <= room:
        return text
    if room <= len(ELLIPSIS):
        return text[:max(room, 0)]
    return text[:room - len(ELLIPSIS)] + ELLIPSIS


def fit_choices(choices: list[tuple[str, str]],
                width: int) -> list[tuple[str, str]]:
    """The items shortened to a box `width` wide; the tags as they are,
    since dialog answers with the tag"""
    tag, _ = _widths(choices)
    space = width - MENU_CHROME - TAG_GAP - tag
    return [(one, clip(item, space)) for one, item in choices]
