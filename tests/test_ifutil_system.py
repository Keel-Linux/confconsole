"""ifutil.py wrappers around the system, with the system stubbed.

`subprocess` calls, `sleep`, `netinfo.InterfaceInfo` and the resolvconf
paths are replaced by fakes that record what was asked and answer what
the test case dictates, so every error path runs in milliseconds and
nothing touches the live network.
"""

import subprocess

import pytest

from conftest import STATIC_V4, UNCONFIGURED


class FakeRun:
    """Replacement for subprocess.run recording argv and returning rc."""

    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(
            args, self.returncode, stdout="", stderr=self.stderr
        )


@pytest.fixture
def scratch_conf(ifutil, interfaces_file, hostname, monkeypatch):
    """Point NetworkInterfaces.CONF_FILE at a scratch file with `text`."""

    def _point(text):
        path = interfaces_file(text)
        monkeypatch.setattr(ifutil.NetworkInterfaces, "CONF_FILE", path)
        return path

    return _point


@pytest.fixture
def no_sleep(ifutil, monkeypatch):
    monkeypatch.setattr(ifutil, "sleep", lambda seconds: None)


@pytest.fixture
def fake_netinfo(ifutil, monkeypatch):
    """Install a controllable InterfaceInfo and return its class."""

    class Info:
        address = None
        netmask = None
        gateway = None

        def __init__(self, ifname):
            self.ifname = ifname

        def get_gateway(self, error=False):
            return self.gateway

    monkeypatch.setattr(ifutil, "InterfaceInfo", Info)
    return Info


def parsed(ifutil, path):
    """The interface configuration a file holds, independent of layout."""
    interfaces = ifutil.NetworkInterfaces()
    interfaces.read(path)
    return interfaces.conf


class TestParseResolv:
    def test_collects_nameserver_lines_only(self, ifutil, tmp_path):
        resolv = tmp_path / "resolv.conf"
        resolv.write_text(
            "# generated\nsearch example.net\n"
            "nameserver 2001:db8::53\nnameserver 2001:db8::54\n"
        )

        assert ifutil._parse_resolv(str(resolv)) == [
            "2001:db8::53",
            "2001:db8::54",
        ]


class TestGetNameservers:
    def test_static_nameservers_come_from_interfaces(
        self, ifutil, scratch_conf
    ):
        scratch_conf(STATIC_V4)

        assert ifutil.get_nameservers("eth0") == ["2001:db8::53", "192.0.2.53"]

    def test_falls_back_to_resolvconf_run_directory(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(ifutil, "exists", lambda path: True)
        monkeypatch.setattr(
            ifutil.os,
            "listdir",
            lambda path: ["lo.inet", "eth0.inet", "eth0.dhcp"],
        )
        seen = []

        def fake_parse(path):
            seen.append(path)
            return ["2001:db8::53"] if path.endswith("eth0.dhcp") else []

        monkeypatch.setattr(ifutil, "_parse_resolv", fake_parse)

        assert ifutil.get_nameservers("eth0") == ["2001:db8::53"]
        assert seen == ["/etc/resolvconf/run/interface/eth0.dhcp"]

    def test_falls_back_to_resolv_conf(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(ifutil, "exists", lambda path: False)
        monkeypatch.setattr(
            ifutil, "_parse_resolv", lambda path: [path]
        )

        assert ifutil.get_nameservers("eth0") == ["/etc/resolv.conf"]

    def test_empty_resolvconf_entries_fall_through(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(ifutil, "exists", lambda path: True)
        monkeypatch.setattr(ifutil.os, "listdir", lambda path: ["eth0.dhcp"])
        monkeypatch.setattr(ifutil, "_parse_resolv", lambda path: [])

        assert ifutil.get_nameservers("eth0") == []


class TestIfupIfdown:
    def test_ifup_without_force(self, ifutil, monkeypatch):
        run = FakeRun(stderr="")
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        assert ifutil.ifup("eth0") == ""
        assert run.calls == [["/usr/sbin/ifup", "eth0"]]

    def test_ifup_with_force_ignores_errors(self, ifutil, monkeypatch):
        run = FakeRun(returncode=1, stderr="already configured")
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        assert ifutil.ifup("eth0", force=True) == "already configured"
        assert run.calls == [["/usr/sbin/ifup", "--force", "eth0"]]

    def test_ifup_failure_raises(self, ifutil, monkeypatch):
        monkeypatch.setattr(
            ifutil.subprocess, "run", FakeRun(returncode=1, stderr="boom")
        )

        with pytest.raises(ifutil.BadIfConfigError, match="bring up"):
            ifutil.ifup("eth0")

    def test_ifdown_without_force(self, ifutil, monkeypatch):
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        assert ifutil.ifdown("eth0") == ""
        assert run.calls == [["/usr/sbin/ifdown", "eth0"]]

    def test_ifdown_with_force_ignores_errors(self, ifutil, monkeypatch):
        run = FakeRun(returncode=1, stderr="not configured")
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        assert ifutil.ifdown("eth0", force=True) == "not configured"
        assert run.calls == [["/usr/sbin/ifdown", "--force", "eth0"]]

    def test_ifdown_failure_raises(self, ifutil, monkeypatch):
        monkeypatch.setattr(
            ifutil.subprocess, "run", FakeRun(returncode=1, stderr="boom")
        )

        with pytest.raises(ifutil.BadIfConfigError, match="bring down"):
            ifutil.ifdown("eth0")


class TestUnconfigureIf:
    def test_happy_path_writes_manual_and_flushes(
        self, ifutil, scratch_conf, monkeypatch
    ):
        path = scratch_conf(STATIC_V4)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)
        flushed = []
        monkeypatch.setattr(
            ifutil.subprocess, "check_output", lambda cmd: flushed.append(cmd)
        )

        assert ifutil.unconfigure_if("eth0") is None
        assert flushed == [["/usr/sbin/ip", "addr", "flush", "dev", "eth0"]]
        assert run.calls == [
            ["/usr/sbin/ifdown", "eth0"],
            ["/usr/sbin/ifup", "eth0"],
        ]
        assert "iface eth0 inet manual" in open(path).read()

    def test_ifdown_stderr_without_force_returns_it(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(STATIC_V4)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun(stderr="warn"))

        assert ifutil.unconfigure_if("eth0") == "warn"

    def test_flush_failure_without_force_returns_error(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(STATIC_V4)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())

        def failing(cmd):
            raise subprocess.CalledProcessError(2, cmd)

        monkeypatch.setattr(ifutil.subprocess, "check_output", failing)

        assert "returned non-zero" in ifutil.unconfigure_if("eth0")

    def test_flush_failure_with_force_retries_addr_and_route(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(STATIC_V4)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        def failing(cmd):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(ifutil.subprocess, "check_output", failing)

        assert ifutil.unconfigure_if("eth0", force=True) is None
        assert run.calls[1:3] == [
            ["/usr/sbin/ip", "addr", "flush", "dev", "eth0"],
            ["/usr/sbin/ip", "route", "flush", "dev", "eth0"],
        ]

    def test_forced_retry_failure_raises(
        self, ifutil, scratch_conf, monkeypatch
    ):
        scratch_conf(STATIC_V4)

        def run(args, **kwargs):
            rc = 1 if args[0] == "/usr/sbin/ip" else 0
            return subprocess.CompletedProcess(
                args, rc, stdout="", stderr="no dev"
            )

        monkeypatch.setattr(ifutil.subprocess, "run", run)

        def failing(cmd):
            raise OSError("denied")

        monkeypatch.setattr(ifutil.subprocess, "check_output", failing)

        with pytest.raises(ifutil.BadIfConfigError, match="no dev"):
            ifutil.unconfigure_if("eth0", force=True)

    def test_ifup_failure_restores_backup_and_forces_up(
        self, ifutil, scratch_conf, monkeypatch
    ):
        path = scratch_conf(STATIC_V4)
        before = parsed(ifutil, path)

        calls = []

        def run(args, **kwargs):
            calls.append(list(args))
            if args == ["/usr/sbin/ifup", "eth0"]:
                return subprocess.CompletedProcess(
                    args, 1, stdout="", stderr="link down"
                )
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(ifutil.subprocess, "run", run)
        monkeypatch.setattr(ifutil.subprocess, "check_output", lambda cmd: b"")

        result = ifutil.unconfigure_if("eth0")

        assert "link down" in result
        assert calls[-1] == ["/usr/sbin/ifup", "--force", "eth0"]
        assert parsed(ifutil, path) == before


class TestSetStatic:
    def test_happy_path_writes_config_and_checks_address(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        path = scratch_conf(UNCONFIGURED)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)
        fake_netinfo.address = "192.0.2.10"

        result = ifutil.set_static(
            "eth0",
            "192.0.2.10",
            "255.255.255.0",
            "192.0.2.1",
            ["2001:db8::53"],
        )

        assert result is None
        assert run.calls == [
            ["/usr/sbin/ifdown", "--force", "eth0"],
            ["/usr/sbin/ifup", "--force", "eth0"],
        ]
        text = open(path).read()
        assert "    gateway 192.0.2.1\n" in text
        assert "    dns-nameservers 2001:db8::53\n" in text

    def test_gateway_is_optional(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        path = scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())
        fake_netinfo.address = "192.0.2.10"

        result = ifutil.set_static(
            "eth0", "192.0.2.10", "255.255.255.0", "", []
        )

        assert result is None
        assert "gateway" not in open(path).read()

    def test_invalid_address_is_returned_as_text(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        scratch_conf(UNCONFIGURED)
        run = FakeRun()
        monkeypatch.setattr(ifutil.subprocess, "run", run)

        result = ifutil.set_static("eth0", "2001:db8::1", "64", "", [])

        assert "not a valid IPv4" in result
        assert run.calls == []

    def test_no_address_after_ifup_is_an_error(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        scratch_conf(UNCONFIGURED)
        monkeypatch.setattr(
            ifutil.subprocess, "run", FakeRun(stderr="dhcp timeout")
        )
        fake_netinfo.address = None

        result = ifutil.set_static(
            "eth0", "192.0.2.10", "255.255.255.0", "", []
        )

        assert result.startswith("Error obtaining IP address")
        assert "dhcp timeout" in result

    def test_write_failure_restores_backup(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        path = scratch_conf(UNCONFIGURED)
        before = parsed(ifutil, path)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())

        def broken(self, ifname, *args, **kwargs):
            self.conf[ifname] = ["auto eth0", "iface eth0 inet static"]
            raise ifutil.BadIfConfigError("simulated")

        monkeypatch.setattr(ifutil.NetworkInterfaces, "set_static", broken)

        result = ifutil.set_static(
            "eth0", "192.0.2.10", "255.255.255.0", "", []
        )

        assert result == "simulated"
        assert parsed(ifutil, path) == before


class TestSetDhcp:
    def test_happy_path(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        path = scratch_conf(STATIC_V4)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())
        fake_netinfo.address = "192.0.2.77"

        assert ifutil.set_dhcp("eth0") is None
        assert "iface eth0 inet dhcp" in open(path).read()

    def test_no_address_after_retries_is_an_error(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        scratch_conf(STATIC_V4)
        monkeypatch.setattr(
            ifutil.subprocess, "run", FakeRun(stderr="no lease")
        )
        fake_netinfo.address = None

        result = ifutil.set_dhcp("eth0")

        assert result.startswith("Error obtaining IP address")
        assert "no lease" in result

    def test_write_failure_restores_backup(
        self, ifutil, scratch_conf, monkeypatch, no_sleep, fake_netinfo
    ):
        path = scratch_conf(STATIC_V4)
        before = parsed(ifutil, path)
        monkeypatch.setattr(ifutil.subprocess, "run", FakeRun())

        def broken(self, ifname):
            raise ifutil.BadIfConfigError("simulated")

        monkeypatch.setattr(ifutil.NetworkInterfaces, "set_dhcp", broken)

        assert ifutil.set_dhcp("eth0") == "simulated"
        assert parsed(ifutil, path) == before


class TestGetIpconf:
    def test_returns_address_netmask_gateway_and_nameservers(
        self, ifutil, scratch_conf, no_sleep, fake_netinfo
    ):
        scratch_conf(STATIC_V4)
        fake_netinfo.address = "192.0.2.10"
        fake_netinfo.netmask = "255.255.255.0"
        fake_netinfo.gateway = "192.0.2.1"

        assert ifutil.get_ipconf("eth0") == (
            "192.0.2.10",
            "255.255.255.0",
            "192.0.2.1",
            ["2001:db8::53", "192.0.2.53"],
        )

    def test_interface_down_returns_none_address(
        self, ifutil, scratch_conf, no_sleep, fake_netinfo
    ):
        scratch_conf(STATIC_V4)
        fake_netinfo.gateway = None

        assert ifutil.get_ipconf("eth0") == (
            None,
            None,
            None,
            ["2001:db8::53", "192.0.2.53"],
        )


class TestGetIpv6conf:
    IP_OUTPUT = (
        "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP\n"
        "    inet6 2001:db8:1::10/64 scope global dynamic mngtmpaddr\n"
        "       valid_lft 86395sec preferred_lft 14395sec\n"
    )

    def test_returns_first_global_address_and_prefix(
        self, ifutil, monkeypatch
    ):
        calls = []

        def check_output(cmd, **kwargs):
            calls.append(cmd)
            return self.IP_OUTPUT

        monkeypatch.setattr(ifutil.subprocess, "check_output", check_output)

        assert ifutil.get_ipv6conf("eth0") == ("2001:db8:1::10", "64")
        assert calls == [
            ["ip", "-6", "addr", "show", "eth0", "scope", "global"]
        ]

    def test_no_inet6_line_gives_none(self, ifutil, monkeypatch):
        monkeypatch.setattr(
            ifutil.subprocess,
            "check_output",
            lambda cmd, **kw: "2: eth0: UP\n",
        )

        assert ifutil.get_ipv6conf("eth0") == (None, None)

    def test_command_failure_gives_none(self, ifutil, monkeypatch):
        def failing(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(ifutil.subprocess, "check_output", failing)

        assert ifutil.get_ipv6conf("eth0") == (None, None)


class TestGetIfmethod:
    def test_method_per_family(self, ifutil, scratch_conf):
        scratch_conf(STATIC_V4)

        assert ifutil.get_ifmethod("eth0") == "static"
        assert ifutil.get_ifmethod("eth0", "inet6") == "static"

    def test_unknown_interface_gives_none(self, ifutil, scratch_conf):
        scratch_conf(UNCONFIGURED)

        assert ifutil.get_ifmethod("eth9") is None
