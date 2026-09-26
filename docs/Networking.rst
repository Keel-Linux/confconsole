Confconsole - Networking
========================

.. contents::

Overview
--------

Networking allows the user to allocate a server IP address via DHCP
(default) or set a static IPv6 or IPv4 address. The IPv6 and IPv4 settings
of an adapter are independent: changing one leaves the other as it is.

**IMPORTANT:** setting a static IP address on a cloud instance (e.g. AWS
EC2) will break your server's internet access and may make it unreachable.
**unless you know exactly what you are doing; DO NOT ADJUST NETWORKING ON
CLOUD SERVERS!** You have been warned!

As of Confconsole v2.0.0 (default in v16.0+ TurnKey appliances), all cloud
builds have Confconsole's Networking options disabled (``networking false``
in ``/etc/confconsole/confconsole.conf``).

.. image:: ./images/02_confconsole_core_networking.png

DHCP
----

Selecting **DHCP** from the menu will querry the local DHCP server for a new
dynamically allocated IP address.

Static
------

As noted above; **DO NOT change network settings on a cloud server!**

Selecting **StaticIP** from the menu allows you to set a static IP address
as follows:

- IP Adress: The desired static IP address
- Netmask: Subnet details (if you are on a LAN with 192.168.x.x then
  it's probably 255.255.255.0)
- Default Gateway: The internet Gateway IP address (your router IP if on
  a LAN)
- Name Server(s): The IP address(es) of DNS servers to use. Currently
  allows up to 3.

Static IPv6
-----------

Selecting **StaticIPv6** from the menu sets a static IPv6 address on the
adapter and leaves the IPv4 configuration untouched:

- IPv6 Address/Prefix: address and prefix length in one field, for
  example ``2001:db8:1::10/64``. The prefix length is required; there is
  no netmask field for IPv6.
- IPv6 Gateway: optional. A link-local gateway such as ``fe80::1`` is
  accepted (the usual case on a routed segment).
- Name Server(s): IPv6 addresses of DNS servers, for example
  ``2001:db8::53``. IPv4 entries are dropped from the IPv6 stanza; set them
  in the StaticIP form instead.

An IPv4 address typed in any of these fields is refused with a message
pointing at the StaticIP form. Clearing every field and applying returns
the adapter to the shipped default, ``inet6 dhcp`` (SLAAC and DHCPv6).

The result is an ``iface eth0 inet6 static`` stanza in
``/etc/network/interfaces``, next to the existing ``inet`` stanza; the
``# UNCONFIGURED INTERFACES`` header is kept so Confconsole can edit the
file again later. The adapter list and the usage screen show the global
IPv6 address, so an adapter with only an IPv6 address is not reported as
"not configured".

Notes
-----

By default, initially TurnKey Linux sets an IP address via DHCP (see
limitations below).

Changes to network config via Confconsole are persistent and will
survive reboot (see limitations below).

Limitations
-----------

IPv6 support covers a static address, DHCP (SLAAC and DHCPv6) and
display. Name servers on the IPv6 stanza are limited to IPv6 addresses.

In most build types, by default TurnKey Linux sets an IP address via
DHCP. The exceptions to that are Proxmox/LXC and Docker. Generally these
builds have an IP (static or dynamic), set via the host when
initially created. 

In some limited cases (e.g. Proxmox - depending on configuration),
any networking adjustments made via Confconsole (or other means) will apply,
but will NOT be persistent post-reboot. The networking can still be
reconfigured on the running system. However, changes will be lost on
reboot. As a general rule, it is recommended that unless you have a need
to reconfigure networking within the instance, set the desired configuration
on the host.

Some other platforms (e.g. AWS EC2 and OpenStack) will almost certainly
break if a static IP is set! As of Confconsole v2.0.0 (default in TurnKey
v16.0+) TurnKey Cloud builds (currently includes EC2, Xen and OpenStack)
have the Networking config options disabled.

Technical note
--------------

Technically the Networking option is not provided by a plugin as it
is a legacy "Advanced" menu option.

