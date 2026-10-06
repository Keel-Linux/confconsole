"""Tests for ipaddr: IPv4 validation, the IP type and IPRange.

Current IPv4 behaviour only; IPv6 is separate planned work. Addresses are
from the RFC 5737 documentation ranges (192.0.2.0/24, 198.51.100.0/24).
"""

import operator

import pytest

import ipaddr
from ipaddr import IP, IPRange, is_legal_ip


class TestIsLegalIp:
    @pytest.mark.parametrize(
        "ip", ["0.0.0.0", "192.0.2.10", "255.255.255.255", "198.51.100.1"]
    )
    def test_accepts_dotted_quad(self, ip):
        assert is_legal_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "192.0.2",  # too few octets
            "192.0.2.1.5",  # too many octets
            "256.0.2.1",  # octet above 255
            "192.0.2.-1",  # negative octet
        ],
    )
    def test_rejects_wrong_octet_count_or_range(self, ip):
        assert is_legal_ip(ip) is False

    @pytest.mark.parametrize("ip", ["a.b.c.d", "192.0.2.x", "192..0.2", ""])
    def test_rejects_non_numeric_text(self, ip):
        assert is_legal_ip(ip) is False

    def test_rejects_an_octet_only_int_accepts(self):
        # int("+1") is 1, so the octet check passes; inet_aton refuses it.
        assert is_legal_ip("192.0.2.+1") is False


class TestIP:
    def test_from_string(self):
        ip = IP("192.0.2.10")

        assert int(ip) == 0xC000020A
        assert str(ip) == "192.0.2.10"
        assert repr(ip) == "IP(192.0.2.10)"

    def test_from_int(self):
        assert str(IP(0xC000020A)) == "192.0.2.10"

    def test_from_another_ip(self):
        original = IP("192.0.2.1")

        copy = IP(original)

        assert copy == original
        assert isinstance(copy, IP)

    def test_illegal_string_raises_error(self):
        with pytest.raises(ipaddr.Error, match="illegal ip"):
            IP("300.0.2.1")

    @pytest.mark.parametrize(
        "op, operand, expected",
        [
            (operator.add, 1, "192.0.2.2"),
            (operator.sub, 1, "192.0.2.0"),
            (operator.and_, IP("255.255.255.0"), "192.0.2.0"),
            (operator.or_, 0xFF, "192.0.2.255"),
            (operator.xor, 0x1, "192.0.2.0"),
        ],
    )
    def test_operators_return_ip(self, op, operand, expected):
        result = op(IP("192.0.2.1"), operand)

        assert isinstance(result, IP)
        assert str(result) == expected


class TestIPRange:
    def test_from_cidr(self):
        network_range = IPRange.from_cidr("192.0.2.0/24")

        assert str(network_range.ip) == "192.0.2.0"
        assert str(network_range.netmask) == "255.255.255.0"
        assert str(network_range.network) == "192.0.2.0"
        assert str(network_range.broadcast) == "192.0.2.255"
        assert network_range.cidr == 24

    def test_from_address_and_netmask(self):
        network_range = IPRange("198.51.100.7", "255.255.255.0")

        assert str(network_range.network) == "198.51.100.0"
        assert str(network_range.broadcast) == "198.51.100.255"
        assert network_range.cidr == 24

    def test_contains_addresses_between_network_and_broadcast(self):
        network_range = IPRange.from_cidr("192.0.2.0/24")

        assert "192.0.2.1" in network_range
        assert IP("192.0.2.254") in network_range
        # the network and broadcast addresses are not inside (strict <)
        assert "192.0.2.0" not in network_range
        assert "192.0.2.255" not in network_range
        assert "198.51.100.1" not in network_range

    def test_formats_with_the_given_address(self):
        network_range = IPRange.from_cidr("192.0.2.10/24")

        assert network_range.fmt_cidr() == "192.0.2.10/24"
        assert str(network_range) == "192.0.2.10/24"
        assert repr(network_range) == "IPRange('192.0.2.10', '255.255.255.0')"

    def test_illegal_address_raises_error(self):
        with pytest.raises(ipaddr.Error):
            IPRange("192.0.2", "255.255.255.0")
