#!/usr/bin/python3
# Copyright (c) 2008 Alon Swartz <alon@turnkeylinux.org> - all rights reserved
"""TurnKey Configuration Console

Options:
    -h, --help           Display this help and exit
        --usage          Display usage screen without Advanced Menu
        --nointeractive  Do not display interactive dialog
        --plugin=<name>  Run plugin directly

"""

import logging
import os
import sys
import subprocess
from subprocess import CalledProcessError
import getopt
import ipaddress
import re
import shlex
from string import Template
from io import StringIO
import traceback

import dialog
from dialog import DialogError
from systemd.journal import JournalHandler
import netinfo

import ipaddr
import ifutil
import conf
import keelbanner
import plugin

from typing import NoReturn, Iterable, Mapping, Any

USAGE: str = __doc__ if __doc__ else ""
PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "plugins.d"
)
# The name at the top of every screen and, unless APPNAME_PATH names the
# appliance otherwise, before the hostname in the menu titles.
BRAND = "Keel Linux"
TITLE = f"{BRAND} Configuration Console"
APPNAME_PATH = "/etc/appname"

handler = JournalHandler(SYSLOG_IDENTIFIER="confconsole")
handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(handler)
log = logging.getLogger(__name__)


class ConfconsoleError(Exception):
    pass


def fatal(msg: str) -> NoReturn:
    msg = f"Error: {msg}"
    log.error(msg)
    print(msg, file=sys.stderr)
    sys.exit(1)


def usage(msg: str | getopt.GetoptError = "") -> NoReturn:
    if msg:
        msg = f"Error: {msg}"
        log.error(msg)
        print(msg, file=sys.stderr)

    print(f"Syntax: {sys.argv[0]}", file=sys.stderr)
    print(USAGE.strip(), file=sys.stderr)
    sys.exit(1)


def format_fields(
    fields: Iterable[tuple[str, str, int, int]],
    field_offset: int | None = None,
) -> list[tuple[str, int, int, str, int, int, int, int]]:
    """Takes fields in format (label, field, label_length, field_length) and
    outputs fields in format (label, ly, lx, item, iy, ix, field_length,
    input_length)

    By default the field starts after label_length columns and is as wide;
    'field_offset' separates the two, so a 43 column IPv6 field can follow
    a 20 column label.
    """
    out = []
    for i, (label, field, l_length, f_length) in enumerate(fields):
        ix = (field_offset if field_offset is not None else l_length) + 1
        out.append((label, i + 1, 1, field, i + 1, ix, l_length, f_length))
    return out


def _url_host_pattern(name: str) -> re.Pattern[str]:
    """The placeholder `name` used as the host of a URL: `://$name` or
    `://${name}`, not already inside brackets (`://[$name]` has no match
    because the bracket separates `://` from `$`)."""
    return re.compile(rf"://\$(?:{name}\b|\{{{name}\}})")


def render_usage_line(
    line: str, values: Mapping[str, str | None]
) -> str | None:
    """Substitute the placeholders of one line of a usage template.

    Returns None when a placeholder of the line resolves to None, so the
    caller drops the line: a template that lists both address families
    shows only the lines of the family the adapter has. Names the mapping
    does not know are left as they are (`Template.safe_substitute`), as
    are `$$` and a lone `$`. An IPv6 value used as the host of a URL
    (after `://`) is wrapped in brackets, `https://[2001:db8:1::10]:12321`,
    unless the template already wrote them.
    """
    for name in Template(line).get_identifiers():
        if name not in values:
            continue
        value = values[name]
        if value is None:
            return None
        if ":" in value:
            line = _url_host_pattern(name).sub(f"://[${{{name}}}]", line)
    return Template(line).safe_substitute(values)


def ipv6_lines(ipaddr6: str, web: bool) -> str:
    """The compact IPv6 block for a template that has no `$ipaddr6`."""
    text = f"IPv6 Web:  https://[{ipaddr6}]\n" if web else ""
    return text + f"IPv6 SSH:  root@{ipaddr6}"


def render_usage(
    template: str,
    ipaddr6: str | None,
    ipaddr: str | None,
    **names: str,
) -> str:
    """Render the usage text of the default adapter, IPv6 first.

    `$ipaddr6` is the global IPv6 address of the adapter (the one
    `ifutil.get_ipv6conf` ranks first: static before dynamic, privacy
    addresses last) and `$ipaddr` its IPv4, or the public address from
    `publicip_cmd`. Lines whose placeholder resolves to None are dropped,
    so a template that lists both families shows one block on a single
    stack adapter and both, in template order, on a dual stack one.

    A template written for IPv4 only (`$ipaddr` without `$ipaddr6`) keeps
    working: on an adapter without IPv4 the IPv6 address takes the place
    of `$ipaddr`, bracketed where it is a URL host, and on a dual stack
    adapter the IPv6 web and SSH lines precede the template text, so the
    operator reads IPv6 first either way. Every other name (`$appname`,
    `$hostname`) comes from `names`.
    """
    identifiers = Template(template).get_identifiers()
    if ipaddr is None and "ipaddr6" not in identifiers:
        ipaddr = ipaddr6
    values: dict[str, str | None] = {
        "ipaddr6": ipaddr6, "ipaddr": ipaddr, **names,
    }
    rendered = (
        render_usage_line(line, values) for line in template.splitlines()
    )
    text = "\n".join(line for line in rendered if line is not None)
    text = text.strip("\n")
    if ipaddr6 and ipaddr6 not in text:
        block = ipv6_lines(ipaddr6, web=template.startswith("Web"))
        text = f"{block}\n\n{text}" if text else block
    return text


def describe_interface(
    ipaddr6: str | None,
    method6: str | None,
    ipaddr: str | None,
    method: str | None,
) -> str:
    """One line for the adapter list of the networking menu: the IPv6
    address then the IPv4, each with its configuration method, or the
    method once after both when it is the same (the menu is 65 columns
    wide and a SLAAC address alone takes up to 39)."""
    families = ((ipaddr6, method6), (ipaddr, method))
    entries = [(a, m) for a, m in families if a]
    if not entries:
        return "not configured"
    methods = [m for _, m in entries]
    if len(entries) > 1 and methods[0] and len(set(methods)) == 1:
        return ", ".join(a for a, _ in entries) + f" ({methods[0]})"
    return ", ".join(f"{a} ({m})" if m else a for a, m in entries)


WrapperReturn = str | tuple[str, str]


class Console:
    def __init__(
        self,
        title: str | None = None,
        width: int = 65,
        height: int = 25,
    ) -> None:
        self.width = width
        self.height = height

        self.console = dialog.Dialog(dialog="dialog")
        self.console.add_persistent_args(["--no-collapse"])
        self.console.add_persistent_args(["--ok-label", "Select"])
        self.console.add_persistent_args(["--cancel-label", "Back"])
        self.console.add_persistent_args(["--colors"])
        if conf.Conf().copy_paste:
            self.console.add_persistent_args(["--no-mouse"])
        if title:
            self.console.add_persistent_args(["--backtitle", title])

    def _handle_exitcode(self, retcode: str) -> bool:
        if retcode == "esc":
            text = "Do you really want to quit?"
            if self.console.yesno(text) == self.console.OK:
                sys.exit(0)
            return False
        return True

    def _wrapper(
        self,
        dialog: str,
        text: str,
        *args: Any,
        **kws: Any,
    ) -> WrapperReturn:
        try:
            method = getattr(self.console, dialog)
        except AttributeError:
            raise ConfconsoleError(f"dialog not supported: {dialog}")

        ret: WrapperReturn = ""

        while 1:
            try:
                ret = method(f"\n{text}", *args, **kws)
            except DialogError as e:
                if "Can't make new window" in e.message:
                    self.console.msgbox(
                        "Terminal too small for UI, resize terminal and"
                        " press OK",
                        ok_label="OK",
                    )
                    continue
                else:
                    raise

            if type(ret) is str:
                retcode = ret
            else:
                retcode = ret[0]

            if self._handle_exitcode(retcode):
                break

        return ret

    def infobox(self, text: str) -> str:
        v = self._wrapper("infobox", text)
        assert isinstance(v, str)
        return v

    def yesno(self, text: str, autosize: bool = False) -> str:
        if autosize:
            text += "\n "
            height, width = 0, 0
        else:
            height, width = 10, 30
        v = self._wrapper("yesno", text, height, width)
        assert isinstance(v, str)
        return v

    def msgbox(
        self,
        title: str,
        text: str,
        button_label: str = "ok",
        autosize: bool = False,
        height: int | None = None,
        width: int | None = None,
    ) -> str:
        # `height` and `width` override the default for a box that carries
        # more than the usual text, such as the usage screen with the mark
        # above it.
        if autosize:
            text += "\n "
            height, width = 0, 0
        else:
            height, width = height or self.height, width or self.width

        v = self._wrapper(
            "msgbox", text, height, width, title=title, ok_label=button_label
        )
        assert isinstance(v, str)
        return v

    def inputbox(
        self,
        title: str,
        text: str,
        init: str = "",
        ok_label: str = "OK",
        cancel_label: str = "Cancel",
    ) -> tuple[str, str]:
        no_cancel = True if cancel_label == "" else False
        v = self._wrapper(
            "inputbox",
            text,
            self.height,
            self.width,
            title=title,
            init=init,
            ok_label=ok_label,
            cancel_label=cancel_label,
            no_cancel=no_cancel,
        )
        assert isinstance(v, tuple)
        return v

    def menu(
        self,
        title: str,
        text: str,
        choices: list[tuple[str, str]],
        no_cancel: bool = False,
        default_item: str | None = None,
    ) -> tuple[str, str]:
        # default_item: the choice highlighted when the menu opens, such
        # as the role a node already has; dialog's first one otherwise
        extra = {} if default_item is None else {"default_item": default_item}
        v = self._wrapper(
            "menu",
            text,
            self.height,
            self.width,
            menu_height=len(choices) + 1,
            title=title,
            choices=choices,
            no_cancel=no_cancel,
            **extra,
        )
        assert isinstance(v, tuple)
        return v

    def form(
        self,
        title: str,
        text: str,
        fields: list[tuple[str, int, int, str, int, int, int, int]],
        ok_label: str = "Apply",
        cancel_label: str = "Cancel",
        autosize: bool = False,
    ) -> tuple[str, str]:
        if autosize:
            text += "\n "
            height, width = 0, 0
        else:
            height, width = self.height, self.width
        v = self._wrapper(
            "form",
            text,
            fields,
            height=height,
            width=width,
            form_height=len(fields) + 1,
            title=title,
            ok_label=ok_label,
            cancel_label=cancel_label,
        )
        assert isinstance(v, tuple)
        return v


class Installer:
    def __init__(self, path: str) -> None:
        self.path: str = path
        self.available: bool = self._is_available()

    def _is_available(self) -> bool:
        if not os.path.exists(self.path):
            return False

        with open("/proc/cmdline") as fob:
            return "boot=live" in fob.readline().split()

    def execute(self) -> None:
        if not self.available:
            raise ConfconsoleError("installer is not available to be executed")

        subprocess.run([self.path])


class TurnkeyConsole:
    OK = "ok"
    CANCEL = 1

    def __init__(
        self,
        pluginManager: plugin.PluginManager,
        eventManager: plugin.EventManager,
        advanced_enabled: bool = True,
    ) -> None:
        self.width = 65
        self.height = 25

        self.console = Console(TITLE, self.width, self.height)

        # sometimes it would be nice to have the appname be something other
        # than the hostname. Allow developers to create  file containing the
        # appname in /etc/appname
        try:
            with open(APPNAME_PATH, 'r') as fob:
                self.appname = fob.read().rstrip()
        except FileNotFoundError:
            self.appname = f"{BRAND} {netinfo.get_hostname().upper()}"

        self.installer = Installer(path="/usr/bin/di-live")

        self.advanced_enabled = advanced_enabled

        self.eventManager = eventManager
        self.pluginManager = pluginManager
        self.pluginManager.updateGlobals({"console": self.console})

    @staticmethod
    def _get_filtered_ifnames() -> list[str]:
        ifnames = []
        for ifname in netinfo.get_ifnames():
            if ifname.startswith(
                ("lo", "tap", "br", "natbr", "tun", "vmnet", "veth", "wmaster")
            ):
                continue
            ifnames.append(ifname)

        # handle bridged LXC where br0 is the default outward-facing interface
        defifname = conf.Conf().default_nic
        if defifname and defifname.startswith("br"):
            ifnames.append(defifname)
            bridgedif = (
                subprocess.run(
                    ["brctl", "show", defifname],
                    capture_output=True,
                    text=True,
                )
                .stdout.split("\n")[1]
                .split("\t")[-1]
            )
            ifnames.remove(bridgedif)

        ifnames.sort()
        return ifnames

    @classmethod
    def _get_default_nic(cls) -> str | None:
        def _validip(ifname: str) -> bool:
            ip = ifutil.get_ipconf(ifname)[0]
            if ip and not ip.startswith("169"):
                return True
            ip6 = ifutil.get_ipv6conf(ifname)[0]
            if ip6:
                return True
            return False

        defifname = conf.Conf().default_nic
        if defifname and _validip(defifname):
            return defifname

        for ifname in cls._get_filtered_ifnames():
            if _validip(ifname):
                return ifname

        return None

    @classmethod
    def _get_public_ipaddr(cls) -> str | None:
        publicip_cmd = conf.Conf().publicip_cmd
        if publicip_cmd:
            command = subprocess.run(
                shlex.split(publicip_cmd),
                capture_output=True,
                text=True,
            )
            if command.returncode == 0:
                return command.stdout.strip()

        return None

    def _get_advmenu(
        self,
    ) -> tuple[
        list[tuple[str, str]], dict[str, plugin.Plugin | plugin.PluginDir]
    ]:
        items = []
        if conf.Conf().networking:
            items.append(("Networking", "Configure appliance networking"))

        if self.installer.available:
            items.append(("Install", "Install to hard disk"))

        plugin_map = {}

        for path in self.pluginManager.path_map:
            plug = self.pluginManager.path_map[path]
            if os.path.dirname(path) == PLUGIN_PATH:
                if isinstance(plug, plugin.Plugin) and hasattr(
                    plug.module, "run"
                ):
                    items.append(
                        (
                            plug.module_name.capitalize(),
                            str(plug.module.__doc__),
                        )
                    )
                elif isinstance(plug, plugin.PluginDir):
                    items.append(
                        (plug.module_name.capitalize(), plug.description)
                    )
                plugin_map[plug.module_name.capitalize()] = plug

        items.append(("Reboot", "Reboot the appliance"))
        items.append(("Shutdown", "Shutdown the appliance"))
        items.append(("Quit", "Quit the configuration console"))

        return items, plugin_map

    def _get_netmenu(self) -> list[tuple[str, str]]:
        menu = []
        for ifname in self._get_filtered_ifnames():
            log.debug("found ifname: %s", ifname)
            addr6 = ifutil.get_ipv6conf(ifname)[0]
            ifmethod6 = ifutil.get_ifmethod(ifname, "inet6")
            log.debug(
                "ifname '%s' ipv6 addr: %s ifmethod: %s",
                ifname, addr6, ifmethod6,
            )
            addr = ifutil.get_ipconf(ifname)[0]
            ifmethod = ifutil.get_ifmethod(ifname)
            log.debug(
                "ifname '%s' addr: %s ifmethod: %s", ifname, addr, ifmethod
            )

            desc = describe_interface(addr6, ifmethod6, addr, ifmethod)
            if (addr6 or addr) and ifname == self._get_default_nic():
                desc += " [*]"

            menu.append((ifname, desc))

        return menu

    def _get_ifconfmenu(self, ifname: str) -> list[tuple[str, str]]:
        menu = []
        menu.append(("DHCP", "Configure networking automatically"))
        menu.append(("StaticIP", "Configure networking manually"))
        menu.append(("StaticIPv6", "Configure IPv6 networking manually"))

        if (
            not ifname == self._get_default_nic()
            and len(self._get_filtered_ifnames()) > 1
            and (
                ifutil.get_ipconf(ifname)[0] is not None
                or ifutil.get_ipv6conf(ifname)[0] is not None
            )
        ):
            menu.append(("Default", "Show this adapter's IP address in Usage"))

        return menu

    def _get_ifconftext(self, ifname: str) -> str:
        addr, netmask, gateway, nameservers = ifutil.get_ipconf(ifname)
        ipv6_addr, ipv6_prefix = ifutil.get_ipv6conf(ifname)
        if addr is None and ipv6_addr is None:
            msg = "Network adapter is not configured"
            log.warning(msg)
            return msg + "\n"
        nameserver_str = " ".join(nameservers)
        text = ""
        if addr is not None:
            log.info(
                f"ip: {addr} netmask: {netmask} gateway: {gateway}"
                f" nameservers: {nameserver_str}",
            )
            text += f"IP Address:      {addr}\n"
            text += f"Netmask:         {netmask}\n"
            text += f"Default Gateway: {gateway}\n"
            text += f"Name Server(s):  {nameserver_str}\n"
        if ipv6_addr:
            log.info(f"ipv6: {ipv6_addr}/{ipv6_prefix}")
            text += f"IPv6 Address:    {ipv6_addr}/{ipv6_prefix}\n"
            if addr is None:
                text += f"Name Server(s):  {nameserver_str}\n"
        text += "\n"

        ifmethod = ifutil.get_ifmethod(ifname)
        if ifmethod:
            conf_method = f"Networking configuration method: {ifmethod}"
            log.info(conf_method)
            text += conf_method + "\n"
        ifmethod6 = ifutil.get_ifmethod(ifname, "inet6")
        if ifmethod6:
            conf_method6 = f"IPv6 configuration method: {ifmethod6}"
            log.info(conf_method6)
            text += conf_method6 + "\n"

        if len(self._get_filtered_ifnames()) > 1:
            text += "Is this adapter's IP address displayed in Usage: "
            if ifname == self._get_default_nic():
                text += "yes\n"
            else:
                text += "no\n"

        return text

    def usage(self) -> str:
        if self.advanced_enabled:
            default_button_label = "Advanced Menu"
            default_return_value = "advanced"
        else:
            default_button_label = "Quit"
            default_return_value = "quit"

        # if no interfaces at all - display error and go to advanced
        if len(self._get_filtered_ifnames()) == 0:
            error = "No network adapters detected"
            log.error(error)
            if not self.advanced_enabled:
                fatal(error)

            self.console.msgbox("Error", error)
            return "advanced"

        # if interfaces but no default - display error and go to networking
        ifname = self._get_default_nic()
        if not ifname:
            error = "Networking is not yet configured"
            log.error(error)
            if not self.advanced_enabled:
                fatal(error)

            self.console.msgbox("Error", error)
            return "networking"

        # No TKLBAM status and no TurnKey Hub footer: a Keel appliance
        # ships neither and depends on no hub (handbook decision 0020).
        # display usage, IPv6 first
        ipv6_addr = ifutil.get_ipv6conf(ifname)[0]
        ip_addr = self._get_public_ipaddr()
        if not ip_addr:
            ip_addr = ifutil.get_ipconf(ifname)[0]
        hostname = netinfo.get_hostname().upper()

        try:
            with open(conf.path("services.txt")) as fob:
                template = fob.read().rstrip()
        except conf.ConfconsoleConfError:
            template = ""
        text = render_usage(
            template,
            ipv6_addr,
            ip_addr,
            appname=self.appname,
            hostname=hostname,
        )

        log.info(
            f"Usage started - hostname: {hostname} ipv6: {ipv6_addr}"
            f" ip: {ip_addr}"
        )
        # The mark above the usage text, the largest tier (wide, full,
        # small) the dialog has room for on this screen over and above
        # the rows the text needs, so not one line of what the appliance
        # already says is lost: a smaller tier, and then none, is taken
        # before that happens. The UTF-8 tiers in a UTF-8 locale, the
        # ASCII ones otherwise. The box widens to a mark wider than it
        # and grows by the rows the mark takes; the mark is centred on the
        # columns the box leaves inside its frame, the usage text keeps
        # its own left margin.
        height, width = self.height, self.width
        room_rows, room_cols = keelbanner.available(
            *keelbanner.terminal_size()
        )
        inside = keelbanner.inner_width(min(width, room_cols))
        used = keelbanner.text_rows(text, inside) + keelbanner.BOX_CHROME
        mark = keelbanner.choose(
            room_rows, room_cols, used, keelbanner.marks(os.environ)
        )
        if mark is not None:
            width = keelbanner.box_width(mark, width, room_cols)
            centred = keelbanner.center(mark, keelbanner.inner_width(width))
            text = keelbanner.above(text, centred)
            height = max(
                used + keelbanner.added_rows(mark), min(height, room_rows)
            )

        retcode = self.console.msgbox(
            f"{hostname} appliance services",
            text,
            button_label=default_button_label,
            height=height,
            width=width,
        )

        if retcode is not self.OK:
            self.running = False

        return default_return_value

    def advanced(self) -> str:
        # dont display cancel button when no interfaces at all
        no_cancel = False
        if len(self._get_filtered_ifnames()) == 0:
            no_cancel = True

        items, plugin_map = self._get_advmenu()

        retcode, choice = self.console.menu(
            "Advanced Menu",
            self.appname + " Advanced Menu\n",
            items,
            no_cancel=no_cancel,
        )

        if retcode is not self.OK:
            return "usage"

        if choice in plugin_map:
            return plugin_map[choice].path

        return "_adv_" + choice.lower()

    def networking(self) -> str:
        ifnames = self._get_filtered_ifnames()

        # if no interfaces at all - display error and go to advanced
        if len(ifnames) == 0:
            log.warning("no interfaces found")
            self.console.msgbox("Error", "No network adapters detected")
            return "advanced"

        log.info(f"{len(ifnames)} interface/s found: {', '.join(ifnames)}")
        # if only 1 interface, dont display menu - just configure it
        if len(ifnames) == 1:
            self.ifname = ifnames[0]
            return "ifconf"

        # display networking
        text = "Choose network adapter to configure\n"
        if self._get_default_nic():
            text += "[*] This adapter's IP address is displayed in Usage"

        retcode, self.ifname = self.console.menu(
            "Networking configuration", text, self._get_netmenu()
        )

        if retcode is not self.OK:
            return "advanced"

        return "ifconf"

    def ifconf(self) -> str:
        retcode, choice = self.console.menu(
            f"{self.ifname} configuration",
            self._get_ifconftext(self.ifname),
            self._get_ifconfmenu(self.ifname),
        )

        if retcode is not self.OK:
            # if multiple interfaces go back to networking
            if len(self._get_filtered_ifnames()) > 1:
                return "networking"

            return "advanced"

        return "_ifconf_" + choice.lower()

    def _ifconf_staticip(self) -> str:
        log_msg = "Applying static ip"
        log.info(log_msg)

        def _validate(
            addr: str, netmask: str, gateway: str, nameservers: list[str]
        ) -> list[str]:
            """Validate Static IP form parameters. Returns an empty array on
            success, an array of strings describing errors otherwise"""
            log_valid_msg = f"{log_msg} {addr}"
            errors = []
            if not addr:
                errors.append("No IP address provided")
            elif not ipaddr.is_legal_ip(addr):
                errors.append(f"Invalid IP address: {addr}")

            if not netmask:
                errors.append("No netmask provided")
            elif not ipaddr.is_legal_ip(netmask):
                errors.append(f"Invalid netmask: {netmask}")

            for nameserver in nameservers:
                if nameserver and not ipaddr.is_legal_ip(nameserver):
                    errors.append(f"Invalid nameserver: {nameserver}")

            if len(nameservers) != len(set(nameservers)):
                errors.append("Duplicate nameservers specified")

            if errors:
                log.error(f"{log_valid_msg} failed: {', '.join(errors)}")
                return errors

            # Final sanity check via the stdlib ipaddress module. Unlike
            # is_legal_ip() this rejects a syntactically-valid but nonsensical
            # (non-contiguous) netmask such as 255.0.255.0, and confirms the
            # gateway falls within the resulting network.
            try:
                network = ipaddress.IPv4Network(
                    f"{addr}/{netmask}", strict=False
                )
            except ValueError as e:
                error = f"Invalid address/netmask: {e}"
                log.error(f"{log_valid_msg} failed: {error}")
                return [error]

            if gateway:
                try:
                    gw = ipaddress.IPv4Address(gateway)
                except ValueError as e:
                    error = f"Invalid gateway: {e}"
                    log.error(f"{log_valid_msg} failed: {error}")
                    return [error]
                if gw not in network:
                    error = (
                        f"Gateway ({gateway}) not in network ({network})"
                    )
                    log.error(f"{log_valid_msg} failed: {error}")
                    return [error]

            return []

        warnings = []
        addr = None
        netmask = None
        gateway = None
        nameservers = None
        try:
            addr, netmask, gateway, nameservers = ifutil.get_ipconf(
                self.ifname, True
            )
            log.debug(
                "ifname: %s; addr: %s; netmask: %s; gateway: %s; nameservers: %s",
                self.ifname,
                addr,
                netmask,
                gateway,
                nameservers,
            )
        except CalledProcessError:
            warnings.append(
                "`route -n` returned non-0 exit code! (unable to get gateway)"
            )
        except netinfo.NetInfoError:
            warnings.append("failed to find default gateway!")
            addr, netmask, gateway, nameservers = ifutil.get_ipconf(
                self.ifname, False
            )

        if addr is None:
            warnings.append("failed to ascertain current address!")
            addr = ""
        if netmask is None:
            warnings.append("failed to ascertain current netmask!")
            netmask = ""
        if gateway is None:
            gateway = ""
        if nameservers is None:
            nameservers = []

        if warnings:
            warning_last_line = "Will leave relevant fields blank"
            log.warning(f"{log_msg} warning/s: {', '.join(warnings)}")
            log.warning(warning_last_line)
            self.console.msgbox(
                "Warning", "\n".join([*warnings, warning_last_line]),
            )

        value = [addr, netmask, gateway]
        value.extend(nameservers)

        # include minimum 2 nameserver fields and 1 blank one
        if len(value) < 4:
            value.append("")

        if value[-1]:
            value.append("")

        field_width = 30
        field_limit = 15

        while 1:
            pre_fields: list[tuple[str, str, int, int]] = [
                ("IP Address", value[0], field_width, field_limit),
                ("Netmask", value[1], field_width, field_limit),
                ("Default Gateway", value[2], field_width, field_limit),
            ]

            for i in range(len(value[3:])):
                pre_fields.append(
                    ("Name Server", value[3 + i], field_width, field_limit)
                )

            fields: list[tuple[str, int, int, str, int, int, int, int]] = (
                format_fields(pre_fields)
            )
            text = f"Static IP configuration ({self.ifname})"
            retcode, input = self.console.form(
                "Network settings", text, fields
            )
            log.debug("static ip fields: %s", fields)
            log.debug("static ip input: %s", input)
            log.debug("static ip retcode: %s", retcode)
            if retcode is not self.OK:
                break

            # remove any whitespaces the user might of included
            input = list(map(str.strip, input))

            # unconfigure the nic if all entries are empty
            if not input[0] and not input[1] and not input[2] and not input[3]:
                ifutil.unconfigure_if(self.ifname)
                break

            addr, netmask, gateway = input[:3]
            nameservers = input[3:]
            for i in range(nameservers.count("")):
                nameservers.remove("")

            err_parts = _validate(addr, netmask, gateway, nameservers)
            if err_parts:
                err: str = "\n".join(err_parts)
                self.console.msgbox("Error", err)
            else:
                in_ssh = "SSH_CONNECTION" in os.environ
                if not in_ssh or (
                    in_ssh
                    and self.console.yesno(
                        "Warning: Changing ip while an ssh session is active"
                        " will drop said ssh session!",
                        autosize=True,
                    )
                    == self.OK
                ):
                    maybe_err: str | None = ifutil.set_static(
                        self.ifname, addr, netmask, gateway, nameservers
                    )
                    if maybe_err is None:
                        break
                    self.console.msgbox("Error", maybe_err)
                else:
                    break

        return "ifconf"

    def _ifconf_staticipv6(self) -> str:
        """Static IPv6 form: address/prefix, gateway and name servers.

        The dialog only collects the fields; validation and the rewrite of
        the inet6 stanza are ifutil.set_static6(). Clearing every field
        returns the interface to the shipped default, inet6 dhcp.
        """
        log.info("Applying static IPv6")

        addr_prefix, gateway, nameservers = ifutil.get_ip6conf(self.ifname)
        value = [addr_prefix or "", gateway or "", *nameservers]

        # include minimum 1 nameserver field and 1 blank one
        if len(value) < 3:
            value.append("")
        if value[-1]:
            value.append("")

        label_width = 20
        addr_limit = 43  # 39 for the address, 4 for '/128'
        ip_limit = 39

        while 1:
            pre_fields: list[tuple[str, str, int, int]] = [
                ("IPv6 Address/Prefix", value[0], addr_limit, addr_limit),
                ("IPv6 Gateway", value[1], addr_limit, ip_limit),
            ]
            for nameserver in value[2:]:
                pre_fields.append(
                    ("Name Server", nameserver, addr_limit, ip_limit)
                )

            fields = format_fields(pre_fields, field_offset=label_width)
            text = f"Static IPv6 configuration ({self.ifname})"
            retcode, input = self.console.form(
                "Network settings", text, fields, autosize=True
            )
            log.debug("static ipv6 input: %s", input)
            log.debug("static ipv6 retcode: %s", retcode)
            if retcode is not self.OK:
                break

            # remove any whitespaces the user might of included
            input = list(map(str.strip, input))

            # back to the shipped default if all entries are empty
            if not any(input):
                err = ifutil.set_dhcp6(self.ifname)
                if err:
                    self.console.msgbox("Error", err)
                break

            addr_prefix, gateway = input[:2]
            nameservers = [ns for ns in input[2:] if ns]
            value = [addr_prefix, gateway, *nameservers, ""]

            in_ssh = "SSH_CONNECTION" in os.environ
            if in_ssh and (
                self.console.yesno(
                    "Warning: Changing ip while an ssh session is active"
                    " will drop said ssh session!",
                    autosize=True,
                )
                != self.OK
            ):
                break

            maybe_err = ifutil.set_static6(
                self.ifname, addr_prefix, gateway, nameservers
            )
            if maybe_err is None:
                break
            self.console.msgbox("Error", maybe_err)

        return "ifconf"

    def _ifconf_dhcp(self) -> str:
        in_ssh = "SSH_CONNECTION" in os.environ
        if not in_ssh or (
            in_ssh
            and self.console.yesno(
                "Warning: Changing ip while an ssh session is active will"
                " drop said ssh session!",
                autosize=True,
            )
            == self.OK
        ):
            self.console.infobox(f"Requesting DHCP for {self.ifname}...")
            err = ifutil.set_dhcp(self.ifname)
            if err:
                self.console.msgbox("Error", err)

        return "ifconf"

    def _ifconf_default(self) -> str:
        conf.Conf().set_default_nic(self.ifname)
        return "ifconf"

    def _adv_install(self) -> str:
        text = "Please note that any changes you may have made to the\n"
        text += "live system will *not* be installed to the hard disk.\n\n"
        self.console.msgbox("Installer", text)

        self.installer.execute()
        return "advanced"

    def _shutdown(self, text: str, opt: str) -> str:
        if self.console.yesno(text) == self.OK:
            self.running = False
            cmd = f"shutdown {opt} now"
            fgvt = os.environ.get("FGVT")
            if fgvt:
                cmd = f"chvt {fgvt}; " + cmd
            os.system(cmd)

        return "advanced"

    def _adv_reboot(self) -> str:
        return self._shutdown("Reboot the appliance?", "-r")

    def _adv_shutdown(self) -> str:
        return self._shutdown("Shutdown the appliance?", "-h")

    def _adv_quit(self) -> str:
        if not self.advanced_enabled:
            self.running = False
            return "usage"

        if (
            self.console.yesno("Do you really want to quit?", autosize=True)
            == self.OK
        ):
            self.running = False

        return "advanced"

    _adv_networking = networking
    quit = _adv_quit

    def loop(self, dialog: str | Any | None = "usage") -> None:
        self.running = True
        prev_dialog = dialog
        standalone = dialog != "usage"  # no "back" for plugins

        while dialog and self.running:
            try:
                if not dialog.startswith(PLUGIN_PATH):
                    try:
                        method = getattr(self, dialog)
                    except AttributeError:
                        raise ConfconsoleError(
                            f"dialog not supported: {dialog}"
                        )
                else:
                    try:
                        method = self.pluginManager.path_map[dialog].run
                    except KeyError:
                        raise ConfconsoleError(
                            f"could not find plugin dialog: {dialog}"
                        )

                new_dialog = method()
                if standalone:  # XXX This feels dirty
                    break
                prev_dialog = dialog
                dialog = new_dialog

            except Exception:  # TODO should only catch specific errors
                sio = StringIO()
                traceback.print_exc(file=sio)

                self.console.msgbox("Caught exception", sio.getvalue())
                dialog = prev_dialog


def main() -> None:
    interactive = True
    advanced_enabled = True
    plugin_name = None

    if os.geteuid() != 0:
        fatal("confconsole needs root privileges to run")

    try:
        l_opts = ["help", "usage", "nointeractive", "plugin="]
        opts, _ = getopt.gnu_getopt(sys.argv[1:], "hn", l_opts)
    except getopt.GetoptError as e:
        usage(e)

    for opt, val in opts:
        if opt in ("-h", "--help"):
            usage()
        elif opt == "--usage":
            advanced_enabled = False
        elif opt == "--nointeractive":
            interactive = False
        elif opt == "--plugin":
            plugin_name = val
        else:
            usage()

    em = plugin.EventManager()
    pm = plugin.PluginManager(
        PLUGIN_PATH, {"eventManager": em, "interactive": interactive}
    )

    if plugin_name:
        ps = list(
            filter(
                lambda x: isinstance(x, plugin.Plugin),
                pm.getByName(plugin_name),
            )
        )

        if len(ps) > 1:
            fatal(f"plugin name ambiguous, matches all of {ps}")
        elif len(ps) == 1:
            p = ps[0]

            if interactive:
                tc = TurnkeyConsole(pm, em, advanced_enabled)
                tc.loop(dialog=p.path)  # calls .run()
            else:
                assert isinstance(p, plugin.Plugin)
                p.module.run()
        else:
            fatal("no such plugin")
    else:
        tc = TurnkeyConsole(pm, em, advanced_enabled)
        tc.loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        subprocess.run(["stty", "sane"])
        traceback.print_exc()
