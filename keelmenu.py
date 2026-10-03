"""Which Keel screens this machine shows, read from its appliance manifest.

Handbook decision 0041: the appliance manifests under
/usr/share/keel/{appliances,overlays} say which overlays an appliance's
chain carries and which data services it has, and the instance spec
says which installation mode chose its defaults (``installation.mode``).
A screen that configures something the chain does not carry is not
offered: Keel Web and Keel Core have no database, so they have no
Database mode screen.

The chain is resolved by keel itself (``keel.manifest.facts.gather``,
what ``keel spec validate`` and ``keel manifest show --resolved`` use),
so confconsole holds no second copy of the resolution rules.

The rules, by the entry's path under plugins.d:

- Instance/Database_mode: a data service of DATA_ENGINES in the chain,
  an overlay that provides that engine or a service the application
  consumes, or a server the spec declares (database.server).
- Instance/Database_mode/Cloud: only for an engine whose replication
  keel applies (REPLICATING_ENGINES). keel validates primary and
  replica for every engine but converges MariaDB's alone; for Redis and
  PostgreSQL it notes that and changes nothing, so their Database mode
  offers Standalone only rather than roles nothing would make.
- Instance/Overlay_network.py: the wireguard overlay in the chain. It is
  in the Instance menu in the cloud modes, where joining nodes is the
  point; in a simple installation it is behind Advanced, configured or
  not. Its place follows the installation mode alone, so it does not
  move when the first address or peer is applied (it did, and Advanced
  went with it: the maintainer took it for gone, 2026-10-03).
- Instance/Keel_Cloud.py: hidden until Keel Cloud exists, which is when
  CLOUD_ENDPOINT holds the endpoint of the service: one https URL with a
  host (a bracketed IPv6 literal allowed), in a regular file root owns
  and neither group nor others can write. Anything else keeps it hidden
  and is logged. Nothing writes that file yet; the screen, its tests and
  its first boot step stay, and writing the file turns them on.

Every other entry is shown. Where the chain cannot be read (no keel, no
appliance manifest, as on every machine of before 0041, or a spec that
names no appliance) the screens are offered as they were, the overlay
behind Advanced: hiding a screen a machine needs is worse than offering
one that says it has nothing to configure.
"""

import logging
import os
import stat
from dataclasses import dataclass
from urllib.parse import urlsplit

import keelcli

log = logging.getLogger("keelmenu")

HERE = os.path.dirname(os.path.realpath(__file__))
PLUGINS = os.path.join(HERE, "plugins.d")
ROOT = "/"
CLOUD_ENDPOINT = "/etc/keel/cloud-endpoint"
CLOUD_OWNER = 0
CLOUD_SCHEME = "https"
CLOUD_MODES = ("cloud_simple", "cloud_advanced")
# The data services Database mode configures: adding an engine (mongodb,
# couchdb) is one entry here
DATA_ENGINES = frozenset({"mariadb", "postgresql", "redis"})
# Those whose primary and replica keel applies, not only validates
REPLICATING_ENGINES = frozenset({"mariadb"})
WIREGUARD = "wireguard"
OK = "ok"

SHOW = "show"
ADVANCED = "advanced"
HIDE = "hide"

ADVANCED_TAG = "Advanced"
ADVANCED_ITEM = (ADVANCED_TAG, "Screens for a set of nodes")
ADVANCED_TEXT = (
    "Screens a simple installation does not need: they join this node"
    " to others.\n"
)
OVERLAY_NAME = "Overlay network"


@dataclass(frozen=True)
class Chain:
    """What the resolved chain carries"""

    overlays: frozenset
    engines: frozenset


@dataclass(frozen=True)
class Machine:
    """The chain (None when it cannot be read) and the spec's choices"""

    chain: Chain | None
    mode: str
    server_engine: str = ""
    has_server: bool = False


def _engines(resolved) -> frozenset:
    found = set()
    for state in resolved.overlays:
        found.add((state.manifest.get("provides") or {}).get("engine"))
    application = resolved.application
    services = (application.item.get("services") or {}) if application else {}
    for service in services.values():
        engine = service.get("engine")
        found.update(engine if isinstance(engine, list) else [engine])
    found.discard(None)
    return frozenset(found)


def chain_of(name: str, root: str = ROOT) -> Chain | None:
    """The overlays and data engines of the appliance NAME, or None"""
    try:
        from keel.manifest.facts import gather
    except ImportError:
        return None
    try:
        resolved = gather(root, name).resolved
    except Exception:  # a keel that fails is an unknown chain, not a
        return None    # menu that cannot open
    if resolved is None:
        return None
    return Chain(frozenset(state.name for state in resolved.overlays),
                 _engines(resolved))


def _section(document: dict, key: str) -> dict:
    found = document.get(key)
    return found if isinstance(found, dict) else {}


def machine() -> Machine:
    """This machine, as its spec and its manifests describe it"""
    document, _ = keelcli.load_description(keelcli.spec_path())
    name = _section(document, "appliance").get("name")
    chain = chain_of(name) if name else None
    mode = str(_section(document, "installation").get("mode") or "")
    server = keelcli.server_of(document)
    return Machine(chain, mode, str(server.get("engine") or ""),
                   bool(server))


def replicates(engine: str) -> bool:
    """Whether keel applies a primary and a replica of `engine`"""
    return engine in REPLICATING_ENGINES


def _read(path: str) -> str:
    with open(path) as fob:
        return fob.read()


def endpoint_problem(path: str) -> str:
    """Why `path` does not turn Keel Cloud on, or "" when it does"""
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return "not a regular file"
        if info.st_uid != CLOUD_OWNER:
            return "not owned by root"
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return "writable by group or others"
        words = _read(path).split()
    except OSError as error:
        return error.strerror or str(error)
    if len(words) != 1:
        return "must hold one URL" if words else "empty"
    try:
        url = urlsplit(words[0])
        url.port  # a port out of range raises here
    except ValueError as error:
        return f"not a URL: {error}"
    if url.scheme != CLOUD_SCHEME:
        return f"must be an {CLOUD_SCHEME} URL"
    if not url.hostname:
        return "no host in the URL"
    return ""


def cloud_available() -> bool:
    """Whether Keel Cloud exists for this node: a valid endpoint is set.
    No file is the default and is quiet; a file that does not hold a
    valid endpoint keeps Keel Cloud hidden and says why in the log."""
    if not os.path.lexists(CLOUD_ENDPOINT):
        return False
    problem = endpoint_problem(CLOUD_ENDPOINT)
    if problem:
        log.warning("Keel Cloud stays hidden: %s: %s", CLOUD_ENDPOINT,
                    problem)
        return False
    return True


def _database(found: Machine) -> str:
    if (found.chain is None or found.has_server
            or found.chain.engines & DATA_ENGINES):
        return SHOW
    return HIDE


def _replication(found: Machine) -> str:
    if found.chain is None or replicates(found.server_engine) or (
            found.chain.engines & REPLICATING_ENGINES):
        return SHOW
    return HIDE


def _overlay(found: Machine) -> str:
    if found.chain is not None and WIREGUARD not in found.chain.overlays:
        return HIDE
    if found.mode in CLOUD_MODES:
        return SHOW
    return ADVANCED


def _cloud(found: Machine) -> str:
    return SHOW if cloud_available() else HIDE


RULES = {
    os.path.join("Instance", "Database_mode"): _database,
    os.path.join("Instance", "Database_mode", "Cloud"): _replication,
    os.path.join("Instance", "Overlay_network.py"): _overlay,
    os.path.join("Instance", "Keel_Cloud.py"): _cloud,
}


def _key(path: str) -> str:
    return os.path.relpath(path, PLUGINS)


def place(path: str, found: Machine) -> str:
    """SHOW, ADVANCED or HIDE for the entry at `path`"""
    rule = RULES.get(_key(path))
    return rule(found) if rule else SHOW


def arrange(plugins: list, machine_of=machine) -> tuple[list, list]:
    """The entries of one menu: those shown, those behind Advanced

    The machine is read only for a menu that holds a Keel screen.
    """
    if not any(_key(one.path) in RULES for one in plugins):
        return list(plugins), []
    found = machine_of()
    shown, behind = [], []
    for one in plugins:
        where = place(one.path, found)
        if where == SHOW:
            shown.append(one)
        elif where == ADVANCED:
            behind.append(one)
    return shown, behind


def advanced(console, items: list, paths: dict, back: str) -> str:
    """The Advanced menu: the path of the screen chosen, else `back`"""
    code, choice = console.menu(ADVANCED_TAG, ADVANCED_TEXT, items)
    if code != OK:
        return back
    return paths[choice]


def overlay_where() -> str:
    """Where the overlay screen is in the Instance menu, as a path"""
    if _overlay(machine()) == ADVANCED:
        return f"{ADVANCED_TAG} > {OVERLAY_NAME}"
    return OVERLAY_NAME
