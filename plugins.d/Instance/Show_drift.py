"""Show drift between the spec and this machine"""

import keelcli

TITLE = "Instance drift"


def run():
    argv = ["diff", "--spec", keelcli.spec_path(), "--format", "json"]
    try:
        result = keelcli.call(argv)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(TITLE, str(error))
        return
    console.msgbox(TITLE, keelcli.drift_text(result), autosize=True)
