"""View the instance spec and its validation report"""

import keelcli

TITLE = "Instance spec"


def run():
    path = keelcli.spec_path()
    argv = ["spec", "validate", "--no-secret-files", "--spec", path]
    try:
        result = keelcli.call(argv)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(TITLE, str(error))
        return
    spec = keelcli.read_text(path)
    console.msgbox(TITLE, keelcli.view_text(path, spec, result), autosize=True)
