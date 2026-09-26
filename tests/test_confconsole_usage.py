"""The usage screen with IPv6 first, and the adapter summary line.

`render_usage` and `render_usage_line` are pure functions: a template
string in, text out, no file and no dialog. `usage()` is exercised with
its collaborators stubbed (interfaces, addresses, `tklbam-status`, the
template path) and a fake console that records the message box.
"""

import pytest

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


class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


@pytest.fixture
def usage_env(confconsole, net_stubs, monkeypatch, tmp_path):
    """Everything usage() reads, replaced: adapters and addresses through
    net_stubs, tklbam-status and the public address command through a
    scripted subprocess.run, the template through conf.path."""
    state = {"tklbam": "TKLBAM: not initialized", "publicip": None}

    def fake_run(argv, **kwargs):
        if argv == ["which", "tklbam-status"]:
            return FakeCompleted("/usr/bin/tklbam-status\n")
        if argv == ["/usr/bin/tklbam-status", "--short"]:
            return FakeCompleted(state["tklbam"] + "\n")
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
    state["net"] = net_stubs
    return state


def make_usage_console(tc, advanced=True):
    console = tc()
    console.advanced_enabled = advanced
    console.appname = "TurnKey Linux CORE"
    console.height = 25
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
        assert "TKLBAM: not initialized" in text
        assert lines[-1] == "             https://hub.turnkeylinux.org"
        assert console.running is True

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

    def test_gap_before_the_footer_shrinks_with_the_text(self, tc, usage_env):
        # 11 lines of services on a 25 line screen leave a gap of 3
        usage_env["net"]["ipconf"] = (V4, "255.255.255.0", "192.0.2.1", [])
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)

        console.usage()

        text = console.console.calls[-1][2]
        footer = "TKLBAM: not initialized\n\n\n\n         TurnKey Backups"
        assert footer in text

    def test_gap_never_drops_below_one_line(
        self, tc, usage_env, confconsole, monkeypatch
    ):
        long_text = "\n".join(f"Service {i}: root@{V6}" for i in range(20))
        monkeypatch.setattr(
            confconsole, "render_usage", lambda *args, **kwargs: long_text
        )
        console = make_usage_console(tc)

        console.usage()

        text = console.console.calls[-1][2]
        assert "TKLBAM: not initialized\n\n         TurnKey Backups" in text

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

    def test_tklbam_missing_is_reported(
        self, tc, usage_env, confconsole, monkeypatch
    ):
        def fake_run(argv, **kwargs):
            assert argv == ["which", "tklbam-status"]
            return FakeCompleted("")

        monkeypatch.setattr(confconsole.subprocess, "run", fake_run)
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)

        console.usage()

        assert "TKLBAM not found" in console.console.calls[-1][2]

    def test_closing_the_box_stops_the_loop(self, tc, usage_env):
        usage_env["net"]["ipv6conf"] = (V6, "64")
        console = make_usage_console(tc)
        console.console.OK = "other"

        console.usage()

        assert console.running is False


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
