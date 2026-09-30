"""The usage screen with IPv6 first, the mark above it, and the adapter
summary line.

`render_usage` and `render_usage_line` are pure functions: a template
string in, text out, no file and no dialog. `usage()` is exercised with
its collaborators stubbed (interfaces, addresses, the public address, the
template path, the terminal size and the mark files) and a fake console
that records the message box. The mark decision itself is measured in
tests/test_keelbanner.py; what is checked here is that the mark goes
above the usage text and arrives centred in the dialog, that the box
grows by what it takes and that nothing the screen already said moved.
"""

import pytest

import keelbanner

V6 = "2001:db8:1::10"
V4 = "192.0.2.10"

DEFAULT_TEMPLATE = """Web:       http://[$ipaddr6]
           https://[$ipaddr6]
Web shell: https://[$ipaddr6]:12320
Webmin:    https://[$ipaddr6]:12321
SSH/SFTP:  root@$ipaddr6 (port 22)

Web:       http://$ipaddr
           https://$ipaddr
Web shell: https://$ipaddr:12320
Webmin:    https://$ipaddr:12321
SSH/SFTP:  root@$ipaddr (port 22)"""

LEGACY_TEMPLATE = """Web:       https://$ipaddr
Webmin:    https://$ipaddr:12321
SSH/SFTP:  root@$ipaddr (port 22)"""

# Stand-ins for the two files the core overlay installs. Their size is
# arbitrary test data, not the size of the shipped art: the screen must
# measure whatever is installed, so nothing below is derived from the art
# and redrawing it stales no test. What the marks draw is the design
# system's business and is checked where the files live. The full one is
# an odd number of columns narrower than the box, so the indent the
# screen gives it pins the rounding too.
FULL_MARK_ROWS, FULL_MARK_COLS = 9, 22
SMALL_MARK_ROWS, SMALL_MARK_COLS = 4, 11
FULL_MARK = "\n".join(["#" * FULL_MARK_COLS] * FULL_MARK_ROWS) + "\n"
SMALL_MARK = "\n".join(["#" * SMALL_MARK_COLS] * SMALL_MARK_ROWS) + "\n"

# The box the usage screen draws itself in, as TurnkeyConsole sizes it.
BOX_ROWS = 25
BOX_COLS = 65

# A terminal with room for each mark above that box, and one too narrow
# for either of them.
TALL_TERMINAL = (BOX_ROWS + keelbanner.added_rows(FULL_MARK) + 5, 100)
SHORT_TERMINAL = (BOX_ROWS + keelbanner.added_rows(SMALL_MARK), 100)
NARROW_TERMINAL = (TALL_TERMINAL[0], SMALL_MARK_COLS + keelbanner.FRAME - 1)


def indent_of(mark_cols: int) -> str:
    """The indent the screen gives a mark of `mark_cols` columns on a
    terminal at least as wide as the box: the block is centred on what
    the box leaves inside its frame."""
    width = keelbanner.inner_width(BOX_COLS)
    return " " * ((width - mark_cols) // 2)


def centred_rows(mark_cols: int, mark_rows: int) -> list[str]:
    """The lines a mark of `mark_cols` by `mark_rows` draws once the
    screen has centred it."""
    return [indent_of(mark_cols) + "#" * mark_cols] * mark_rows


class TestRenderUsageLine:
    def test_substitutes_known_names_and_keeps_unknown_ones(self, confconsole):
        line = confconsole.render_usage_line(
            "$appname on $hostname at $ipaddr6 $unknown",
            {"appname": "Core", "hostname": "CORE", "ipaddr6": V6},
        )

        assert line == f"Core on CORE at {V6} $unknown"

    def test_line_with_a_none_placeholder_is_dropped(self, confconsole):
        assert (
            confconsole.render_usage_line(
                "Webmin: https://[$ipaddr6]:12321", {"ipaddr6": None}
            )
            is None
        )

    def test_ipv6_url_host_gets_brackets(self, confconsole):
        line = confconsole.render_usage_line(
            "https://$ipaddr:12321 and https://${ipaddr} root@$ipaddr",
            {"ipaddr": V6},
        )

        assert line == f"https://[{V6}]:12321 and https://[{V6}] root@{V6}"

    def test_brackets_written_in_the_template_are_not_doubled(
        self, confconsole
    ):
        line = confconsole.render_usage_line(
            "https://[$ipaddr6]:12321", {"ipaddr6": V6}
        )

        assert line == f"https://[{V6}]:12321"

    def test_ipv4_url_host_is_left_alone(self, confconsole):
        line = confconsole.render_usage_line(
            "https://$ipaddr:12321", {"ipaddr": V4}
        )

        assert line == f"https://{V4}:12321"

    def test_ipaddr_prefix_of_ipaddr6_is_not_bracketed_by_mistake(
        self, confconsole
    ):
        line = confconsole.render_usage_line(
            "https://$ipaddr6", {"ipaddr6": V6, "ipaddr": V4}
        )

        assert line == f"https://[{V6}]"

    def test_escaped_dollar_and_invalid_placeholder_survive(self, confconsole):
        line = confconsole.render_usage_line("costs $$5 at $ ", {"ipaddr": V4})

        assert line == "costs $5 at $ "


class TestRenderUsage:
    def test_dual_stack_shows_ipv6_block_then_ipv4_block(self, confconsole):
        text = confconsole.render_usage(DEFAULT_TEMPLATE, V6, V4)

        assert text == (
            f"Web:       http://[{V6}]\n"
            f"           https://[{V6}]\n"
            f"Web shell: https://[{V6}]:12320\n"
            f"Webmin:    https://[{V6}]:12321\n"
            f"SSH/SFTP:  root@{V6} (port 22)\n"
            "\n"
            f"Web:       http://{V4}\n"
            f"           https://{V4}\n"
            f"Web shell: https://{V4}:12320\n"
            f"Webmin:    https://{V4}:12321\n"
            f"SSH/SFTP:  root@{V4} (port 22)"
        )

    def test_ipv4_only_adapter_sees_the_previous_output(self, confconsole):
        text = confconsole.render_usage(DEFAULT_TEMPLATE, None, V4)

        assert text == (
            f"Web:       http://{V4}\n"
            f"           https://{V4}\n"
            f"Web shell: https://{V4}:12320\n"
            f"Webmin:    https://{V4}:12321\n"
            f"SSH/SFTP:  root@{V4} (port 22)"
        )

    def test_ipv6_only_adapter_sees_only_the_ipv6_block(self, confconsole):
        text = confconsole.render_usage(DEFAULT_TEMPLATE, V6, None)

        assert text == (
            f"Web:       http://[{V6}]\n"
            f"           https://[{V6}]\n"
            f"Web shell: https://[{V6}]:12320\n"
            f"Webmin:    https://[{V6}]:12321\n"
            f"SSH/SFTP:  root@{V6} (port 22)"
        )

    def test_legacy_template_on_ipv6_only_adapter_puts_ipv6_in_place(
        self, confconsole
    ):
        text = confconsole.render_usage(LEGACY_TEMPLATE, V6, None)

        assert text == (
            f"Web:       https://[{V6}]\n"
            f"Webmin:    https://[{V6}]:12321\n"
            f"SSH/SFTP:  root@{V6} (port 22)"
        )

    def test_legacy_template_on_dual_stack_gets_ipv6_lines_first(
        self, confconsole
    ):
        text = confconsole.render_usage(LEGACY_TEMPLATE, V6, V4)

        assert text == (
            f"IPv6 Web:  https://[{V6}]\n"
            f"IPv6 SSH:  root@{V6}\n"
            "\n"
            f"Web:       https://{V4}\n"
            f"Webmin:    https://{V4}:12321\n"
            f"SSH/SFTP:  root@{V4} (port 22)"
        )

    def test_legacy_template_without_web_line_gets_ssh_only(self, confconsole):
        text = confconsole.render_usage("SSH: root@$ipaddr", V6, V4)

        assert text == f"IPv6 SSH:  root@{V6}\n\nSSH: root@{V4}"

    def test_missing_template_dual_stack_shows_ipv6_ssh(self, confconsole):
        assert confconsole.render_usage("", V6, V4) == f"IPv6 SSH:  root@{V6}"

    def test_missing_template_without_ipv6_is_empty(self, confconsole):
        assert confconsole.render_usage("", None, V4) == ""

    def test_legacy_template_without_any_address_renders_none_text(
        self, confconsole
    ):
        # today's behaviour, reached only when usage() has a default
        # adapter without addresses: the template is kept, nothing crashes
        text = confconsole.render_usage(LEGACY_TEMPLATE, None, None)

        assert text == ""

    def test_appname_and_hostname_are_substituted(self, confconsole):
        text = confconsole.render_usage(
            "$appname ($hostname): root@$ipaddr6",
            V6,
            None,
            appname="TurnKey Linux CORE",
            hostname="CORE",
        )

        assert text == f"TurnKey Linux CORE (CORE): root@{V6}"

    def test_public_ipv6_from_publicip_cmd_is_bracketed_in_urls(
        self, confconsole
    ):
        text = confconsole.render_usage(LEGACY_TEMPLATE, V6, "2001:db8::1")

        assert "Web:       https://[2001:db8::1]" in text.splitlines()


class TestDescribeInterface:
    def test_ipv6_then_ipv4_with_one_shared_method(self, confconsole):
        assert (
            confconsole.describe_interface(V6, "dhcp", V4, "dhcp")
            == f"{V6}, {V4} (dhcp)"
        )

    def test_differing_methods_are_shown_per_family(self, confconsole):
        assert (
            confconsole.describe_interface(V6, "static", V4, "dhcp")
            == f"{V6} (static), {V4} (dhcp)"
        )

    def test_method_missing_on_one_family_is_shown_per_family(
        self, confconsole
    ):
        assert (
            confconsole.describe_interface(V6, None, V4, "dhcp")
            == f"{V6}, {V4} (dhcp)"
        )
        assert (
            confconsole.describe_interface(V6, "static", V4, None)
            == f"{V6} (static), {V4}"
        )

    def test_single_family_keeps_the_previous_format(self, confconsole):
        assert confconsole.describe_interface(None, None, V4, "dhcp") == (
            f"{V4} (dhcp)"
        )
        assert confconsole.describe_interface(V6, None, None, None) == V6

    def test_no_address_is_not_configured(self, confconsole):
        assert (
            confconsole.describe_interface(None, None, None, None)
            == "not configured"
        )


class TestNetworkMenuIPv6First:
    def test_secondary_adapter_has_no_default_marker(self, tc, net_stubs):
        net_stubs["ifnames"] = ["eth0", "eth1"]
        net_stubs["ipv6conf"] = (V6, "64")

        assert tc()._get_netmenu()[1] == ("eth1", V6)


@pytest.fixture
def usage_env(confconsole, net_stubs, monkeypatch, tmp_path):
    """Everything usage() reads, replaced: adapters and addresses through
    net_stubs, the public address through _get_public_ipaddr, the
    template through conf.path. The screen runs no command: a Keel
    appliance has no TKLBAM to ask (handbook decision 0020, the TurnKey
    Hub is not a dependency), so any command it ran fails the test."""
    state = {"publicip": None}

    def fake_run(argv, **kwargs):
        raise AssertionError(f"unexpected command {argv}")

    monkeypatch.setattr(confconsole.subprocess, "run", fake_run)
    monkeypatch.setattr(
        confconsole.TurnkeyConsole,
        "_get_public_ipaddr",
        classmethod(lambda cls: state["publicip"]),
    )
    monkeypatch.setattr(confconsole.netinfo, "get_hostname", lambda: "core")
    template = tmp_path / "services.txt"
    template.write_text(DEFAULT_TEMPLATE + "\n")

    def fake_path(name):
        assert name == "services.txt"
        if state.get("no_template"):
            raise confconsole.conf.ConfconsoleConfError(name)
        return str(template)

    monkeypatch.setattr(confconsole.conf, "path", fake_path)

    # The console the screen is drawn on, and the marks installed on it.
    # An 80 by 24 terminal with no mark file is the default, which is what
    # a test host has and what the screen looked like before the mark.
    state["terminal"] = (24, 80)
    state["marks"] = {}
    monkeypatch.setattr(
        confconsole.keelbanner, "terminal_size", lambda: state["terminal"]
    )
    monkeypatch.setattr(
        confconsole.keelbanner, "read", lambda path: state["marks"].get(path)
    )
    state["net"] = net_stubs
    return state


def install_marks(state, full=FULL_MARK, small=SMALL_MARK):
    """Put the two marks where the core overlay installs them."""
    state["marks"] = {keelbanner.MARK: full, keelbanner.MARK_SMALL: small}


def make_usage_console(tc, advanced=True):
    console = tc()
    console.advanced_enabled = advanced
    console.appname = "TurnKey Linux CORE"
    console.height = BOX_ROWS
    console.width = BOX_COLS
    console.running = True
    return console


class TestUsageScreen:
    def test_dual_stack_message_box_shows_ipv6_first(self, tc, usage_env):
        usage_env["net"]["ipconf"] = (V4, "255.255.255.0", "192.0.2.1", [])
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)

        assert console.usage() == "advanced"

        kind, title, text = console.console.calls[-1]
        assert (kind, title) == ("msgbox", "CORE appliance services")
        lines = text.splitlines()
        assert lines[0] == f"Web:       http://[{V6}]"
        assert lines[6] == f"Web:       http://{V4}"
        assert lines[-1] == f"SSH/SFTP:  root@{V4} (port 22)"
        assert console.running is True

    def test_no_turnkey_hub_and_no_tklbam_lines(self, tc, usage_env):
        # The lines the maintainer saw at the end of the first boot of
        # Template B2: TurnKey's backup and hub service, which a Keel
        # appliance neither ships nor depends on.
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)

        console.usage()

        text = console.console.calls[-1][2]
        assert "TKLBAM" not in text
        assert "TurnKey Backups" not in text
        assert "hub.turnkeylinux.org" not in text

    def test_public_address_replaces_ipv4_only(self, tc, usage_env):
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["publicip"] = "198.51.100.7"
        console = make_usage_console(tc)

        console.usage()

        text = console.console.calls[-1][2]
        assert f"root@{V6} (port 22)" in text
        assert "root@198.51.100.7 (port 22)" in text

    def test_missing_template_falls_back_to_ipv6_ssh_line(
        self, tc, usage_env
    ):
        usage_env["no_template"] = True
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)

        console.usage()

        text = console.console.calls[-1][2]
        assert text.splitlines()[0] == f"IPv6 SSH:  root@{V6}"

    def test_the_text_is_the_services_and_nothing_after_them(
        self, tc, usage_env, confconsole, monkeypatch
    ):
        long_text = "\n".join(f"Service {i}: root@{V6}" for i in range(20))
        monkeypatch.setattr(
            confconsole, "render_usage", lambda *args, **kwargs: long_text
        )
        console = make_usage_console(tc)

        console.usage()

        assert console.console.calls[-1][2] == long_text

    def test_quit_button_without_advanced_menu(self, tc, usage_env):
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc, advanced=False)

        assert console.usage() == "quit"

    def test_no_adapter_goes_to_advanced(self, tc, usage_env):
        usage_env["net"]["ifnames"] = []
        console = make_usage_console(tc)

        assert console.usage() == "advanced"
        assert console.console.calls == [
            ("msgbox", "Error", "No network adapters detected")
        ]

    def test_no_default_adapter_goes_to_networking(self, tc, usage_env):
        usage_env["net"]["default_nic"] = None
        console = make_usage_console(tc)

        assert console.usage() == "networking"
        assert console.console.calls[-1][2] == (
            "Networking is not yet configured"
        )

    def test_no_adapter_is_fatal_without_advanced_menu(self, tc, usage_env):
        usage_env["net"]["ifnames"] = []
        console = make_usage_console(tc, advanced=False)

        with pytest.raises(SystemExit):
            console.usage()

    def test_no_default_adapter_is_fatal_without_advanced_menu(
        self, tc, usage_env
    ):
        usage_env["net"]["default_nic"] = None
        console = make_usage_console(tc, advanced=False)

        with pytest.raises(SystemExit):
            console.usage()

    def test_closing_the_box_stops_the_loop(self, tc, usage_env):
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)
        console.console.OK = "other"

        console.usage()

        assert console.running is False


class TestUsageMark:
    """The mark goes above the usage text when the terminal has room for
    it over and above the rows the screen already uses, centred on the
    columns the box leaves inside its frame, and the box grows by exactly
    what the mark takes, so no line of the screen is lost. Whatever size
    the installed art is, the screen measures it: the sizes below are the
    fixtures' own."""

    def test_a_tall_terminal_gets_the_full_mark_above_the_services(
        self, tc, usage_env
    ):
        # Arrange
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = TALL_TERMINAL
        install_marks(usage_env)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert
        text = console.console.calls[-1][2]
        lines = text.splitlines()
        assert lines[:FULL_MARK_ROWS] == centred_rows(
            FULL_MARK_COLS, FULL_MARK_ROWS
        )
        assert lines[FULL_MARK_ROWS] == ""
        assert lines[FULL_MARK_ROWS + 1] == f"Web:       http://[{V6}]"
        assert console.console.msgbox_kwargs["height"] == BOX_ROWS + (
            keelbanner.added_rows(FULL_MARK)
        )

    def test_the_mark_is_centred_and_the_usage_text_stays_left_aligned(
        self, tc, usage_env
    ):
        # Arrange: the same screen twice, first without a mark installed
        usage_env["net"]["ipconf"] = (V4, "255.255.255.0", "192.0.2.1", [])
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = TALL_TERMINAL
        plain = make_usage_console(tc)
        plain.usage()
        without_mark = plain.console.calls[-1][2]
        install_marks(usage_env)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert: the mark block, indented, a blank line, then the very
        # text the screen shows without it, not a column further in
        text = console.console.calls[-1][2]
        block = "\n".join(centred_rows(FULL_MARK_COLS, FULL_MARK_ROWS))
        assert text == f"{block}\n\n{without_mark}"
        assert without_mark.splitlines()[0] == f"Web:       http://[{V6}]"

    def test_a_mark_as_wide_as_the_box_is_not_indented_or_truncated(
        self, tc, usage_env
    ):
        # Arrange
        width = keelbanner.inner_width(BOX_COLS)
        wide = "\n".join(["#" * width] * FULL_MARK_ROWS) + "\n"
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = TALL_TERMINAL
        install_marks(usage_env, full=wide)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert
        lines = console.console.calls[-1][2].splitlines()
        assert lines[:FULL_MARK_ROWS] == ["#" * width] * FULL_MARK_ROWS

    def test_a_shorter_terminal_falls_back_to_the_small_mark(
        self, tc, usage_env
    ):
        # Arrange
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = SHORT_TERMINAL
        install_marks(usage_env)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert
        lines = console.console.calls[-1][2].splitlines()
        assert lines[:SMALL_MARK_ROWS] == centred_rows(
            SMALL_MARK_COLS, SMALL_MARK_ROWS
        )
        assert lines[SMALL_MARK_ROWS + 1] == f"Web:       http://[{V6}]"
        assert console.console.msgbox_kwargs["height"] == BOX_ROWS + (
            keelbanner.added_rows(SMALL_MARK)
        )

    def test_80_by_24_keeps_the_usage_screen_whole(self, tc, usage_env):
        # Arrange
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = (24, 80)
        install_marks(usage_env)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert
        text = console.console.calls[-1][2]
        assert "#" not in text
        assert text.splitlines()[0] == f"Web:       http://[{V6}]"
        assert console.console.msgbox_kwargs["height"] == BOX_ROWS

    def test_an_appliance_without_the_mark_files_is_unchanged(
        self, tc, usage_env
    ):
        # Arrange
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = TALL_TERMINAL
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert
        text = console.console.calls[-1][2]
        assert text.splitlines()[0] == f"Web:       http://[{V6}]"
        assert console.console.msgbox_kwargs["height"] == BOX_ROWS

    def test_the_mark_does_not_displace_the_ipv4_block(
        self, tc, usage_env
    ):
        # Arrange
        usage_env["net"]["ipconf"] = (V4, "255.255.255.0", "192.0.2.1", [])
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = TALL_TERMINAL
        install_marks(usage_env)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert: the IPv4 block keeps its place under the IPv6 one, the
        # mark and its blank line above them both
        lines = console.console.calls[-1][2].splitlines()
        ipv4_line = keelbanner.added_rows(FULL_MARK) + 6
        assert lines[ipv4_line] == f"Web:       http://{V4}"
        assert lines[-1] == f"SSH/SFTP:  root@{V4} (port 22)"

    def test_a_narrow_terminal_drops_the_mark(self, tc, usage_env):
        # Arrange
        usage_env["net"]["ipv6conf"] = (V6, "64")
        usage_env["terminal"] = NARROW_TERMINAL
        install_marks(usage_env)
        console = make_usage_console(tc)

        # Act
        console.usage()

        # Assert
        assert "#" not in console.console.calls[-1][2]


class TestUsageUsesIfutilPreference:
    """The address on the screen is the one get_ipv6conf ranks first:
    static before dynamic, privacy (temporary) addresses last."""

    def test_stable_address_reaches_the_template(
        self, tc, usage_env, confconsole, ifutil, monkeypatch
    ):
        out = (
            "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n"
            "    inet6 2001:db8:1:0:aaaa::1/64 scope global"
            " temporary dynamic\n"
            "    inet6 2001:db8:1:0:be24:11ff:feed:44bd/64 scope global"
            " dynamic mngtmpaddr\n"
            f"    inet6 {V6}/64 scope global\n"
        )
        monkeypatch.setattr(
            ifutil.subprocess, "check_output", lambda *a, **k: out
        )
        monkeypatch.setattr(
            confconsole.ifutil,
            "get_ipv6conf",
            usage_env["net"]["real_get_ipv6conf"],
        )
        console = make_usage_console(tc)

        console.usage()

        text = console.console.calls[-1][2]
        assert text.splitlines()[0] == f"Web:       http://[{V6}]"
        assert "aaaa" not in text and "be24" not in text
