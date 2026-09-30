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
    " localhost is not an IPv6 name. The primary's own screen shows the"
    " address, and the password asked for next.\n\n"
    + keelcli.NO_FAILOVER
)


def run():
    answers = dbscreen.ask(
        console, TITLE, TEXT,
        [
            ("Replicate from (address)", "host", 26, 42),
            ("Port (blank: default)", "port", 26, 42),
            ("Answer on (addresses)", "listen", 26, 42),
        ],
    )
    if answers is None:
        return
    server = keelcli.replica_server(
        answers["engine"], answers["listen"],
        answers["host"], answers["port"], answers["secret"],
    )
    password = dbscreen.replica_password(
        console, TITLE, dbscreen.secret_path(server)
    )
    if password is None:
        return
    question = keelcli.replica_warning(answers["host"].strip())
    if console.yesno(question, autosize=True) != "ok":
        return
    dbscreen.apply_mode(
        console, TITLE, server, may_destroy=True, password=password
    )
