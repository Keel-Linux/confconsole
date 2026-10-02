"""Make this replica the primary"""

import dbscreen
import keelcli

TITLE = "Cloud: promote this replica"
QUESTION = (
    "Promote THIS node to a primary?\n\n"
    "It stops replicating and forgets the primary it followed. Nothing"
    " here stops the old primary or tells any other machine, so if the"
    " old primary is still running you will have two writable servers"
    " holding one dataset, and the writes they take will diverge.\n\n"
    "Only do this when you know the old primary is gone.\n\n"
    "Afterwards the description still says replica while the machine"
    " says primary, which keel diff reports as drift. Change the"
    " description with the Primary screen to settle it.\n\n"
    + keelcli.NO_FAILOVER
)


def run():
    if console.yesno(QUESTION, autosize=True) != "ok":
        return
    result = dbscreen.call(console, TITLE, ["database", "promote"])
    if result is None:
        return
    console.msgbox(TITLE, keelcli.promote_text(result), autosize=True)
