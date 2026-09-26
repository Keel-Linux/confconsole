"""The static IPv6 writer: validation, the inet6 stanza and the wrappers.

Same approach as the other ifutil tests: NetworkInterfaces works on a
scratch file, subprocess, sleep and `ip` output are stubbed. The inet
(IPv4) stanza must come out of every rewrite untouched.
"""

import subprocess

import pytest

from conftest import INET6_ONLY, STATIC_V4, STUB_HOSTNAME, UNCONFIGURED

INET_ONLY = """# UNCONFIGURED INTERFACES

auto eth0
iface eth0 inet static
    address 192.0.2.10
    netmask 255.255.255.0
    hostname core
"""

ADDR = "2001:db8:1::10/64"
GW = "2001:db8:1::1"


def stanzas(ifutil, interfaces, ifname="eth0"):
    """The iface stanzas of an interface, keyed by family."""
    return {
        block["family"]: block
        for block in ifutil._list_to_data(interfaces.conf[ifname])
        if isinstance(block, dict)
    }


class TestValidIp6:
    def test_accepts_and_compresses_unicast(self, ifutil):
        assert ifutil._valid_ip6("2001:DB8:0:0::1") == "2001:db8::1"

    def test_accepts_link_local_for_a_gateway(self, ifutil):
        assert ifutil._valid_ip6("fe80::1", "IPv6 gateway") == "fe80::1"

    def test_refuses_prefix(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv6Error, match="plain address"):
            ifutil._valid_ip6("2001:db8::1/64")

    def test_refuses_garbage(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv6Error, match="not a valid"):
            ifutil._valid_ip6("2001:db8::zz")

    def test_refuses_ipv4_with_a_clear_message(self, ifutil):
        with pytest.raises(
            ifutil.InvalidIPv6Error, match="must be IPv6, not IPv4"
        ):
            ifutil._valid_ip6("192.0.2.1", "IPv6 gateway")

    @pytest.mark.parametrize("ip", ["ff02::1", "::1", "::"])
    def test_refuses_non_unicast(self, ifutil, ip):
        with pytest.raises(ifutil.InvalidIPv6Error, match="unicast"):
            ifutil._valid_ip6(ip)


class TestValidIp6Prefix:
    def test_normalises_address_and_prefix(self, ifutil):
        assert ifutil._valid_ip6_prefix("2001:DB8:1:0::10/64") == ADDR

    def test_requires_prefix_length(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv6Error, match="prefix length"):
            ifutil._valid_ip6_prefix("2001:db8:1::10")

    @pytest.mark.parametrize("plen", ["129", "abc", ""])
    def test_refuses_bad_prefix_length(self, ifutil, plen):
        with pytest.raises(ifutil.InvalidIPv6Error, match="0-128"):
            ifutil._valid_ip6_prefix(f"2001:db8:1::10/{plen}")

    def test_refuses_ipv4_cidr(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv6Error, match="not IPv4"):
            ifutil._valid_ip6_prefix("192.0.2.10/24")

    def test_refuses_link_local(self, ifutil):
        with pytest.raises(ifutil.InvalidIPv6Error, match="link-local"):
            ifutil._valid_ip6_prefix("fe80::10/64")


class TestIp6Nameservers:
    def test_keeps_ipv6_and_drops_ipv4(self, ifutil):
        assert ifutil._ip6_nameservers(
            ["2001:db8::53", "192.0.2.53", "2001:db8::54"]
        ) == ["2001:db8::53", "2001:db8::54"]

    def test_invalid_entry_raises(self, ifutil):
        with pytest.raises(ifutil.InvalidIPError):
            ifutil._ip6_nameservers(["2001:db8::53", "dns.example"])

    def test_empty_list(self, ifutil):
        assert ifutil._ip6_nameservers([]) == []


class TestNetworkInterfacesSetStatic6:
    @pytest.fixture
    def loaded(self, ifutil, interfaces_file, hostname):
        def _load(text):
            interfaces = ifutil.NetworkInterfaces()
            interfaces.read(interfaces_file(text))
            return interfaces

        return _load

    def test_replaces_dhcp_stanza_and_keeps_inet(self, ifutil, loaded):
        interfaces = loaded(UNCONFIGURED)
        inet_before = stanzas(ifutil, interfaces)["inet"]

        interfaces.set_static6(
            "eth0", ADDR, GW, ["2001:db8::53", "192.0.2.53"]
        )

        assert interfaces.conf["eth0"] == [
            "auto eth0",
            "iface eth0 inet dhcp",
            "    hostname core",
            "iface eth0 inet6 static",
            "    hostname core",
            "    address 2001:db8:1::10/64",
            "    gateway 2001:db8:1::1",
            "    dns-nameservers 2001:db8::53",
        ]
        assert stanzas(ifutil, interfaces)["inet"] == inet_before

    def test_replaces_existing_static_options(self, ifutil, loaded):
        interfaces = loaded(STATIC_V4)

        interfaces.set_static6("eth0", "2001:db8:2::20/48")

        inet6 = stanzas(ifutil, interfaces)["inet6"]
        assert inet6["method"] == "static"
        assert inet6["options"] == [
            ["hostname", STUB_HOSTNAME],
            ["address", "2001:db8:2::20/48"],
        ]
        assert stanzas(ifutil, interfaces)["inet"]["options"] == [
            ["address", "192.0.2.10"],
            ["netmask", "255.255.255.0"],
            ["gateway", "192.0.2.1"],
            ["dns-nameservers", "2001:db8::53", "192.0.2.53"],
            ["hostname", "core"],
            ["post-up", "/usr/local/bin/announce"],
        ]

    def test_gateway_is_optional(self, ifutil, loaded):
        interfaces = loaded(INET6_ONLY)

        interfaces.set_static6("eth0", ADDR, None, ["2001:db8::53"])

        keys = [o[0] for o in stanzas(ifutil, interfaces)["inet6"]["options"]]
        assert keys == ["hostname", "address", "dns-nameservers"]

    def test_only_ipv4_nameservers_writes_no_dns_line(self, ifutil, loaded):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_static6("eth0", ADDR, GW, ["192.0.2.53"])

        keys = [o[0] for o in stanzas(ifutil, interfaces)["inet6"]["options"]]
        assert keys == ["hostname", "address", "gateway"]

    def test_appends_inet6_stanza_when_interface_has_only_inet(
        self, ifutil, loaded
    ):
        interfaces = loaded(INET_ONLY)

        interfaces.set_static6("eth0", ADDR, GW)

        assert interfaces.conf["eth0"] == [
            "auto eth0",
            "iface eth0 inet static",
            "    address 192.0.2.10",
            "    netmask 255.255.255.0",
            "    hostname core",
            "iface eth0 inet6 static",
            "    hostname core",
            "    address 2001:db8:1::10/64",
            "    gateway 2001:db8:1::1",
        ]

    def test_unknown_interface_gets_default_inet_dhcp_first(
        self, ifutil, loaded
    ):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_static6("eth1", ADDR)

        assert interfaces.conf["eth1"] == [
            "auto eth1",
            "iface eth1 inet dhcp",
            "    hostname core",
            "iface eth1 inet6 static",
            "    hostname core",
            "    address 2001:db8:1::10/64",
        ]

    def test_unknown_non_ethernet_interface_raises(self, ifutil, loaded):
        with pytest.raises(ifutil.InterfaceNotFoundError):
            loaded(UNCONFIGURED).set_static6("wlan0", ADDR)

    @pytest.mark.parametrize(
        "args, match",
        [
            (("192.0.2.10/24", None, None), "not IPv4"),
            ((ADDR, "192.0.2.1", None), "IPv6 gateway must be IPv6"),
            ((ADDR, "2001:db8:1::1/64", None), "plain address"),
            ((ADDR, None, ["nope"]), "does not appear to be"),
        ],
    )
    def test_invalid_input_changes_nothing(self, ifutil, loaded, args, match):
        interfaces = loaded(UNCONFIGURED)
        before = list(interfaces.conf["eth0"])

        with pytest.raises(ifutil.InvalidIPError, match=match):
            interfaces.set_static6("eth0", *args)

        assert interfaces.conf["eth0"] == before

    def test_written_file_keeps_header_and_both_stanzas(
        self, ifutil, loaded, tmp_path
    ):
        interfaces = loaded(UNCONFIGURED)
        interfaces.set_static6("eth0", ADDR, GW, ["2001:db8::53"])
        out = tmp_path / "out"

        interfaces.write(str(out))

        text = out.read_text()
        assert text.startswith("# UNCONFIGURED INTERFACES\n\n")
        assert "iface eth0 inet dhcp\n" in text
        assert "iface eth0 inet6 static\n    hostname core\n" in text
        reread = ifutil.NetworkInterfaces()
        reread.read(str(out))
        assert reread.conf == interfaces.conf

    def test_headerless_file_is_still_refused(self, ifutil, loaded, tmp_path):
        interfaces = loaded("auto eth0\niface eth0 inet6 dhcp\n")
        interfaces.set_static6("eth0", ADDR)

        with pytest.raises(ifutil.ManuallyConfiguredError):
            interfaces.write(str(tmp_path / "out"))


class TestNetworkInterfacesSetDhcp6:
    @pytest.fixture
    def loaded(self, ifutil, interfaces_file, hostname):
        def _load(text):
            interfaces = ifutil.NetworkInterfaces()
            interfaces.read(interfaces_file(text))
            return interfaces

        return _load

    def test_strips_static_options_and_keeps_inet(self, ifutil, loaded):
        interfaces = loaded(STATIC_V4)
        inet_before = stanzas(ifutil, interfaces)["inet"]

        interfaces.set_dhcp6("eth0")

        inet6 = stanzas(ifutil, interfaces)["inet6"]
        assert inet6["method"] == "dhcp"
        assert inet6["options"] == [["hostname", STUB_HOSTNAME]]
        assert stanzas(ifutil, interfaces)["inet"] == inet_before

    def test_appends_inet6_dhcp_when_missing(self, ifutil, loaded):
        interfaces = loaded(INET_ONLY)

        interfaces.set_dhcp6("eth0")

        assert interfaces.conf["eth0"][-2:] == [
            "iface eth0 inet6 dhcp",
            "    hostname core",
        ]

    def test_unknown_interface_gets_default_config(self, ifutil, loaded):
        interfaces = loaded(UNCONFIGURED)

        interfaces.set_dhcp6("eth1")

        assert stanzas(ifutil, interfaces, "eth1")["inet6"]["method"] == "dhcp"
        assert stanzas(ifutil, interfaces, "eth1")["inet"]["method"] == "dhcp"


class FakeRun:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(
            args, self.returncode, stdout="", stderr=self.stderr
        )


def ip_output(*entries):
    """Render `ip -6 addr show scope global` lines for (addr/plen, flags)."""
    lines = ["2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP"]
    for addr_prefix, flags in entries:
        lines.append(f"    inet6 {addr_prefix} scope global {flags}")
        lines.append("       valid_lft forever preferred_lft forever")
    return "\n".join(lines) + "\n"


@pytest.fixture
def scratch_conf(ifutil, interfaces_file, hostname, monkeypatch):
    def _point(text):
        path = interfaces_file(text)
        monkeypatch.setattr(ifutil.NetworkInterfaces, "CONF_FILE", path)
        return path

    return _point


@pytest.fixture
def no_sleep(ifutil, monkeypatch):
    monkeypatch.setattr(ifutil, "sleep", lambda seconds: None)


@pytest.fixture
def ip_shows(ifutil, monkeypatch):
    """Make `ip -6 addr show` answer with the given entries."""

    def _set(*entries):
        monkeypatch.setattr(
            ifutil.subprocess,
            "check_output",
            lambda cmd, **kw: ip_output(*entries),
        )

    return _set


def parsed(ifutil, path):
    interfaces = ifutil.NetworkInterfaces()
    interfaces.read(path)
    return interfaces.conf


class TestGetIpv6confPreference:
    def test_static_beats_dynamic_beats_temporary(self, ifutil, ip_shows):
        ip_shows(
            ("2001:db8:1:0:aaaa::1/64", "temporary dynamic"),
            ("2001:db8:1:0:be24:11ff:feed:44bd/64", "dynamic mngtmpaddr"),
            ("2001:db8:1::10/64", ""),
        )

        assert ifutil.get_ipv6conf("eth0") == ("2001:db8:1::10", "64")

    def test_dynamic_preferred_over_temporary(self, ifutil, ip_shows):
        ip_shows(
            ("2001:db8:1:0:aaaa::1/64", "temporary dynamic"),
            ("2001:db8:1:0:be24:11ff:feed:44bd/64", "dynamic mngtmpaddr"),
        )

        assert ifutil.get_ipv6conf("eth0") == (
            "2001:db8:1:0:be24:11ff:feed:44bd",
            "64",
        )

    def test_list_returns_flags(self, ifutil, ip_shows):
        ip_shows(("2001:db8:1::10/64", "tentative"))

        assert ifutil._list_ipv6_global("eth0") == [
            ("2001:db8:1::10", "64", {"scope", "global", "tentative"})
        ]

    def test_list_is_empty_on_failure(self, ifutil, monkeypatch):
        def failing(cmd, **kwargs):
            raise FileNotFoundError("ip")

        monkeypatch.setattr(ifutil.subprocess, "check_output", failing)

        assert ifutil._list_ipv6_global("eth0") == []


class TestSetStatic6Wrapper:
    def test_happy_path_writes_config_and_checks_address(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, ip_shows
    ):
        path = scratch_conf(UNCONFIGURED)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)
        ip_shows(("2001:db8:1::10/64", "tentative"))

        result = ifutil.set_static6(
            "eth0", "2001:DB8:1::10/64", GW, ["2001:db8::53", "192.0.2.53"]
        )

        assert result is None
        assert run.calls == [
            ["/usr/sbin/ifdown", "--force", "eth0"],
            ["/usr/sbin/ifup", "--force", "eth0"],
        ]
        text = open(path).read()
        assert text.startswith("# UNCONFIGURED INTERFACES\n")
        assert "iface eth0 inet dhcp\n" in text
        assert "iface eth0 inet6 static\n" in text
        assert "    address 2001:db8:1::10/64\n" in text
        assert "    gateway 2001:db8:1::1\n" in text
        assert "    dns-nameservers 2001:db8::53\n" in text
        assert "netmask" not in text

    def test_gateway_and_nameservers_are_optional(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, ip_shows
    ):
        path = scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())
        ip_shows(("2001:db8:1::10/64", ""))

        assert ifutil.set_static6("eth0", ADDR) is None
        text = open(path).read()
        assert "gateway" not in text
        assert "dns-nameservers" not in text

    @pytest.mark.parametrize(
        "args, match",
        [
            (("192.0.2.10/24",), "not IPv4"),
            (("2001:db8:1::10",), "prefix length"),
            ((ADDR, "192.0.2.1"), "IPv6 gateway must be IPv6"),
            ((ADDR, "", ["192.0.2.53", "bad"]), "does not appear"),
        ],
    )
    def test_invalid_input_is_returned_before_touching_the_interface(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, args, match
    ):
        path = scratch_conf(UNCONFIGURED)
        before = parsed(ifutil, path)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        result = ifutil.set_static6("eth0", *args)

        assert match in result
        assert run.calls == []
        assert parsed(ifutil, path) == before

    def test_address_missing_after_ifup_is_an_error(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, ip_shows
    ):
        scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(
            ifutil.subprocess, "run", FakeRun(stderr="link down")
        )
        ip_shows(("2001:db8:1:0:be24:11ff:feed:44bd/64", "dynamic"))

        result = ifutil.set_static6("eth0", ADDR)

        assert result.startswith("Error: 2001:db8:1::10 not found on eth0")
        assert "link down" in result

    def test_write_failure_restores_backup(
        self, ifutil, scratch_conf, monkeypatch, no_sleep
    ):
        path = scratch_conf(UNCONFIGURED)
        before = parsed(ifutil, path)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())

        def broken(self, ifname, *args, **kwargs):
            self.conf[ifname] = ["auto eth0", "iface eth0 inet6 static"]
            raise ifutil.BadIfConfigError("simulated")

        monkeypatch.setattr(ifutil.NetworkInterfaces, "set_static6", broken)

        assert ifutil.set_static6("eth0", ADDR) == "simulated"
        assert parsed(ifutil, path) == before


class TestSetDhcp6Wrapper:
    def test_happy_path(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, ip_shows
    ):
        path = scratch_conf(STATIC_V4)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)
        ip_shows(("2001:db8:1:0:be24:11ff:feed:44bd/64", "dynamic"))

        assert ifutil.set_dhcp6("eth0") is None
        assert run.calls == [
            ["/usr/sbin/ifdown", "--force", "eth0"],
            ["/usr/sbin/ifup", "--force", "eth0"],
        ]
        text = open(path).read()
        assert "iface eth0 inet6 dhcp\n" in text
        assert "iface eth0 inet static\n" in text
        assert "    address 192.0.2.10\n" in text
        assert "2001:db8:1::1" not in text

    def test_no_address_after_retries_is_an_error(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, ip_shows
    ):
        scratch_conf(STATIC_V4)
        monkeypatch.setattr(
            ifutil.subprocess, "run", FakeRun(stderr="no router")
        )
        ip_shows()

        result = ifutil.set_dhcp6("eth0")

        assert result.startswith("Error obtaining IPv6 address")
        assert "no router" in result

    def test_write_failure_restores_backup(
        self, ifutil, scratch_conf, monkeypatch, no_sleep
    ):
        path = scratch_conf(STATIC_V4)
        before = parsed(ifutil, path)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())

        def broken(self, ifname):
            raise ifutil.BadIfConfigError("simulated")

        monkeypatch.setattr(ifutil.NetworkInterfaces, "set_dhcp6", broken)

        assert ifutil.set_dhcp6("eth0") == "simulated"
        assert parsed(ifutil, path) == before
