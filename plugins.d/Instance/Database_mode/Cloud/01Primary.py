"""Primary: other nodes may replicate from this one"""

import dbscreen
import keelcli

TITLE = "Cloud: primary"
TEXT = (
    "Other nodes replicate from this one. This screen sets what THIS"
    " node holds: the addresses it answers on and the origins it allows"
    " to replicate from it. A prefix is the form to prefer, because with"
    " IPv6 and no NAT the /64 a fleet lives on is stable where a single"
    " address goes stale on every rebuild. A name is accepted and is"
    " fragile: it fails quietly when DNS does.\n\n"
    "A primary holds authorizations, not replicas. Nothing here creates"
    " a replica anywhere.\n\n" + keelcli.NO_FAILOVER
)


def run():
    answers = dbscreen.ask(
        console, TITLE, TEXT,
        [
            ("Answer on (addresses)", "listen", 24, 44),
            ("Allow replication from", "allowed_from", 24, 44),
            ("Replication password file", "secret", 24, 44),
        ],
    )
    if answers is None:
        return
    dbscreen.apply_mode(
        console, TITLE,
        keelcli.primary_server(
            answers["engine"], answers["listen"],
            answers["allowed_from"], answers["secret"],
        ),
    )
