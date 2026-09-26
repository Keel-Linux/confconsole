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

Usage screen
------------

The main screen lists the addresses of the default adapter and the
services reachable on them, IPv6 first. The text comes from the template
``/etc/confconsole/services.txt`` (``conf/services.txt`` in the source),
with these placeholders:

- ``$ipaddr6``: the global IPv6 address of the adapter. When the adapter
  has several, the stable one is chosen: a static address before a SLAAC
  or DHCPv6 (``dynamic``) one, and privacy (``temporary``) addresses last.
- ``$ipaddr``: the IPv4 address, or the output of ``publicip_cmd`` from
  ``confconsole.conf`` when that is set.
- ``$hostname`` and ``$appname``: the host name in capitals and the
  appliance name from ``/etc/appname``.

A line whose placeholder has no value is dropped, so a template that
lists both families shows only the IPv6 block on an IPv6-only adapter
and only the IPv4 block on an IPv4-only one. The shipped template is::

    Web:       http://[$ipaddr6]
               https://[$ipaddr6]
    Web shell: https://[$ipaddr6]:12320
    Webmin:    https://[$ipaddr6]:12321
    SSH/SFTP:  root@$ipaddr6 (port 22)

    Web:       http://$ipaddr
               https://$ipaddr
    Web shell: https://$ipaddr:12320
    Webmin:    https://$ipaddr:12321
    SSH/SFTP:  root@$ipaddr (port 22)

An IPv6 address used as the host of a URL (right after ``://``) is
rendered in brackets, ``https://[2001:db8:1::10]:12321``, whether or not
the template writes them; ``root@$ipaddr6`` stays as it is.

Appliance templates written before ``$ipaddr6`` existed, with ``$ipaddr``
only, keep working without a change: on an adapter without IPv4 the IPv6
address takes the place of ``$ipaddr`` (bracketed in URLs), and on a dual
stack adapter two lines, ``IPv6 Web`` and ``IPv6 SSH``, precede the
template text. To show every service on both families, add the
``$ipaddr6`` lines to the appliance's ``services.txt`` as above.

In the networking menu the summary line of an adapter follows the same
order: ``2001:db8:1::10, 192.0.2.10 (dhcp) [*]``, with the configuration
method after each address when the two families differ
(``2001:db8:1::10 (static), 192.0.2.10 (dhcp)``). ``[*]`` marks the
adapter the usage screen shows.

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

