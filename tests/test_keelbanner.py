"""The Keel mark above the usage screen.

`keelbanner` is pure but for `read` and `terminal_size`: a mark string and
a terminal size in, a decision out. The marks here are synthetic test
data of an arbitrary size, not a copy of the art the core overlay
installs: what the module must do is measure the file it reads, so a test
that knew the shipped art would go stale the day the art is redrawn.
Every expectation below is derived from the size these fixtures measure.
The files are written to a scratch directory, so no test depends on the
host carrying `/etc/keel/banner.txt`.
"""

import os

import pytest

# Synthetic marks, ragged on purpose so the widest line is not the width
# of every line. The full one is taller and wider than the small one,
# which is all the fallback ladder needs.
MARK = """\
+-----------------+
| FIXTURE MARK,   |
| NOT THE ART     |
|   ###   ###   |
|    #########    |
|      #####      |
+-----------------+
"""

MARK_SMALL = """\
+-------+
| SMALL |
+-------+
"""

USAGE_ROWS = 25


def measure(mark: str) -> tuple[int, int]:
    """The rows and the widest line of a fixture, so a test expectation
    is derived from the art the fixture carries and never from a size the
    module is assumed to know."""
    lines = mark.splitlines()
    return len(lines), max(len(line) for line in lines)


MARK_ROWS, MARK_COLS = measure(MARK)
SMALL_ROWS, SMALL_COLS = measure(MARK_SMALL)


@pytest.fixture
def keelbanner():
    import keelbanner as module

    return module


@pytest.fixture
def marks(tmp_path):
    """The two mark files on disk, largest first."""
    full = tmp_path / "banner.txt"
    small = tmp_path / "banner-small.txt"
    full.write_text(MARK)
    small.write_text(MARK_SMALL)
    return (str(full), str(small))


def reader_of(**marks):
    """A stand-in for keelbanner.read over a dict of path to text."""
    return lambda path: marks.get(path)


def rows_for(mark_rows: int, keelbanner) -> int:
    """The shortest terminal a mark of `mark_rows` rows fits above the
    usage box in, the blank line between them counted."""
    return mark_rows + keelbanner.SEPARATOR_ROWS + USAGE_ROWS


def margins(block: str, width: int) -> tuple[int, int]:
    """The blank columns on each side of `block` inside `width`.

    Both are read off the block itself rather than recomputed from the
    mark it came from, so a test that uses this proves where the block
    landed instead of agreeing with whatever the indent happened to be.
    """
    drawn = [line for line in block.split("\n") if line.strip()]
    left = min(len(line) - len(line.lstrip(" ")) for line in drawn)
    return left, width - max(len(line) for line in drawn)


def drawn_mark(rows: int, cols: int) -> str:
    """A mark of exactly `rows` by `cols`, ragged so its widest line is
    the last one. A test may ask for any size with this, including one
    no art has ever had and none is planned to have."""
    return "\n".join(["#"] * (rows - 1) + ["#" * cols]) + "\n"


class TestTerminalSize:
    def test_reads_the_size_the_terminal_reports(
        self, keelbanner, monkeypatch
    ):
        # Arrange
        monkeypatch.setenv("COLUMNS", "132")
        monkeypatch.setenv("LINES", "50")

        # Act
        rows, cols = keelbanner.terminal_size()

        # Assert
        assert (rows, cols) == (50, 132)

    def test_falls_back_to_24_by_80_when_the_terminal_does_not_say(
        self, keelbanner, monkeypatch
    ):
        # Arrange
        monkeypatch.delenv("COLUMNS", raising=False)
        monkeypatch.delenv("LINES", raising=False)
        monkeypatch.setattr(
            keelbanner.shutil,
            "get_terminal_size",
            lambda fallback: os.terminal_size(fallback),
        )

        # Act
        rows, cols = keelbanner.terminal_size()

        # Assert
        assert (rows, cols) == (24, 80)


class TestMarkSize:
    """The size is whatever the string carries: the module measures it and
    never knows how big the installed art is."""

    def test_reports_the_rows_and_the_width_of_a_block(self, keelbanner):
        assert keelbanner.mark_size("###\n###\n") == (2, 3)

    def test_a_ragged_block_is_as_wide_as_its_widest_line(self, keelbanner):
        assert keelbanner.mark_size("#\n####\n##\n") == (3, 4)

    def test_a_block_of_one_line_is_one_row(self, keelbanner):
        assert keelbanner.mark_size("#####") == (1, 5)

    def test_a_blank_line_inside_a_block_counts_as_a_row(self, keelbanner):
        assert keelbanner.mark_size("##\n\n###\n") == (3, 3)

    def test_an_empty_mark_has_no_size(self, keelbanner):
        assert keelbanner.mark_size("") == (0, 0)

    def test_it_reports_whatever_the_installed_file_carries(self, keelbanner):
        assert keelbanner.mark_size(MARK) == (MARK_ROWS, MARK_COLS)
        assert keelbanner.mark_size(MARK_SMALL) == (SMALL_ROWS, SMALL_COLS)


class TestInnerWidth:
    def test_the_frame_and_its_padding_come_off_the_terminal_width(
        self, keelbanner
    ):
        assert keelbanner.inner_width(80) == 80 - keelbanner.FRAME

    def test_fits_and_center_measure_against_the_same_width(self, keelbanner):
        # Arrange: a mark exactly as wide as the box leaves room for
        width = keelbanner.inner_width(80)
        mark = "#" * width + "\n"

        # Act
        centred = keelbanner.center(mark, width)

        # Assert: it fits, and it needs no shift to fit
        assert keelbanner.fits(mark, 60, 80, USAGE_ROWS) is True
        assert centred == mark


class TestFits:
    def test_a_mark_fits_a_terminal_as_tall_as_it_needs(self, keelbanner):
        rows = rows_for(MARK_ROWS, keelbanner)

        assert keelbanner.fits(MARK, rows, 80, USAGE_ROWS) is True

    def test_it_does_not_fit_one_row_short(self, keelbanner):
        rows = rows_for(MARK_ROWS, keelbanner) - 1

        assert keelbanner.fits(MARK, rows, 80, USAGE_ROWS) is False

    def test_the_small_mark_fits_where_the_full_one_does_not(
        self, keelbanner
    ):
        rows = rows_for(SMALL_ROWS, keelbanner)

        assert keelbanner.fits(MARK_SMALL, rows, 80, USAGE_ROWS) is True
        assert keelbanner.fits(MARK, rows, 80, USAGE_ROWS) is False

    def test_a_mark_wider_than_the_box_does_not_fit(self, keelbanner):
        # the mark needs its own columns plus the frame and its padding
        narrow = SMALL_COLS + keelbanner.FRAME - 1

        assert keelbanner.fits(MARK_SMALL, 60, narrow, USAGE_ROWS) is False
        assert keelbanner.fits(MARK_SMALL, 60, narrow + 1, USAGE_ROWS) is True

    def test_an_empty_mark_never_fits(self, keelbanner):
        assert keelbanner.fits("", 60, 80, USAGE_ROWS) is False


class TestCenter:
    """The block is centred, not the lines: one indent for all of them, so
    the mark's internal alignment survives."""

    def test_an_odd_leftover_rounds_the_indent_down(self, keelbanner):
        # Arrange: 9 columns for a mark of 2, so 7 are left over
        # Act
        centred = keelbanner.center("##\n", 9)

        # Assert
        assert centred == "   ##\n"

    def test_an_even_leftover_splits_in_half(self, keelbanner):
        # Arrange: 10 columns for a mark of 2, so 8 are left over
        # Act
        centred = keelbanner.center("##\n", 10)

        # Assert
        assert centred == "    ##\n"

    def test_a_mark_wider_than_the_width_is_not_shifted_or_truncated(
        self, keelbanner
    ):
        # Act
        centred = keelbanner.center("#####\n", 3)

        # Assert
        assert centred == "#####\n"

    def test_a_mark_exactly_the_width_is_not_shifted(self, keelbanner):
        assert keelbanner.center("#####\n", 5) == "#####\n"

    def test_a_blank_line_stays_blank(self, keelbanner):
        # Act
        centred = keelbanner.center("#\n\n#\n", 5)

        # Assert
        assert centred == "  #\n\n  #\n"

    def test_a_line_of_spaces_comes_back_empty(self, keelbanner):
        # Arrange: the widest line of this mark is the line of 3 spaces,
        # so the indent is (5 - 3) // 2
        mark = "#\n   \n#\n"

        # Act
        centred = keelbanner.center(mark, 5)

        # Assert: the drawn rows are shifted, the other one carries nothing
        assert centred == " #\n\n #\n"

    def test_trailing_whitespace_in_the_art_does_not_survive(
        self, keelbanner
    ):
        # Arrange: the widest line of this mark is 4 columns, 2 of them
        # spaces, so the indent is (10 - 4) // 2
        mark = "##  \n#\n"

        # Act
        centred = keelbanner.center(mark, 10)

        # Assert
        assert centred == "   ##\n   #\n"

    def test_no_line_gains_trailing_whitespace(self, keelbanner):
        # Act
        centred = keelbanner.center(MARK, 60)

        # Assert
        assert all(line == line.rstrip() for line in centred.splitlines())

    def test_every_line_is_shifted_by_the_same_indent(self, keelbanner):
        # Arrange
        width = 60
        indent = " " * ((width - MARK_COLS) // 2)

        # Act
        centred = keelbanner.center(MARK, width)

        # Assert
        assert centred.splitlines() == [
            indent + line for line in MARK.splitlines()
        ]

    def test_centring_does_not_change_the_number_of_rows(self, keelbanner):
        # Act
        centred = keelbanner.center(MARK, 60)

        # Assert
        assert keelbanner.mark_size(centred)[0] == MARK_ROWS

    def test_the_centred_block_stays_plain_ascii(self, keelbanner):
        centred = keelbanner.center(MARK, 60)

        assert centred.isascii()
        assert "\x1b" not in centred

    @pytest.mark.parametrize("width", [19, 20, 21, 22, 40, 61, 200])
    def test_the_block_stands_in_the_middle_of_the_width(
        self, keelbanner, width
    ):
        # Arrange: a mark of this file's own whose widest line is neither
        # the first nor the last, and one of whose lines is indented in
        # the art, so an indent taken from the wrong line, or applied line
        # by line, comes out lopsided here
        mark = "/\\\n/================\\\n\n        ||\n"

        # Act
        centred = keelbanner.center(mark, width)

        # Assert: the margins are equal, or the one odd column is left
        # over on the right
        left, right = margins(centred, width)
        assert 0 <= right - left <= 1


class TestAnUnanticipatedSize:
    """A mark of a size nobody planned for.

    The art above the usage screen is redrawn in another repository, and
    the next drawing is smaller than this one. Nothing here is told a
    size: each case makes a mark of its own, and every expectation is
    derived from the size that mark measures.
    """

    @pytest.mark.parametrize(
        "rows, cols", [(1, 1), (2, 3), (7, 24), (12, 38), (31, 71), (44, 7)]
    )
    def test_it_is_measured_chosen_and_centred_whatever_its_size(
        self, keelbanner, tmp_path, rows, cols
    ):
        # Arrange: the mark on disk, and the smallest terminal it fits in
        # with nine columns to spare
        path = tmp_path / "banner.txt"
        path.write_text(drawn_mark(rows, cols))
        terminal_cols = cols + keelbanner.FRAME + 9
        terminal_rows = rows_for(rows, keelbanner)

        # Act
        chosen = keelbanner.choose(
            terminal_rows, terminal_cols, USAGE_ROWS, (str(path),)
        )
        width = keelbanner.inner_width(terminal_cols)
        centred = keelbanner.center(chosen, width)

        # Assert: measured, not assumed; centred; and costing the box only
        # its own rows and the blank line under it
        assert keelbanner.mark_size(chosen) == (rows, cols)
        assert keelbanner.mark_size(centred)[0] == rows
        left, right = margins(centred, width)
        assert 0 <= right - left <= 1
        assert keelbanner.added_rows(chosen) == (
            rows + keelbanner.SEPARATOR_ROWS
        )

    @pytest.mark.parametrize(
        "rows, cols", [(1, 1), (2, 3), (7, 24), (12, 38), (31, 71), (44, 7)]
    )
    def test_one_row_or_one_column_short_and_the_usage_screen_wins(
        self, keelbanner, tmp_path, rows, cols
    ):
        # Arrange
        path = tmp_path / "banner.txt"
        path.write_text(drawn_mark(rows, cols))
        paths = (str(path),)
        tall = rows_for(rows, keelbanner)
        wide = cols + keelbanner.FRAME

        # Act and Assert: it fits exactly, and neither one row nor one
        # column less leaves the usage text a line shorter
        assert keelbanner.choose(tall, wide, USAGE_ROWS, paths) is not None
        assert keelbanner.choose(tall, wide - 1, USAGE_ROWS, paths) is None
        assert keelbanner.choose(tall - 1, wide, USAGE_ROWS, paths) is None


class TestRead:
    def test_reads_the_installed_mark(self, keelbanner, marks):
        assert keelbanner.read(marks[0]) == MARK

    def test_a_missing_file_is_not_an_error(self, keelbanner, tmp_path):
        assert keelbanner.read(str(tmp_path / "absent")) is None

    def test_reads_a_utf8_mark_whatever_the_locale(
        self, keelbanner, tmp_path
    ):
        path = tmp_path / "banner-utf8.txt"
        path.write_bytes("█ █\n▀▀▀\n".encode())

        assert keelbanner.read(str(path)) == "█ █\n▀▀▀\n"

    def test_a_file_that_is_not_utf8_is_skipped(self, keelbanner, tmp_path):
        path = tmp_path / "banner.txt"
        path.write_bytes(b"\xff\xfe#\n")

        assert keelbanner.read(str(path)) is None


class TestChoose:
    """`choose` is given the room the dialog has on the screen
    (`available`), not the terminal, and the rows the box needs without
    a mark."""

    def test_no_room_above_the_box_gets_no_mark(self, keelbanner, marks):
        assert keelbanner.choose(USAGE_ROWS, 80, USAGE_ROWS, marks) is None

    def test_a_tall_terminal_gets_the_full_mark(self, keelbanner, marks):
        rows = rows_for(MARK_ROWS, keelbanner)

        assert keelbanner.choose(rows, 80, USAGE_ROWS, marks) == MARK

    def test_the_ladder_is_full_then_small_then_none_as_it_shrinks(
        self, keelbanner, marks
    ):
        # Arrange: the shortest room each mark needs
        full = rows_for(MARK_ROWS, keelbanner)
        small = rows_for(SMALL_ROWS, keelbanner)

        # Act
        ladder = [
            keelbanner.choose(rows, 80, USAGE_ROWS, marks)
            for rows in (full, full - 1, small, small - 1)
        ]

        # Assert
        assert ladder == [MARK, MARK_SMALL, MARK_SMALL, None]

    def test_a_terminal_too_narrow_falls_back_the_same_way(
        self, keelbanner, marks
    ):
        # Arrange: room for the small mark's columns but not the full
        # mark's, on a terminal tall enough for either
        rows = rows_for(MARK_ROWS, keelbanner)
        cols = SMALL_COLS + keelbanner.FRAME

        # Act and Assert
        assert keelbanner.choose(rows, cols, USAGE_ROWS, marks) == MARK_SMALL
        assert keelbanner.choose(rows, cols - 1, USAGE_ROWS, marks) is None

    def test_an_80_by_24_terminal_keeps_a_25_row_box_whole(
        self, keelbanner, marks
    ):
        rows, cols = keelbanner.available(24, 80)

        assert keelbanner.choose(rows, cols, USAGE_ROWS, marks) is None

    def test_the_paths_default_to_the_ladder_of_the_locale(
        self, keelbanner, monkeypatch
    ):
        # Arrange: every mark installed, a UTF-8 locale
        monkeypatch.setenv("LANG", "C.UTF-8")
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_CTYPE", raising=False)
        installed = {path: MARK_SMALL for path in keelbanner.MARKS_UTF8}
        installed.update({path: MARK for path in keelbanner.MARKS_ASCII})
        rows = rows_for(MARK_ROWS, keelbanner)

        # Act
        chosen = keelbanner.choose(
            rows, 80, USAGE_ROWS, reader=installed.get
        )

        # Assert: the UTF-8 ladder was read, and only it
        assert chosen == MARK_SMALL

    def test_a_mark_that_is_not_installed_is_skipped(self, keelbanner):
        chosen = keelbanner.choose(
            rows_for(MARK_ROWS, keelbanner),
            80,
            USAGE_ROWS,
            ("/absent/banner.txt", "/absent/banner-small.txt"),
            reader_of(**{"/absent/banner-small.txt": MARK_SMALL}),
        )

        assert chosen == MARK_SMALL

    def test_no_mark_installed_at_all(self, keelbanner):
        chosen = keelbanner.choose(
            rows_for(MARK_ROWS, keelbanner),
            80,
            USAGE_ROWS,
            ("/absent/banner.txt",),
            reader_of(),
        )

        assert chosen is None

    def test_the_paths_are_the_ones_the_core_overlay_installs(
        self, keelbanner
    ):
        assert keelbanner.MARKS_UTF8 == (
            "/etc/keel/banner-wide.txt",
            "/etc/keel/banner-utf8.txt",
            "/etc/keel/banner-small-utf8.txt",
        )
        assert keelbanner.MARKS_ASCII == (
            "/etc/keel/banner.txt",
            "/etc/keel/banner-small.txt",
        )


# Three synthetic tiers drawn in block characters, ragged, each smaller
# than the one before in both directions: a stand-in for the wide, the
# full and the small mark whose sizes are this file's own.
TIER_WIDE = "\n".join(["█" * 40] * 6 + ["▀" * 9]) + "\n"
TIER_FULL = "\n".join(["▒" * 12] * 5) + "\n"
TIER_SMALL = "\n".join(["░" * 5] * 2) + "\n"
TIERS = {"wide": TIER_WIDE, "full": TIER_FULL, "small": TIER_SMALL}


class TestTiers:
    """The largest tier the dialog has room for, in the order wide, full,
    small, none, decided by width and by height alike."""

    def ladder(self, keelbanner, rows, cols, used_rows=USAGE_ROWS):
        chosen = keelbanner.choose(
            rows, cols, used_rows, tuple(TIERS), TIERS.get
        )
        names = [name for name, mark in TIERS.items() if mark == chosen]
        return names[0] if names else None

    def test_a_block_character_is_one_column(self, keelbanner):
        assert keelbanner.mark_size("██\n▀\n") == (2, 2)
        assert keelbanner.mark_size(TIER_WIDE) == (7, 40)

    def test_room_for_everything_takes_the_wide_tier(self, keelbanner):
        rows = rows_for(7, keelbanner)

        assert self.ladder(keelbanner, rows, 40 + keelbanner.FRAME) == "wide"

    def test_one_column_short_of_the_wide_tier_takes_the_full_one(
        self, keelbanner
    ):
        rows = rows_for(7, keelbanner)

        assert self.ladder(keelbanner, rows, 40 + keelbanner.FRAME - 1) == (
            "full"
        )

    def test_one_row_short_of_the_wide_tier_takes_the_full_one(
        self, keelbanner
    ):
        rows = rows_for(7, keelbanner) - 1

        assert self.ladder(keelbanner, rows, 200) == "full"

    def test_then_the_small_tier_then_none(self, keelbanner):
        assert self.ladder(keelbanner, 60, 12 + keelbanner.FRAME - 1) == (
            "small"
        )
        assert self.ladder(keelbanner, rows_for(2, keelbanner), 200) == (
            "small"
        )
        assert self.ladder(keelbanner, rows_for(2, keelbanner) - 1, 200) is (
            None
        )
        assert self.ladder(keelbanner, 60, 5 + keelbanner.FRAME - 1) is None

    def test_a_taller_usage_text_pushes_the_choice_down(self, keelbanner):
        rows = rows_for(7, keelbanner)

        assert self.ladder(keelbanner, rows, 200, USAGE_ROWS) == "wide"
        assert self.ladder(keelbanner, rows, 200, USAGE_ROWS + 1) == "full"


class TestLocale:
    """dialog draws a character past ASCII only in a UTF-8 locale, so the
    UTF-8 marks go with a UTF-8 locale and the ASCII ones with any
    other. The locale is the one the dialog child inherits: LC_ALL, then
    LC_CTYPE, then LANG."""

    @pytest.mark.parametrize(
        "environ",
        [
            {"LANG": "C.UTF-8"},
            {"LANG": "en_US.utf8"},
            {"LANG": "de_DE.UTF-8@euro"},
            {"LANG": "C", "LC_CTYPE": "C.UTF-8"},
            {"LANG": "C", "LC_ALL": "pt_BR.UTF-8"},
        ],
    )
    def test_a_utf8_locale(self, keelbanner, environ):
        assert keelbanner.is_utf8(environ) is True
        assert keelbanner.marks(environ) == keelbanner.MARKS_UTF8

    @pytest.mark.parametrize(
        "environ",
        [
            {},
            {"LANG": "C"},
            {"LANG": "POSIX"},
            {"LANG": "en_US.ISO-8859-1"},
            {"LANG": "en_US.UTF-8", "LC_ALL": "C"},
            {"LANG": "en_US.UTF-8", "LC_CTYPE": "C"},
            {"LANG": "", "LC_ALL": "", "LC_CTYPE": ""},
        ],
    )
    def test_any_other_locale(self, keelbanner, environ):
        assert keelbanner.is_utf8(environ) is False
        assert keelbanner.marks(environ) == keelbanner.MARKS_ASCII

    def test_an_empty_setting_is_skipped_for_the_next(self, keelbanner):
        environ = {"LC_ALL": "", "LC_CTYPE": "", "LANG": "C.UTF-8"}

        assert keelbanner.is_utf8(environ) is True


class TestAvailable:
    """The room the dialog has on the screen. dialog centres a box on the
    whole screen, so the backtitle and the rule under it at the top cost
    the same rows at the bottom, and the shadow on the right the same
    columns on the left."""

    def test_the_screen_less_the_backtitle_and_the_shadow(self, keelbanner):
        assert keelbanner.available(24, 80) == (
            24 - keelbanner.SCREEN_ROWS,
            80 - keelbanner.SCREEN_COLS,
        )

    def test_measured_on_dialog_at_80_by_24(self, keelbanner):
        # A box of 20 rows is the tallest dialog draws clear of the
        # backtitle on 24 rows, measured with dialog 1.3 on trixie.
        assert keelbanner.available(24, 80) == (20, 76)

    def test_never_negative(self, keelbanner):
        assert keelbanner.available(2, 3) == (0, 0)


class TestTextRows:
    """The rows a text takes in a box whose inside is `width` wide: dialog
    wraps a line longer than that at a space."""

    def test_one_row_per_short_line(self, keelbanner):
        assert keelbanner.text_rows("a\nbb\n\nccc", 10) == 4

    def test_a_long_line_wraps_at_a_space(self, keelbanner):
        assert keelbanner.text_rows("aaaa bbbb cccc", 9) == 2

    def test_a_word_longer_than_the_width_is_broken(self, keelbanner):
        assert keelbanner.text_rows("x" * 25, 10) == 3

    def test_the_wrapped_usage_line_of_a_real_address(self, keelbanner):
        line = (
            "Admin:     https://[2804:710:d0:5:e0fc:fc60:e690:1c25]"
            "/wp-admin/"
        )

        assert keelbanner.text_rows(line, 61) == 2
        assert keelbanner.text_rows(line, len(line)) == 1


class TestBoxWidth:
    def test_a_mark_narrower_than_the_box_keeps_its_width(self, keelbanner):
        assert keelbanner.box_width(TIER_SMALL, 65, 76) == 65

    def test_a_wider_mark_widens_the_box_by_its_frame(self, keelbanner):
        assert keelbanner.box_width(TIER_WIDE, 30, 76) == (
            40 + keelbanner.FRAME
        )

    def test_never_wider_than_the_room(self, keelbanner):
        assert keelbanner.box_width(TIER_WIDE, 65, 50) == 50
        assert keelbanner.box_width(TIER_SMALL, 65, 50) == 50


class TestAbove:
    def test_the_mark_then_one_blank_line_then_the_text(self, keelbanner):
        # Arrange
        usage = "Web:  https://[2001:db8:1::10]"

        # Act
        block = keelbanner.above(usage, MARK_SMALL)

        # Assert
        lines = block.splitlines()
        assert lines[:SMALL_ROWS] == MARK_SMALL.splitlines()
        assert lines[SMALL_ROWS] == ""
        assert lines[SMALL_ROWS + 1] == usage
        assert len(lines) == SMALL_ROWS + 2

    def test_a_centred_mark_keeps_its_indent_and_the_text_keeps_none(
        self, keelbanner
    ):
        # Arrange
        usage = "Web:  https://[2001:db8:1::10]"
        width = 60
        indent = " " * ((width - SMALL_COLS) // 2)

        # Act
        block = keelbanner.above(usage, keelbanner.center(MARK_SMALL, width))

        # Assert
        lines = block.splitlines()
        assert lines[:SMALL_ROWS] == [
            indent + line for line in MARK_SMALL.splitlines()
        ]
        assert lines[SMALL_ROWS + 1] == usage

    def test_the_block_is_plain_ascii_with_no_escape(self, keelbanner):
        block = keelbanner.above("Web:  https://[2001:db8:1::10]", MARK)

        assert block.isascii()
        assert "\x1b" not in block


class TestAddedRows:
    def test_the_box_grows_by_the_mark_and_its_blank_line(self, keelbanner):
        separator = keelbanner.SEPARATOR_ROWS

        assert keelbanner.added_rows(MARK) == MARK_ROWS + separator
        assert keelbanner.added_rows(MARK_SMALL) == SMALL_ROWS + separator

    def test_centring_a_mark_does_not_change_what_it_costs(self, keelbanner):
        centred = keelbanner.center(MARK, 60)

        assert keelbanner.added_rows(centred) == keelbanner.added_rows(MARK)
