"""Show drift between the spec and this machine"""

import keelcli
import keelfit

TITLE = "Instance drift"


def run():
    argv = ["diff", "--spec", keelcli.spec_path(), "--format", "json"]
    try:
        result = keelcli.call(argv)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(TITLE, str(error))
        return
    width = keelfit.text_width(keelfit.room())
    console.msgbox(TITLE, keelcli.drift_text(result, width), autosize=True)
