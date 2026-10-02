"""The size of a dialog box, so that no text is cut at its edge.

The maintainer's screenshots of the Keel Web step 8 image showed menu
descriptions cut at the right border of confconsole's 65 column box. A
menu now widens to its widest line, up to what the terminal leaves, and
a description is shortened with an ellipsis only when even that is not
enough. The numbers are dialog 1.3's, measured on trixie.
"""

import pytest

import keelbanner
import keelfit


class TestRoom:
    def test_the_terminal_less_the_backtitle_and_the_shadow(
        self, monkeypatch
    ):
        monkeypatch.setattr(keelbanner, "terminal_size", lambda: (24, 80))

        assert keelfit.room() == (20, 76)

    def test_a_larger_terminal_leaves_more(self, monkeypatch):
        monkeypatch.setattr(keelbanner, "terminal_size", lambda: (30, 100))

        assert keelfit.room() == (26, 96)


class TestBox:
    def test_a_box_that_fits_is_left_as_it_is(self):
        assert keelfit.box(20, 65, (26, 96)) == (20, 65)

    def test_a_box_taller_or_wider_than_the_room_is_cut_to_it(self):
        # confconsole's 25 rows on a 24 row console drew over the
        # backtitle
        assert keelfit.box(25, 120, (20, 76)) == (20, 76)


CHOICES = [
    ("Networking", "Configure appliance networking"),
    ("Instance", "The instance spec, and what this node runs"),
]


class TestMenuWidth:
    def test_a_narrow_menu_keeps_the_box_width_it_was_given(self):
        assert keelfit.menu_width([("Quit", "Quit")], 65, 76) == 65

    def test_the_widest_tag_and_the_widest_item_set_the_width(self):
        # dialog lines every item up after the widest tag
        needed = (len("Networking") + keelfit.TAG_GAP
                  + len("The instance spec, and what this node runs")
                  + keelfit.MENU_CHROME)

        assert keelfit.menu_width(CHOICES, 40, 76) == needed

    def test_never_wider_than_the_room(self):
        assert keelfit.menu_width([("Tag", "x" * 200)], 65, 76) == 76

    def test_an_empty_menu_keeps_its_width(self):
        assert keelfit.menu_width([], 65, 76) == 65

    def test_the_longest_line_of_the_text_widens_it_too(self):
        # a public key line of 68 columns wrapped in a 65 column box
        text = "short\n" + "k" * 68 + "\nshort"

        assert keelfit.menu_width([("A", "b")], 65, 76, text) == (
            68 + keelfit.TEXT_CHROME)
        assert keelfit.menu_width([], 65, 70, text) == 70


class TestTextBox:
    """A message box sized to its text and to the terminal, where dialog's
    own autosize drew over the backtitle and wrapped at its own width"""

    def test_as_wide_as_the_longest_line_and_as_tall_as_its_rows(self):
        text = "a" * 50 + "\nb"

        assert keelfit.text_box(text, (20, 76)) == (
            2 + keelfit.BOX_CHROME, 50 + keelfit.TEXT_CHROME)

    def test_never_larger_than_the_room(self):
        text = "\n".join(["word " * 30] * 40)

        assert keelfit.text_box(text, (20, 76)) == (20, 76)

    def test_a_short_text_keeps_a_readable_width(self):
        assert keelfit.text_box("ok", (20, 76)) == (
            1 + keelfit.BOX_CHROME, keelfit.MIN_TEXT_WIDTH)

    def test_an_8_column_terminal_still_gets_a_box(self, monkeypatch):
        # 8 columns leave 4 for a box, 0 for its text: text_rows was
        # asked to wrap at 0, and a height of 0 made dialog autosize
        monkeypatch.setattr(keelbanner, "terminal_size", lambda: (3, 8))
        space = keelfit.room()

        height, width = keelfit.text_box("a few words of text", space)

        assert space == (0, 4)
        assert (height, width) == (1, 4)
        assert keelfit.box(20, 65, space) == (1, 4)

    def test_a_text_too_wide_for_a_box_of_one_column_is_one_a_row(self):
        assert keelfit.text_box("abc", (20, 4)) == (3 + keelfit.BOX_CHROME, 4)

    def test_the_text_width_inside_the_box(self):
        assert keelfit.text_width((20, 76)) == 72


class TestFitChoices:
    def test_choices_that_fit_are_unchanged(self):
        assert keelfit.fit_choices(CHOICES, 76) == CHOICES

    def test_an_item_wider_than_the_box_ends_in_an_ellipsis(self):
        fitted = keelfit.fit_choices([("Tag", "word " * 30)], 40)

        (tag, item), = fitted
        assert tag == "Tag"
        assert item.endswith(keelfit.ELLIPSIS)
        room = 40 - keelfit.MENU_CHROME - keelfit.TAG_GAP - len("Tag")
        assert len(item) == room

    def test_the_tags_are_never_changed_since_dialog_answers_with_them(self):
        choices = [("A" * 30, "b" * 60)]

        assert keelfit.fit_choices(choices, 50)[0][0] == "A" * 30

    @pytest.mark.parametrize("room, expected", [
        (3, "abc"), (2, "ab"), (0, ""), (-4, ""),
    ])
    def test_no_room_for_an_ellipsis_cuts_plainly(self, room, expected):
        assert keelfit.clip("abcdef", room) == expected

    def test_clip_leaves_a_short_text_alone(self):
        assert keelfit.clip("abc", 10) == "abc"
