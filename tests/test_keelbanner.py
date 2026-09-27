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
        # the room, not the floor under the usage screen, is what decides
        assert tall - 1 >= keelbanner.MIN_ROWS

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


class TestChoose:
    def test_a_terminal_under_24_rows_gets_no_mark(self, keelbanner, marks):
        rows = keelbanner.MIN_ROWS - 1

        assert keelbanner.choose(rows, 80, USAGE_ROWS, marks) is None

    def test_a_tall_terminal_gets_the_full_mark(self, keelbanner, marks):
        rows = rows_for(MARK_ROWS, keelbanner)

        assert keelbanner.choose(rows, 80, USAGE_ROWS, marks) == MARK

    def test_the_ladder_is_full_then_small_then_none_as_it_shrinks(
        self, keelbanner, marks
    ):
        # Arrange: the shortest terminal each mark needs
        full = rows_for(MARK_ROWS, keelbanner)
        small = rows_for(SMALL_ROWS, keelbanner)
        assert small - 1 >= keelbanner.MIN_ROWS

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

    def test_an_80_by_24_terminal_keeps_the_usage_screen_whole(
        self, keelbanner, marks
    ):
        assert keelbanner.choose(24, 80, USAGE_ROWS, marks) is None

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

    def test_the_default_paths_are_the_ones_the_overlay_installs(
        self, keelbanner
    ):
        assert keelbanner.MARKS == (
            "/etc/keel/banner.txt",
            "/etc/keel/banner-small.txt",
        )


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
