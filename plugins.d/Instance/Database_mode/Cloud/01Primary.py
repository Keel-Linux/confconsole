"""Primary: other nodes may replicate from this one"""

import dbscreen
import keelcli

TITLE = "Cloud: primary"
TEXT = (
    "Other nodes replicate from this one. This screen sets what THIS"
    " node holds: the addresses it answers on and the origins it allows"
    " to replicate from it. Give each replica's address. An empty field"
    " offers the addresses of every overlay peer, replica or not, so"
    " remove any that is not one. MariaDB matches the text of a"
    " replica's address, which can leave out zero groups, so keel"
    " refuses a prefix such as the overlay /64 that it cannot hold"
    " exactly. A name is accepted and is fragile: it fails quietly when"
    " DNS does.\n\n"
    "Once it is configured, this screen shows what each replica needs:"
    " the address to replicate from, the account and where the password"
    " is kept, and offers to generate that password.\n\n"
    "A primary holds authorizations, not replicas. Nothing here creates"
    " a replica anywhere.\n\n" + keelcli.THIS_NODE + "\n\n"
    + keelcli.NO_FAILOVER
)


def run():
    answers = dbscreen.ask(
        console, TITLE, TEXT,
        [
            ("Answer on (addresses)", "listen", 24, 44),
            ("Allow replication from", "allowed_from", 24, 44),
            ("Replication password file", "secret", 24, 44),
        ],
        offer_addresses=True,
    )
    if answers is None:
        return
    server = keelcli.primary_server(
        answers["engine"], answers["listen"],
        answers["allowed_from"], answers["secret"],
    )
    secret = dbscreen.secret_path(server)
    password = dbscreen.primary_password(console, TITLE, secret)
    if password is None:
        return
    result = dbscreen.apply_mode(console, TITLE, server, password=password)
    if result is None:
        return
    where = keelcli.reachable(
        server.get("listen") or [], dbscreen.local_addresses()
    )
    failure = ""
    if result.code != keelcli.OK:
        failure = keelcli.describe_exit("apply", result.code)
    dbscreen.show_secret(
        console, TITLE,
        keelcli.handout_text(
            answers["engine"], where, secret, password,
            origins=server["replication"]["allowed_from"], failure=failure,
        ),
    )
