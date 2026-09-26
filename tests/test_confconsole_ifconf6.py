"""The static IPv6 dialog and the IPv6 lines of the networking menu.

No dialog is launched: TurnkeyConsole is instantiated without __init__
(the `tc` fixture in conftest.py), its `console` is a scripted fake that
records every call and answers from a queue, and the ifutil functions the
dialog calls are stubs that record their arguments. The dialog must hold
no logic beyond collecting fields and calling ifutil, so these tests check
exactly that.
"""

import pytest

from conftest import INET6_ONLY, STATIC_V4, UNCONFIGURED

ADDR = "2001:db8:1::10/64"
GW = "fe80::1"
NS = "2001:db8::53"


@pytest.fixture
def ifutil_calls(confconsole, monkeypatch):
    """Stub the ifutil functions the dialog calls; return the call log."""
    calls = {}
    monkeypatch.setattr(
        confconsole.ifutil, "get_ip6conf", lambda ifname: (ADDR, GW, [NS])
    )
    results = {"set_static6": None, "set_dhcp6": None}

    def stub(name):
        def _call(ifname, *args):
            calls.setdefault(name, []).append((ifname, *args))
            return results[name]

        return _call

    monkeypatch.setattr(confconsole.ifutil, "set_static6", stub("set_static6"))
    monkeypatch.setattr(confconsole.ifutil, "set_dhcp6", stub("set_dhcp6"))
    calls["results"] = results
    return calls


@pytest.fixture
def not_in_ssh(monkeypatch):
    monkeypatch.delenv("SSH_CONNECTION", raising=False)


class TestFormatFields:
    def test_default_offset_equals_label_length(self, confconsole):
        assert confconsole.format_fields([("IP Address", "x", 30, 15)]) == [
            ("IP Address", 1, 1, "x", 1, 31, 30, 15)
        ]

    def test_field_offset_separates_label_from_width(self, confconsole):
        fields = confconsole.format_fields(
            [("IPv6 Address/Prefix", ADDR, 43, 43), ("Name Server", "", 43, 39)],
            field_offset=20,
        )

        assert fields == [
            ("IPv6 Address/Prefix", 1, 1, ADDR, 1, 21, 43, 43),
            ("Name Server", 2, 1, "", 2, 21, 43, 39),
        ]


class TestStaticIPv6Form:
    def test_prefills_from_get_ip6conf_and_applies(
        self, tc, ifutil_calls, not_in_ssh
    ):
        console = tc(forms=[("ok", [ADDR, GW, NS, "2001:db8::54"])])

        assert console._ifconf_staticipv6() == "ifconf"

        kind, text, fields, kwargs = console.console.calls[0]
        assert kind == "form"
        assert text == "Static IPv6 configuration (eth0)"
        assert kwargs == {"autosize": True}
        labels = [f[0] for f in fields]
        assert labels == [
            "IPv6 Address/Prefix", "IPv6 Gateway", "Name Server", "Name Server",
        ]
        assert [f[3] for f in fields] == [ADDR, GW, NS, ""]
        # 43 columns for address/prefix, 39 for a plain address, none 15
        assert [f[7] for f in fields] == [43, 39, 39, 39]
        assert all(f[5] == 21 for f in fields)
        assert ifutil_calls["set_static6"] == [
            ("eth0", ADDR, GW, [NS, "2001:db8::54"])
        ]
        assert "set_dhcp6" not in ifutil_calls

    def test_whitespace_is_stripped_and_blank_nameservers_dropped(
        self, tc, ifutil_calls, not_in_ssh
    ):
        console = tc(forms=[("ok", [f" {ADDR} ", "", "", f"{NS} "])])

        console._ifconf_staticipv6()

        assert ifutil_calls["set_static6"] == [("eth0", ADDR, "", [NS])]

    def test_error_from_ifutil_is_shown_and_form_reopens(
        self, tc, ifutil_calls, not_in_ssh
    ):
        ifutil_calls["results"]["set_static6"] = "IPv6 gateway must be IPv6"
        console = tc(
            forms=[("ok", ["192.0.2.10/24", "192.0.2.1", ""]), ("cancel", [])]
        )

        assert console._ifconf_staticipv6() == "ifconf"

        kinds = [c[0] for c in console.console.calls]
        assert kinds == ["form", "msgbox", "form"]
        assert console.console.calls[1][2] == "IPv6 gateway must be IPv6"
        # the second form shows what was typed, plus a blank name server
        assert [f[3] for f in console.console.calls[2][2]] == [
            "192.0.2.10/24", "192.0.2.1", "",
        ]
        assert len(ifutil_calls["set_static6"]) == 1

    def test_cancel_calls_nothing(self, tc, ifutil_calls, not_in_ssh):
        console = tc(forms=[("cancel", [])])

        assert console._ifconf_staticipv6() == "ifconf"
        assert "set_static6" not in ifutil_calls
        assert "set_dhcp6" not in ifutil_calls

    def test_all_fields_empty_restores_dhcp6(
        self, tc, ifutil_calls, not_in_ssh
    ):
        console = tc(forms=[("ok", ["", " ", ""])])

        console._ifconf_staticipv6()

        assert ifutil_calls["set_dhcp6"] == [("eth0",)]
        assert "set_static6" not in ifutil_calls
        assert [c[0] for c in console.console.calls] == ["form"]

    def test_dhcp6_error_is_shown(self, tc, ifutil_calls, not_in_ssh):
        ifutil_calls["results"]["set_dhcp6"] = "Error obtaining IPv6 address"
        console = tc(forms=[("ok", ["", "", ""])])

        console._ifconf_staticipv6()

        assert console.console.calls[-1] == (
            "msgbox", "Error", "Error obtaining IPv6 address",
        )

    def test_ssh_session_asks_before_applying(
        self, tc, ifutil_calls, monkeypatch
    ):
        monkeypatch.setenv("SSH_CONNECTION", "2001:db8::2 22 2001:db8::1 22")
        console = tc(forms=[("ok", [ADDR, "", ""])], yesno=["ok"])

        console._ifconf_staticipv6()

        assert console.console.calls[1][0] == "yesno"
        assert "ssh session" in console.console.calls[1][1]
        assert ifutil_calls["set_static6"] == [("eth0", ADDR, "", [])]

    def test_ssh_warning_declined_applies_nothing(
        self, tc, ifutil_calls, monkeypatch
    ):
        monkeypatch.setenv("SSH_CONNECTION", "2001:db8::2 22 2001:db8::1 22")
        console = tc(forms=[("ok", [ADDR, "", ""])], yesno=["cancel"])

        assert console._ifconf_staticipv6() == "ifconf"
        assert "set_static6" not in ifutil_calls

    def test_empty_prefill_gives_address_gateway_and_one_nameserver(
        self, tc, ifutil_calls, confconsole, monkeypatch, not_in_ssh
    ):
        monkeypatch.setattr(
            confconsole.ifutil, "get_ip6conf", lambda ifname: (None, None, [])
        )
        console = tc(forms=[("cancel", [])])

        console._ifconf_staticipv6()

        assert [f[3] for f in console.console.calls[0][2]] == ["", "", ""]


class TestNetworkMenuShowsIPv6:
    def test_ipv6_only_interface_is_listed_with_its_address(
        self, tc, net_stubs
    ):
        net_stubs["ipv6conf"] = ("2001:db8:1::10", "64")
        net_stubs["methods"]["inet6"] = "static"

        assert tc()._get_netmenu() == [("eth0", "2001:db8:1::10 (static) [*]")]

    def test_ipv4_still_comes_first_when_present(self, tc, net_stubs):
        net_stubs["ipconf"] = ("192.0.2.10", "255.255.255.0", "192.0.2.1", [])
        net_stubs["ipv6conf"] = ("2001:db8:1::10", "64")
        net_stubs["methods"] = {"inet": "dhcp", "inet6": "static"}

        assert tc()._get_netmenu() == [("eth0", "192.0.2.10 (dhcp) [*]")]

    def test_no_address_at_all_is_not_configured(self, tc, net_stubs):
        assert tc()._get_netmenu() == [("eth0", "not configured")]

    def test_ifconf_menu_has_static_ipv6_entry(self, tc, net_stubs):
        entries = [item[0] for item in tc()._get_ifconfmenu("eth0")]

        assert entries == ["DHCP", "StaticIP", "StaticIPv6"]

    def test_default_entry_offered_for_ipv6_only_secondary_nic(
        self, tc, net_stubs
    ):
        net_stubs["ifnames"] = ["eth0", "eth1"]
        net_stubs["ipv6conf"] = ("2001:db8:2::10", "64")

        entries = [item[0] for item in tc()._get_ifconfmenu("eth1")]

        assert entries == ["DHCP", "StaticIP", "StaticIPv6", "Default"]

    def test_default_entry_hidden_without_any_address(self, tc, net_stubs):
        net_stubs["ifnames"] = ["eth0", "eth1"]

        entries = [item[0] for item in tc()._get_ifconfmenu("eth1")]

        assert "Default" not in entries


class TestInterfaceText:
    def test_ipv6_only_interface_is_described(self, tc, net_stubs):
        net_stubs["ipconf"] = (None, None, None, [NS])
        net_stubs["ipv6conf"] = ("2001:db8:1::10", "64")
        net_stubs["methods"]["inet6"] = "static"

        text = tc()._get_ifconftext("eth0")

        assert text == (
            "IPv6 Address:    2001:db8:1::10/64\n"
            f"Name Server(s):  {NS}\n"
            "\n"
            "IPv6 configuration method: static\n"
        )

    def test_dual_stack_lists_ipv4_block_then_ipv6(self, tc, net_stubs):
        net_stubs["ipconf"] = (
            "192.0.2.10", "255.255.255.0", "192.0.2.1", ["192.0.2.53"],
        )
        net_stubs["ipv6conf"] = ("2001:db8:1::10", "64")
        net_stubs["methods"] = {"inet": "static", "inet6": "dhcp"}
        net_stubs["ifnames"] = ["eth0", "eth1"]

        text = tc()._get_ifconftext("eth0")

        assert text == (
            "IP Address:      192.0.2.10\n"
            "Netmask:         255.255.255.0\n"
            "Default Gateway: 192.0.2.1\n"
            "Name Server(s):  192.0.2.53\n"
            "IPv6 Address:    2001:db8:1::10/64\n"
            "\n"
            "Networking configuration method: static\n"
            "IPv6 configuration method: dhcp\n"
            "Is this adapter's IP address displayed in Usage: yes\n"
        )

    def test_not_configured_without_any_address(self, tc, net_stubs):
        assert tc()._get_ifconftext("eth0") == (
            "Network adapter is not configured\n"
        )


class TestGetIp6conf:
    """ifutil.get_ip6conf, the data source of the form (measured file)."""

    @pytest.fixture
    def scratch(self, ifutil, interfaces_file, hostname, monkeypatch):
        def _point(text, live=("2001:db8:1::10", "64")):
            path = interfaces_file(text)
            monkeypatch.setattr(ifutil.NetworkInterfaces, "CONF_FILE", path)
            monkeypatch.setattr(ifutil, "get_ipv6conf", lambda ifname: live)
            return path

        return _point

    def test_reads_live_address_and_inet6_stanza(self, ifutil, scratch):
        scratch(INET6_ONLY)

        assert ifutil.get_ip6conf("eth0") == (
            ADDR, "2001:db8:1::1", ["2001:db8::53"],
        )

    def test_nameservers_fall_back_to_ipv6_entries_of_resolver(
        self, ifutil, scratch, monkeypatch
    ):
        scratch(UNCONFIGURED, live=(None, None))
        monkeypatch.setattr(
            ifutil, "get_nameservers", lambda ifname: ["192.0.2.53", NS]
        )

        assert ifutil.get_ip6conf("eth0") == (None, None, [NS])

    def test_non_ip_resolver_entry_gives_no_nameservers(
        self, ifutil, scratch, monkeypatch
    ):
        scratch(STATIC_V4)
        monkeypatch.setattr(
            ifutil.NetworkInterfaces,
            "get_if_conf",
            lambda self, ifname, key, inet_family="inet": None,
        )
        monkeypatch.setattr(
            ifutil, "get_nameservers", lambda ifname: ["dns.example"]
        )

        assert ifutil.get_ip6conf("eth0") == (ADDR, None, [])
