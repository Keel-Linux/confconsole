"""One server, replicating nothing"""

import dbscreen
import keelcli

TITLE = "Database mode: standalone"
TEXT = (
    "One server, which is what this appliance is by default. It"
    " replicates nothing and nothing replicates from it.\n\n"
    + keelcli.THIS_NODE
)


def run():
    answers = dbscreen.ask(
        console, TITLE, TEXT,
        [("Answer on (addresses)", "listen", 22, 46)],
    )
    if answers is None:
        return
    dbscreen.apply_mode(
        console, TITLE,
        keelcli.standalone_server(answers["engine"], answers["listen"]),
    )
