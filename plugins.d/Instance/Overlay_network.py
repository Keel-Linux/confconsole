"""Overlay network (WireGuard): this node's key, address and peers"""

import wgscreen
from wgcli import TITLE  # noqa: F401 (the title the menu tests read)


def run():
    wgscreen.run(console)
