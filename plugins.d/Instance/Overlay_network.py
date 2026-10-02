"""WireGuard mesh: this node's key, address, peers"""

import wgscreen
from wgcli import TITLE  # noqa: F401 (the title the menu tests read)


def run():
    wgscreen.run(console)
