"""ifutil.py pure functions: stanza parsing and rendering.

These are the functions the static IPv6 writer (plan 04, section 3.2)
builds on. No file, process or network is touched.
"""

import pytest

from conftest import STUB_HOSTNAME

DATA_LINES = [
    "auto eth0",
    "iface eth0 inet dhcp",
    "    hostname core",
    "iface eth0 inet6 static",
    "    address 2001:db8:1::10",
    "    netmask 64",
    "    gateway 2001:db8:1::1",
]


class TestPreprocessInterfaceConfig:
    def test_keeps_header_lines_and_reindents_post_up(self, ifutil, hostname):
        config = (
            "allow-hotplug eth0\n"
            "iface eth0 inet dhcp\n"
            "  post-up /usr/local/bin/announce\n"
            "wpa-conf /etc/wpa.conf\n"
        )

        lines = ifutil._preprocess_interface_config(config)

        assert lines == [
            "allow-hotplug eth0",
            "iface eth0 inet dhcp",
            "    post-up /usr/local/bin/announce",
            "wpa-conf /etc/wpa.conf",
        ]

    def test_replaces_hostname_line_with_current_hostname(
        self, ifutil, hostname
    ):
        config = "auto eth0\niface eth0 inet dhcp\n    hostname old-name\n"

        lines = ifutil._preprocess_interface_config(config)

        assert lines == [
            "auto eth0",
            "iface eth0 inet dhcp",
            f"    hostname {STUB_HOSTNAME}",
        ]

    def test_drops_hostname_line_when_no_hostname_is_known(
        self, ifutil, monkeypatch
    ):
        monkeypatch.setattr(ifutil, "get_hostname", lambda: "")
        config = "auto eth0\niface eth0 inet dhcp\n    hostname old-name\n"

        lines = ifutil._preprocess_interface_config(config)

        assert lines == ["auto eth0", "iface eth0 inet dhcp"]

    def test_drops_static_options(self, ifutil, hostname):
        config = (
            "auto eth0\n"
            "iface eth0 inet6 static\n"
            "    address 2001:db8:1::10\n"
            "    netmask 64\n"
            "    gateway 2001:db8:1::1\n"
            "    dns-nameservers 2001:db8::53\n"
            "    hostname core\n"
        )

        lines = ifutil._preprocess_interface_config(config)

        assert lines == [
            "auto eth0",
            "iface eth0 inet6 static",
            f"    hostname {STUB_HOSTNAME}",
        ]

    def test_appends_hostname_to_a_bare_two_line_stanza(
        self, ifutil, hostname
    ):
        lines = ifutil._preprocess_interface_config(
            "auto eth0\niface eth0 inet dhcp"
        )

        assert lines[-1] == f"    hostname {STUB_HOSTNAME}"
        assert len(lines) == 3

    def test_rejects_unknown_line(self, ifutil, hostname):
        with pytest.raises(ifutil.BadIfConfigError, match="Unexpected"):
            ifutil._preprocess_interface_config(
                "auto eth0\niface eth0 inet dhcp\n    mtu 1400\n"
            )


class TestListToData:
    def test_splits_stanzas_per_family(self, ifutil):
        data = ifutil._list_to_data(DATA_LINES)

        assert data == [
            "auto eth0",
            {
                "iface": "eth0",
                "family": "inet",
                "method": "dhcp",
                "options": [["hostname", "core"]],
            },
            {
                "iface": "eth0",
                "family": "inet6",
                "method": "static",
                "options": [
                    ["address", "2001:db8:1::10"],
                    ["netmask", "64"],
                    ["gateway", "2001:db8:1::1"],
                ],
            },
        ]

    def test_keeps_top_level_lines_that_are_not_iface(self, ifutil):
        data = ifutil._list_to_data(["# comment", "auto eth0", ""])

        assert data == ["# comment", "auto eth0", ""]

    def test_keeps_indented_line_with_no_open_stanza(self, ifutil):
        data = ifutil._list_to_data(["    orphan option", "auto eth0"])

        assert data == ["    orphan option", "auto eth0"]

    def test_tab_indent_counts_as_option(self, ifutil):
        data = ifutil._list_to_data(["iface eth0 inet dhcp", "\thostname x"])

        assert data[0]["options"] == [["hostname", "x"]]

    def test_rejects_malformed_iface_header(self, ifutil):
        with pytest.raises(ifutil.BadIfConfigError, match="Invalid iface"):
            ifutil._list_to_data(["iface eth0 inet"])


class TestDataToList:
    def test_round_trip_normalises_indent_to_four_spaces(self, ifutil):
        lines = ifutil._data_to_list(ifutil._list_to_data(DATA_LINES))

        assert lines == DATA_LINES

    def test_renders_string_items_verbatim(self, ifutil):
        lines = ["auto eth0", "# x"]

        assert ifutil._data_to_list(lines) == lines


class TestGetRawOpts:
    def test_returns_options_of_the_requested_family(self, ifutil):
        assert ifutil._get_raw_opts(DATA_LINES, "inet6") == [
            ["address", "2001:db8:1::10"],
            ["netmask", "64"],
            ["gateway", "2001:db8:1::1"],
        ]

    def test_defaults_to_inet(self, ifutil):
        assert ifutil._get_raw_opts(DATA_LINES) == [["hostname", "core"]]

    def test_returns_empty_list_when_family_is_absent(self, ifutil):
        assert ifutil._get_raw_opts(["auto eth0"], "inet6") == []


class TestMergeIfaceOptions:
    def test_new_values_first_then_untouched_current(self, ifutil, hostname):
        current = [["hostname", "core"], ["post-up", "/bin/true"]]
        new = {"address": "2001:db8:1::10", "netmask": "64"}

        merged = ifutil._merge_iface_options(current, new)

        assert merged == [
            ["hostname", "core"],
            ["address", "2001:db8:1::10"],
            ["netmask", "64"],
            ["post-up", "/bin/true"],
        ]

    def test_new_value_overrides_existing_key(self, ifutil, hostname):
        current = [["address", "2001:db8:1::10"], ["netmask", "64"]]

        merged = ifutil._merge_iface_options(
            current, {"address": "2001:db8:1::20"}
        )

        assert merged == [
            ["hostname", STUB_HOSTNAME],
            ["address", "2001:db8:1::20"],
            ["netmask", "64"],
        ]

    def test_list_value_is_split_into_items(self, ifutil, hostname):
        merged = ifutil._merge_iface_options(
            [], {"dns-nameservers": ["2001:db8::53", "2001:db8::54"]}
        )

        assert merged[1] == ["dns-nameservers", "2001:db8::53", "2001:db8::54"]

    def test_string_value_with_spaces_is_split(self, ifutil, hostname):
        merged = ifutil._merge_iface_options(
            [], {"dns-nameservers": "2001:db8::53 2001:db8::54"}
        )

        assert merged[1] == ["dns-nameservers", "2001:db8::53", "2001:db8::54"]

    def test_none_values_are_ignored(self, ifutil, hostname):
        merged = ifutil._merge_iface_options([], {"gateway": None})

        assert merged == [["hostname", STUB_HOSTNAME]]

    def test_new_hostname_goes_first_and_current_line_is_retained(
        self, ifutil, hostname
    ):
        # Current upstream behaviour: the hostname key is popped from the
        # new options before the override check, so the existing hostname
        # line is kept after the new one instead of being replaced.
        merged = ifutil._merge_iface_options(
            [["hostname", "old"]], {"hostname": "new"}
        )

        assert merged == [["hostname", "new"], ["hostname", "old"]]

    def test_hostname_is_generated_when_missing_everywhere(
        self, ifutil, hostname
    ):
        merged = ifutil._merge_iface_options([["post-up", "/bin/true"]], {})

        assert merged == [
            ["hostname", STUB_HOSTNAME],
            ["post-up", "/bin/true"],
        ]


class TestStripStaticOpts:
    def test_removes_static_keys_and_keeps_hostname_first(
        self, ifutil, hostname
    ):
        options = [
            ["address", "2001:db8:1::10"],
            ["post-up", "/bin/true"],
            ["netmask", "64"],
            ["hostname", "kept"],
            ["gateway", "2001:db8:1::1"],
            ["dns-nameservers", "2001:db8::53"],
        ]

        assert ifutil._strip_static_opts(options) == [
            ["hostname", "kept"],
            ["post-up", "/bin/true"],
        ]

    def test_adds_hostname_when_missing(self, ifutil, hostname):
        assert ifutil._strip_static_opts([]) == [["hostname", STUB_HOSTNAME]]


class TestValidIp:
    @pytest.mark.parametrize("ip", ["2001:db8::1", "::1", "192.0.2.1"])
    def test_accepts_plain_addresses_of_both_families(self, ifutil, ip):
        assert ifutil._valid_ip(ip) == ip

    def test_rejects_cidr(self, ifutil):
        with pytest.raises(ifutil.InvalidIPError, match="plain IP"):
            ifutil._valid_ip("2001:db8::1/64")

    def test_rejects_garbage(self, ifutil):
        with pytest.raises(ifutil.InvalidIPError):
            ifutil._valid_ip("2001:db8::zz")


class TestIPv4:
    def test_parse_and_str(self, ifutil):
        ip = ifutil.IPv4.parse(" 192.0.2.10 ")

        assert (ip.p0, ip.p1, ip.p2, ip.p3) == (192, 0, 2, 10)
        assert str(ip) == "192.0.2.10"

    def test_rejects_non_ipv4(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv4Error, match="not a valid IPv4"):
            ifutil.IPv4.parse("2001:db8::1")

    def test_rejects_junk_after_octets(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv4Error, match="junk"):
            ifutil.IPv4.parse("192.0.2.10/24")

    @pytest.mark.parametrize(
        "value", ["256.0.2.10", "192.256.2.10", "192.0.256.10", "192.0.2.256"]
    )
    def test_rejects_octet_out_of_range(self, ifutil, value):
        with pytest.raises(ifutil.InvalidIPv4Error, match="0-255"):
            ifutil.IPv4.parse(value)

    def test_is_an_invalid_ip_error(self, ifutil):
        assert issubclass(ifutil.InvalidIPv4Error, ifutil.InvalidIPError)
        assert issubclass(ifutil.InvalidIPv6Error, ifutil.InvalidIPError)
