"""The Keel mark above the usage screen.

The console is a brand surface: an operator meets a Keel appliance on the
container console or over SSH long before any web page. The mark is
installed by the core overlay as ``/etc/keel/banner.txt`` and
``/etc/keel/banner-small.txt``, the same two files the login banner
(``/etc/update-motd.d/00-keel-banner``) reads, both plain ASCII with no
colour escape so a serial console and a recovery shell render them.

How many rows and columns a mark takes is whatever the installed files
carry: the art is drawn in the overlay and redrawn there, and nothing
here assumes a size. This module measures the file it reads, decides which
of the two marks, if either, goes above the usage text, centres it on the
width the dialog leaves inside its frame and puts it there. It opens no
dialog and formats no address: the usage text is rendered by
``confconsole.render_usage``, is left as it is and is never centred.

The rule the module enforces is the identity's: the mark never costs the
screen a line of what it already says, so it is dropped to the small one,
and then to nothing, rather than pushing the addresses out of the box.
"""

import shutil

MARK = "/etc/keel/banner.txt"
MARK_SMALL = "/etc/keel/banner-small.txt"
MARKS = (MARK, MARK_SMALL)

# Under this the usage screen alone is already tight and the mark is
# dropped: the addresses win.
MIN_ROWS = 24
DEFAULT_COLS = 80

# One blank line between the mark and the first line of the usage text.
SEPARATOR_ROWS = 1

# The dialog frame and its padding, left and right, top and bottom.
FRAME = 4


def terminal_size() -> tuple[int, int]:
    """The terminal as (rows, columns), 24 by 80 when it does not say."""
    size = shutil.get_terminal_size(fallback=(DEFAULT_COLS, MIN_ROWS))
    return size.lines, size.columns


def mark_size(mark: str) -> tuple[int, int]:
    """The rows and columns an ASCII mark occupies, (0, 0) when empty."""
    lines = mark.splitlines()
    return len(lines), max((len(line) for line in lines), default=0)


def inner_width(cols: int) -> int:
    """The columns a terminal of `cols` leaves inside the dialog frame.

    One definition, used by `fits` to decide whether a mark is too wide
    and by the caller to centre it, so the width the mark is measured
    against and the width it is centred on can never disagree.
    """
    return cols - FRAME


def fits(mark: str, rows: int, cols: int, used_rows: int) -> bool:
    """Whether `mark` fits above a box of `used_rows` rows in a terminal
    of `rows` by `cols`, the blank line between them counted. An empty
    file never fits, so a truncated mark costs the screen nothing."""
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
        with open(path) as fob:
            return fob.read()
    except OSError:
        return None


def choose(
    rows: int,
    cols: int,
    used_rows: int,
    paths: tuple[str, ...] = MARKS,
    reader=None,
) -> str | None:
    """The first mark of `paths` that fits, or None.

    `paths` is ordered largest first, so a tall terminal gets the full
    mark, a shorter one the small mark and a terminal under `MIN_ROWS`
    none at all, whatever its width. `reader` defaults to `read`, looked
    up when the call is made and not when this function was defined, so a
    test can replace it on the module.
    """
    if rows < MIN_ROWS:
        return None
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
