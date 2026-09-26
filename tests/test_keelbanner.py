"""The Keel mark above the usage screen.

`keelbanner` is pure but for `read` and `terminal_size`: a mark string and
a terminal size in, a decision out. The marks used here are the ones the
core overlay installs, written to a scratch directory so no test depends
on the host carrying `/etc/keel/banner.txt`.
"""

import os

import pytest

# The two marks of the design system, as the core overlay installs them.
MARK = """\
       .--------------------.
       +%%%%%%%%%%%%%%%%%%%%+
        .........##.........
    .=+++++++++++%%+++++++++++=.
    :#%%%%%%%%%%%%%%%%%%%%%%%%#:
                 ##
:=================%%=================:
+%%%%@@@%%%%%%%%%%%%%%%%%%%%%%@@@%%%%+
 ...:%%%=.........##.........=%%%:...
     %%%:         ##         :%%%
     %%%:         ##         :%%%
     %%%=         ##         =%%%
     +%%#         ##         #%%+
      #%%*.       ##       .*%%#
      .*%@%=.     ##     .=%@%*.
        -#%@%*=:..++..:=*%@%#-
          -+#%@@%*++*%@@%#+-
             :-=++++++=-:
                  ==
"""

MARK_SMALL = """\
   ._______.
   +%%%%%%%+
  .====##====.
 :=========##=========:
 +%%@%%%%%%%%%%%%@%%%+
  ..:%%=...##...=%%:..
     %%:   ##   :%%
     +%#.  ##  .#%+
      *%@=.##.=@%*
        -*%@%%@%*-
           .++.
"""

USAGE_ROWS = 25


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
    def test_the_full_mark_is_19_rows_by_38_columns(self, keelbanner):
        assert keelbanner.mark_size(MARK) == (19, 38)

    def test_the_small_mark_is_11_rows_by_23_columns(self, keelbanner):
        assert keelbanner.mark_size(MARK_SMALL) == (11, 23)

    def test_an_empty_mark_has_no_size(self, keelbanner):
        assert keelbanner.mark_size("") == (0, 0)


class TestFits:
    def test_the_full_mark_fits_a_tall_terminal(self, keelbanner):
        assert keelbanner.fits(MARK, 45, 80, USAGE_ROWS) is True

    def test_the_full_mark_does_not_fit_one_row_short(self, keelbanner):
        assert keelbanner.fits(MARK, 44, 80, USAGE_ROWS) is False

    def test_the_small_mark_fits_where_the_full_one_does_not(
        self, keelbanner
    ):
        assert keelbanner.fits(MARK_SMALL, 37, 80, USAGE_ROWS) is True

    def test_a_mark_wider_than_the_box_does_not_fit(self, keelbanner):
        # 23 columns of mark and 4 of frame need 27
        assert keelbanner.fits(MARK_SMALL, 60, 26, USAGE_ROWS) is False
        assert keelbanner.fits(MARK_SMALL, 60, 27, USAGE_ROWS) is True

    def test_an_empty_mark_never_fits(self, keelbanner):
        assert keelbanner.fits("", 60, 80, USAGE_ROWS) is False


class TestRead:
    def test_reads_the_installed_mark(self, keelbanner, marks):
        assert keelbanner.read(marks[0]) == MARK

    def test_a_missing_file_is_not_an_error(self, keelbanner, tmp_path):
        assert keelbanner.read(str(tmp_path / "absent")) is None


class TestChoose:
    def test_a_terminal_under_24_rows_gets_no_mark(self, keelbanner, marks):
        assert keelbanner.choose(23, 80, USAGE_ROWS, marks) is None

    def test_a_tall_terminal_gets_the_full_mark(self, keelbanner, marks):
        assert keelbanner.choose(45, 80, USAGE_ROWS, marks) == MARK

    def test_a_shorter_terminal_falls_back_to_the_small_mark(
        self, keelbanner, marks
    ):
        assert keelbanner.choose(40, 80, USAGE_ROWS, marks) == MARK_SMALL

    def test_an_80_by_24_terminal_keeps_the_usage_screen_whole(
        self, keelbanner, marks
    ):
        assert keelbanner.choose(24, 80, USAGE_ROWS, marks) is None

    def test_a_mark_that_is_not_installed_is_skipped(self, keelbanner):
        chosen = keelbanner.choose(
            45,
            80,
            USAGE_ROWS,
            ("/absent/banner.txt", "/absent/banner-small.txt"),
            reader_of(**{"/absent/banner-small.txt": MARK_SMALL}),
        )

        assert chosen == MARK_SMALL

    def test_no_mark_installed_at_all(self, keelbanner):
        chosen = keelbanner.choose(
            45, 80, USAGE_ROWS, ("/absent/banner.txt",), reader_of()
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
        # Act
        block = keelbanner.above("Web:  https://[2001:db8:1::10]", MARK_SMALL)

        # Assert
        lines = block.splitlines()
        assert lines[0] == "   ._______."
        assert lines[10] == "           .++."
        assert lines[11] == ""
        assert lines[12] == "Web:  https://[2001:db8:1::10]"
        assert len(lines) == 13

    def test_the_block_is_plain_ascii_with_no_escape(self, keelbanner):
        block = keelbanner.above("Web:  https://[2001:db8:1::10]", MARK)

        assert block.isascii()
        assert "\x1b" not in block


class TestAddedRows:
    def test_the_box_grows_by_the_mark_and_its_blank_line(self, keelbanner):
        assert keelbanner.added_rows(MARK) == 20
        assert keelbanner.added_rows(MARK_SMALL) == 12
