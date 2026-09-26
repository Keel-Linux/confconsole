"""ifutil.NetworkInterfaces against a scratch interfaces file.

`read()` and `write()` take a `conf_file` argument, so nothing here goes
near /etc/network/interfaces. Where the class attribute CONF_FILE is used
implicitly it is pointed at the scratch file.
"""

import json

import pytest

from conftest import (
    INET6_ONLY,
    MANUAL_HEADERLESS,
    STATIC_V4,
    STUB_HOSTNAME,
    UNCONFIGURED,
)


@pytest.fixture
def loaded(ifutil, interfaces_file, hostname):
    """Return a NetworkInterfaces loaded from the given text."""

    def _load(text):
        interfaces = ifutil.NetworkInterfaces()
        interfaces.read(interfaces_file(text))
        return interfaces

    return _load


class TestRead:
    def test_groups_lines_per_interface_and_detects_header(self, loaded):
        interfaces = loaded(UNCONFIGURED)

        assert interfaces.unconfigured is True
        assert list(interfaces.conf) == ["lo", "eth0"]
        assert interfaces.conf["eth0"] == [
            "auto eth0",
            "iface eth0 inet dhcp",
            "    hostname core",
            "iface eth0 inet6 dhcp",
            "    hostname core",
        ]

    def test_missing_header_marks_file_as_manually_configured(self, loaded):
        interfaces = loaded(MANUAL_HEADERLESS)

        assert interfaces.unconfigured is False
        assert interfaces.conf == {
            "eth0": ["auto eth0", "iface eth0 inet manual"]
        }

    def test_allow_hotplug_starts_an_interface(self, loaded):
        interfaces = loaded("allow-hotplug eth1\niface eth1 inet6 auto\n")

        assert interfaces.conf == {
            "eth1": ["allow-hotplug eth1", "iface eth1 inet6 auto"]
        }

    def test_lines_before_any_interface_are_ignored(self, loaded):
        interfaces = loaded("iface eth9 inet dhcp\nauto eth0\n")

        assert interfaces.conf == {"eth0": ["auto eth0"]}

    def test_reads_class_conf_file_by_default(
        self, ifutil, interfaces_file, monkeypatch
    ):
        monkeypatch.setattr(
            ifutil.NetworkInterfaces,
            "CONF_FILE",
            interfaces_file(UNCONFIGURED),
        )

        interfaces = ifutil.NetworkInterfaces()
        interfaces.read()

        assert "eth0" in interfaces.conf


class TestWrite:
    def test_writes_header_and_one_block_per_interface(
        self, loaded, tmp_path
    ):
        interfaces = loaded(UNCONFIGURED)
        out = tmp_path / "out"

        interfaces.write(str(out))

        assert out.read_text() == (
            "# UNCONFIGURED INTERFACES\n"
            "\n"
            "\n"
            "auto lo\n"
            "iface lo inet loopback\n"
            "\n"
            "auto eth0\n"
            "iface eth0 inet dhcp\n"
            "    hostname core\n"
            "iface eth0 inet6 dhcp\n"
            "    hostname core\n"
        )

    def test_round_trip_is_stable(self, ifutil, loaded, tmp_path):
        first = loaded(STATIC_V4)
        out = tmp_path / "out"
        first.write(str(out))

        second = ifutil.NetworkInterfaces()
        second.read(str(out))

        assert second.conf == first.conf

    def test_refuses_to_write_a_manually_configured_file(
        self, ifutil, loaded, tmp_path
    ):
        interfaces = loaded(MANUAL_HEADERLESS)
        out = tmp_path / "out"

        with pytest.raises(ifutil.ManuallyConfiguredError, match="header"):
            interfaces.write(str(out))

        assert not out.exists()

    def test_writes_class_conf_file_by_default(
        self, ifutil, loaded, tmp_path, monkeypatch
    ):
        out = tmp_path / "default-target"
        monkeypatch.setattr(ifutil.NetworkInterfaces, "CONF_FILE", str(out))
        interfaces = loaded(UNCONFIGURED)

        interfaces.write()

        assert out.read_text().startswith("# UNCONFIGURED INTERFACES\n")


class TestDuplicate:
    def test_copy_is_independent(self, loaded):
        original = loaded(UNCONFIGURED)

        copy = original.duplicate()
        copy.conf["eth0"].append("    mtu 1400")
        copy.unconfigured = False

        assert "    mtu 1400" not in original.conf["eth0"]
        assert original.unconfigured is True
        assert copy.conf["lo"] == original.conf["lo"]


class TestOptionQueries:
    def test_iface_opts_of_the_inet_stanza(self, loaded):
        interfaces = loaded(STATIC_V4)

        assert interfaces.get_iface_opts("eth0") == [
            "post-up /usr/local/bin/announce"
        ]

    def test_iface_opts_of_the_inet6_stanza_are_separate(self, loaded):
        interfaces = loaded(STATIC_V4)

        assert interfaces.get_iface_opts("eth0", "inet6") == []

    def test_bridge_opts(self, loaded):
        interfaces = loaded(
            "# UNCONFIGURED INTERFACES\n"
            "auto br0\n"
            "iface br0 inet6 static\n"
            "    address 2001:db8:1::10\n"
            "    netmask 64\n"
            "    bridge_ports eth0 eth1\n"
            "    bridge_stp off\n"
        )

        assert interfaces.get_bridge_opts("br0", "inet6") == [
            "bridge_ports eth0 eth1",
            "bridge_stp off",
        ]

    def test_unknown_interface_raises(self, ifutil, loaded):
        interfaces = loaded(UNCONFIGURED)

        with pytest.raises(ifutil.InterfaceNotFoundError, match="eth7"):
            interfaces.get_iface_opts("eth7")

    def test_get_method_per_family(self, loaded):
        interfaces = loaded(STATIC_V4)

        assert interfaces.get_method("eth0") == "static"
        assert interfaces.get_method("eth0", "inet6") == "static"
        assert interfaces.get_method("lo") == ""
        assert interfaces.get_method("eth0", "inet9") == ""

    def test_get_if_conf_returns_values_after_the_key(self, loaded):
        interfaces = loaded(STATIC_V4)

        assert interfaces.get_if_conf("eth0", "dns-nameservers") == [
            "2001:db8::53",
            "192.0.2.53",
        ]
        assert interfaces.get_if_conf("eth0", "address", "inet6") == [
            "2001:db8:1::10"
        ]
        assert interfaces.get_if_conf("eth0", "mtu") is None
        assert interfaces.get_if_conf("eth9", "address") is None

    def test_address_netmask_and_nameserver_helpers(self, loaded):
        static = loaded(STATIC_V4)
        dhcp = loaded(UNCONFIGURED)

        assert static.get_address("eth0") == "192.0.2.10"
        assert static.get_netmask("eth0") == "255.255.255.0"
        assert static.get_nameservers("eth0") == ["2001:db8::53", "192.0.2.53"]
        assert dhcp.get_address("eth0") is None
        assert dhcp.get_netmask("eth0") is None
        assert dhcp.get_nameservers("eth0") == []

    def test_repr_is_json_of_conf(self, loaded):
        interfaces = loaded(MANUAL_HEADERLESS)

        assert json.loads(repr(interfaces)) == interfaces.conf


class TestGenDefaultIfConfig:
    def test_both_families_by_default(self, ifutil, hostname):
        interfaces = ifutil.NetworkInterfaces()
        interfaces.conf = {}

        interfaces.gen_default_if_config("eth0")

        assert interfaces.conf["eth0"] == [
            "auto eth0",
            "iface eth0 inet dhcp",
            f"    hostname {STUB_HOSTNAME}",
            "iface eth0 inet6 dhcp",
            f"    hostname {STUB_HOSTNAME}",
        ]

    @pytest.mark.parametrize(
        "family, expected",
        [("inet", "iface eth0 inet dhcp"), ("inet6", "iface eth0 inet6 dhcp")],
    )
    def test_single_family(self, ifutil, hostname, family, expected):
        interfaces = ifutil.NetworkInterfaces()
        interfaces.conf = {}

        interfaces.gen_default_if_config("eth0", family)

        assert interfaces.conf["eth0"] == [
            "auto eth0",
            expected,
            f"    hostname {STUB_HOSTNAME}",
        ]

    def test_non_ethernet_name_raises(self, ifutil, hostname):
        interfaces = ifutil.NetworkInterfaces()
        interfaces.conf = {}

        with pytest.raises(ifutil.InterfaceNotFoundError, match="wlan0"):
            interfaces.gen_default_if_config("wlan0")


class TestSetDhcp:
    def test_unknown_interface_gets_dual_stack_dhcp(self, loaded):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_dhcp("eth1")

        assert interfaces.conf["eth1"] == [
            "auto eth1",
            "iface eth1 inet dhcp",
            f"    hostname {STUB_HOSTNAME}",
            "iface eth1 inet6 dhcp",
            f"    hostname {STUB_HOSTNAME}",
        ]

    def test_static_inet_becomes_dhcp_and_inet6_is_untouched(self, loaded):
        interfaces = loaded(STATIC_V4)

        interfaces.set_dhcp("eth0")

        assert interfaces.conf["eth0"] == [
            "auto eth0",
            "iface eth0 inet dhcp",
            "    hostname core",
            "    post-up /usr/local/bin/announce",
            "iface eth0 inet6 static",
            "    address 2001:db8:1::10",
            "    netmask 64",
            "    gateway 2001:db8:1::1",
        ]


    def test_interface_without_inet_stanza_is_left_unchanged(self, loaded):
        interfaces = loaded(INET6_ONLY)
        before = list(interfaces.conf["eth0"])

        interfaces.set_dhcp("eth0")

        assert interfaces.conf["eth0"] == before


class TestSetManual:
    def test_unknown_interface_is_generated_first(self, loaded):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_manual("eth1")

        assert interfaces.conf["eth1"] == [
            "auto eth1",
            "iface eth1 inet manual",
            f"    hostname {STUB_HOSTNAME}",
            "iface eth1 inet6 dhcp",
            f"    hostname {STUB_HOSTNAME}",
        ]

    def test_static_inet_becomes_manual_without_static_options(self, loaded):
        interfaces = loaded(STATIC_V4)

        interfaces.set_manual("eth0")

        assert interfaces.conf["eth0"][1:4] == [
            "iface eth0 inet manual",
            "    hostname core",
            "    post-up /usr/local/bin/announce",
        ]
        assert "iface eth0 inet6 static" in interfaces.conf["eth0"]


    def test_interface_without_inet_stanza_is_left_unchanged(self, loaded):
        interfaces = loaded(INET6_ONLY)
        before = list(interfaces.conf["eth0"])

        interfaces.set_manual("eth0")

        assert interfaces.conf["eth0"] == before


class TestSetStatic:
    def test_full_static_config_on_a_dhcp_interface(self, loaded):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_static(
            "eth0",
            "192.0.2.10",
            "255.255.255.0",
            "192.0.2.1",
            ["2001:db8::53", "192.0.2.53"],
        )

        assert interfaces.conf["eth0"] == [
            "auto eth0",
            "iface eth0 inet static",
            "    hostname core",
            "    address 192.0.2.10",
            "    netmask 255.255.255.0",
            "    gateway 192.0.2.1",
            "    dns-nameservers 2001:db8::53 192.0.2.53",
            "iface eth0 inet6 dhcp",
            "    hostname core",
        ]

    def test_omitted_gateway_and_nameservers_are_removed(self, loaded):
        interfaces = loaded(STATIC_V4)

        interfaces.set_static("eth0", "192.0.2.20", "255.255.255.0")

        inet = ifutil_stanza(interfaces, "inet")
        assert inet["method"] == "static"
        assert inet["options"] == [
            ["hostname", "core"],
            ["address", "192.0.2.20"],
            ["netmask", "255.255.255.0"],
            ["post-up", "/usr/local/bin/announce"],
        ]

    def test_inet6_stanza_is_left_alone(self, loaded):
        interfaces = loaded(STATIC_V4)

        interfaces.set_static("eth0", "192.0.2.20", "255.255.255.0")

        assert ifutil_stanza(interfaces, "inet6")["options"] == [
            ["address", "2001:db8:1::10"],
            ["netmask", "64"],
            ["gateway", "2001:db8:1::1"],
        ]

    def test_unknown_interface_is_generated_then_configured(self, loaded):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_static("eth2", "192.0.2.30", "255.255.255.0")

        assert interfaces.conf["eth2"][:4] == [
            "auto eth2",
            "iface eth2 inet static",
            f"    hostname {STUB_HOSTNAME}",
            "    address 192.0.2.30",
        ]
        assert "iface eth2 inet6 dhcp" in interfaces.conf["eth2"]

    def test_invalid_nameserver_raises_before_changing_anything(
        self, ifutil, loaded
    ):
        interfaces = loaded(UNCONFIGURED)
        before = list(interfaces.conf["eth0"])

        with pytest.raises(ifutil.InvalidIPError):
            interfaces.set_static(
                "eth0", "192.0.2.10", "255.255.255.0", None, ["2001:db8::/64"]
            )

        assert interfaces.conf["eth0"] == before


def ifutil_stanza(interfaces, family):
    import ifutil

    for stanza in ifutil._list_to_data(interfaces.conf["eth0"]):
        if isinstance(stanza, dict) and stanza["family"] == family:
            return stanza
    raise AssertionError(f"no {family} stanza")
