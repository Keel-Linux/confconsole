"""Apply the instance spec to this machine"""

import keelcli

TITLE = "Apply instance spec"


def run():
    path = keelcli.spec_path()
    argv = ["spec", "apply", "--spec", path, "--non-interactive"]
    question = (
        f"Apply {path} to this machine?\n\n"
        f"Headless equivalent: keel {' '.join(argv)}"
    )
    if console.yesno(question, autosize=True) != "ok":
        return
    try:
        result = keelcli.call(argv)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(TITLE, str(error))
        return
    console.msgbox(TITLE, keelcli.apply_text(result), autosize=True)
