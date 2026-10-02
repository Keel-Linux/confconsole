"""The Keel mark above the usage screen.

The console is a brand surface: an operator meets a Keel appliance on the
container console or over SSH long before any web page. The mark is the
maintainer's console art, installed by the core overlay in ``/etc/keel``,
the same files the login banner (``/etc/update-motd.d/00-keel-banner``)
reads: a wide mark with the KEEL LINUX lettering, the tagline and
KEELLINUX.ORG, a full mark and a small one. The wide mark is drawn in
UTF-8 block and shade characters only; the full and the small mark come
in UTF-8 and in plain ASCII. None of them carries a colour escape.

How many rows and columns a mark takes is whatever the installed files
carry: the art is drawn in the overlay and redrawn there, and nothing
here assumes a size. This module measures the file it reads, decides
which tier, if any, goes above the usage text, in the order wide, full,
small, none, from the room the dialog has on the screen, and centres it
on the width of the box. It opens no dialog and formats no address: the
usage text is rendered by ``confconsole.render_usage``, is left as it is
and is never centred.

The rule the module enforces is the identity's: the mark never costs the
screen a line of what it already says, so a smaller tier is taken, and
then none, rather than pushing the addresses out of the box.
"""

import os
import shutil
import textwrap
from collections.abc import Mapping

MARK_WIDE = "/etc/keel/banner-wide.txt"
MARK_UTF8 = "/etc/keel/banner-utf8.txt"
MARK_SMALL_UTF8 = "/etc/keel/banner-small-utf8.txt"
MARK = "/etc/keel/banner.txt"
MARK_SMALL = "/etc/keel/banner-small.txt"

# The two ladders, largest first. There is no ASCII wide mark.
MARKS_UTF8 = (MARK_WIDE, MARK_UTF8, MARK_SMALL_UTF8)
MARKS_ASCII = (MARK, MARK_SMALL)

MIN_ROWS = 24
DEFAULT_COLS = 80

# One blank line between the mark and the first line of the usage text.
SEPARATOR_ROWS = 1

# The dialog frame and its padding, left and right.
FRAME = 4

# The rows of a message box that are not text: the top border, the blank
# row Console._wrapper puts above every text, the rule above the button,
# the button and the bottom border.
BOX_CHROME = 5

# What the screen keeps from the box. dialog centres a box on the whole
# screen, so the backtitle and the rule under it, two rows at the top,
# cost two rows at the bottom too, and the shadow, two columns on the
# right, costs two on the left. Measured with dialog 1.3 on trixie: on
# 24 rows a box of 20 is the tallest drawn clear of the backtitle.
SCREEN_ROWS = 4
SCREEN_COLS = 4


def terminal_size() -> tuple[int, int]:
    """The terminal as (rows, columns), 24 by 80 when it does not say."""
    size = shutil.get_terminal_size(fallback=(DEFAULT_COLS, MIN_ROWS))
    return size.lines, size.columns


def available(rows: int, cols: int) -> tuple[int, int]:
    """The rows and columns a dialog box may take on a terminal of
    `rows` by `cols`, the backtitle and the shadow kept clear."""
    return max(0, rows - SCREEN_ROWS), max(0, cols - SCREEN_COLS)


def is_utf8(environ: Mapping[str, str]) -> bool:
    """Whether the locale of `environ` is UTF-8: LC_ALL, then LC_CTYPE,
    then LANG, the first set and not empty, as the C library reads them.

    This is the environment the dialog child inherits. Python run in the
    C locale with LANG=C coerces LC_CTYPE to C.UTF-8 (PEP 538), and dialog
    then does draw UTF-8, so the UTF-8 marks are right there too; LC_ALL=C
    turns the coercion off and gets the ASCII ones.
    """
    for name in ("LC_ALL", "LC_CTYPE", "LANG"):
        value = environ.get(name, "")
        if value:
            codeset = value.partition(".")[2].partition("@")[0].lower()
            return codeset in ("utf-8", "utf8")
    return False


def marks(environ: Mapping[str, str]) -> tuple[str, ...]:
    """The ladder for the locale of `environ`, largest first."""
    return MARKS_UTF8 if is_utf8(environ) else MARKS_ASCII


def mark_size(mark: str) -> tuple[int, int]:
    """The rows and columns a mark occupies, (0, 0) when empty. Every
    character of the art, a block or a shade as much as a "#", is one
    column wide."""
    lines = mark.splitlines()
    return len(lines), max((len(line) for line in lines), default=0)


def inner_width(cols: int) -> int:
    """The columns a box `cols` wide leaves inside its frame.

    One definition, used by `fits` to decide whether a mark is too wide
    and by the caller to centre it, so the width the mark is measured
    against and the width it is centred on can never disagree.
    """
    return cols - FRAME


def text_rows(text: str, width: int) -> int:
    """The rows `text` takes inside a box whose inside is `width` wide:
    dialog wraps a longer line at a space, and breaks a word longer than
    the whole width."""
    rows = 0
    for line in text.split("\n"):
        rows += max(1, len(textwrap.wrap(line, width)))
    return rows


def box_width(mark: str, width: int, room: int) -> int:
    """The width of a box of `width` columns once it holds `mark`: wide
    enough for the mark inside its frame, never wider than `room`."""
    return min(room, max(width, mark_size(mark)[1] + FRAME))


def fits(mark: str, rows: int, cols: int, used_rows: int) -> bool:
    """Whether `mark` fits above a box of `used_rows` rows in a room of
    `rows` by `cols` (`available`), the blank line between them counted.
    The box may widen to the room, so the mark needs only its own
    columns and the frame. An empty file never fits, so a truncated mark
    costs the screen nothing."""
    mark_rows, mark_cols = mark_size(mark)
    if mark_rows == 0:
        return False
    if mark_cols > inner_width(cols):
        return False
    return mark_rows + SEPARATOR_ROWS + used_rows <= rows


def read(path: str) -> str | None:
    """The mark at `path`, or None when it cannot be read. A missing file
    is not an error: the appliance was built before the overlay carried
    the mark, or an operator removed it."""
    try:
        with open(path, encoding="utf-8") as fob:
            return fob.read()
    except (OSError, UnicodeDecodeError):
        return None


def choose(
    rows: int,
    cols: int,
    used_rows: int,
    paths: tuple[str, ...] | None = None,
    reader=None,
) -> str | None:
    """The first mark of `paths` that fits a room of `rows` by `cols`
    above a box of `used_rows` rows, or None.

    `rows` and `cols` are the room the dialog has (`available`), not the
    terminal. `paths` is ordered largest first and defaults to the ladder
    of the locale (`marks`), so the widest terminal gets the wide mark, a
    narrower or shorter one the full mark, then the small mark, and a
    terminal with room for none of them none at all. `reader` defaults to
    `read`, looked up when the call is made and not when this function
    was defined, so a test can replace it on the module.
    """
    if paths is None:
        paths = marks(os.environ)
    if reader is None:
        reader = read
    for path in paths:
        mark = reader(path)
        if mark is None:
            continue
        if fits(mark, rows, cols, used_rows):
            return mark
    return None


def center(mark: str, width: int) -> str:
    """`mark` shifted right so the block sits centred in `width` columns.

    The block is centred, not each line: one indent, the same for every
    line, because padding the lines one by one would destroy the mark's
    internal alignment. The indent is measured from the widest line of
    whatever art was installed, so a mark as wide as `width`, or wider,
    is shifted by nothing and is never truncated. No line of the block
    carries trailing whitespace, and a blank line in the mark stays blank
    rather than becoming a line of spaces.
    """
    indent = " " * max(0, (width - mark_size(mark)[1]) // 2)
    lines = []
    for row in mark.split("\n"):
        line = row.rstrip()
        lines.append(indent + line if line else "")
    return "\n".join(lines)


def above(text: str, mark: str) -> str:
    """`mark`, one blank line, then `text`."""
    return mark.rstrip("\n") + "\n" * (SEPARATOR_ROWS + 1) + text


def added_rows(mark: str) -> int:
    """How much taller the box has to be to hold `mark` above its text."""
    return mark_size(mark)[0] + SEPARATOR_ROWS
