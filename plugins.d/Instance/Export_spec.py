"""Export a spec from this machine (keel inspect)"""

import keelcli

TITLE = "Export instance spec"


def run():
    ret, output = console.inputbox(
        TITLE, "Write the spec to this file:", keelcli.DEFAULT_EXPORT
    )
    output = output.strip()
    if ret != "ok" or not output:
        return
    report = keelcli.report_path(output)
    argv = ["inspect", "--output", output, "--report", report]
    try:
        result = keelcli.call(argv)
    except keelcli.KeelNotInstalled as error:
        console.msgbox(TITLE, str(error))
        return
    text = keelcli.export_text(
        output, report, keelcli.read_text(report), result
    )
    console.msgbox(TITLE, text, autosize=True)
