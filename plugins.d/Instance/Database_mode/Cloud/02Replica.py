"""Replica: this node replicates from another"""

import dbscreen
import keelcli

TITLE = "Cloud: replica"
TEXT = (
    "This node replicates from another. A replica is a COPY of its"
    " primary, so making this node one REPLACES the database it holds"
    " now. keel refuses unless this server holds nothing of its own, and"
    " asks before it destroys anything.\n\n"
    "Give the primary's literal IPv6 address, never a name: on Debian"
    " localhost is not an IPv6 name. The password file is the one the"
    " primary's own screen names, with the same value on both.\n\n"
    + keelcli.NO_FAILOVER
)


def run():
    answers = dbscreen.ask(
        console, TITLE, TEXT,
        [
            ("Replicate from (address)", "host", 26, 42),
            ("Port (blank: default)", "port", 26, 42),
            ("Answer on (addresses)", "listen", 26, 42),
            ("Replication password file", "secret", 26, 42),
        ],
    )
    if answers is None:
        return
    dbscreen.apply_mode(
        console, TITLE,
        keelcli.replica_server(
            answers["engine"], answers["listen"],
            answers["host"], answers["port"], answers["secret"],
        ),
        may_destroy=True,
    )
