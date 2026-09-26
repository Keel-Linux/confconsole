"""The keel client the Instance menu uses, without a keel command.

`call` is exercised with `subprocess.run` replaced; everything else is a
pure function over its result: the exit code messages, the drift table
rendered from the JSON document `keel diff --format json` prints, and the
texts the four screens show.
"""

import json
import subprocess

import pytest

import keelcli

SPEC = "/etc/keel/instance.yaml"

DIFF_DOCUMENT = {
    "spec": SPEC,
    "root": "/",
    "fields": [
        {
            "field": "instance.hostname",
            "section": "instance",
            "status": "same",
            "declared": "blog",
            "observed": "blog",
            "reason": "",
        },
        {
            "field": "instance.fqdn",
            "section": "instance",
            "status": "drift",
            "declared": "blog.example.org",
            "observed": "shop.example.org",
            "reason": "",
        },
        {
            "field": "network.nameservers",
            "section": "network",
            "status": "same",
            "declared": ["2001:db8:1::53", "2001:db8:1::54"],
            "observed": ["2001:db8:1::53", "2001:db8:1::54"],
            "reason": "",
        },
        {
            "field": "tls.acme.enabled",
            "section": "tls",
            "status": "same",
            "declared": True,
            "observed": True,
            "reason": "",
        },
        {
            "field": "security.updates",
            "section": "security",
            "status": "unknown",
            "declared": "force",
            "observed": None,
            "reason": "/etc/cron-apt/config permission denied (root only)",
        },
        {
            "field": "secrets",
            "section": "secrets",
            "status": "not compared",
            "declared": None,
            "observed": None,
            "reason": "values are never read, on either side",
        },
    ],
    "counts": {
        "same": 3,
        "drift": 1,
        "unknown": 1,
        "not_declared": 0,
        "not_compared": 1,
    },
    "drift": True,
    "incomplete": True,
    "exit_code": 14,
}


def result(code=0, stdout="", stderr="", argv=("keel", "diff")):
    return keelcli.Result(tuple(argv), code, stdout, stderr)


class TestPaths:
    def test_spec_path_is_the_default_without_the_variable(self, monkeypatch):
        monkeypatch.delenv("KEEL_SPEC", raising=False)

        assert keelcli.spec_path() == SPEC

    def test_spec_path_honours_keel_spec(self, monkeypatch):
        monkeypatch.setenv("KEEL_SPEC", "/root/other.yaml")

        assert keelcli.spec_path() == "/root/other.yaml"

    def test_empty_keel_spec_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("KEEL_SPEC", "")

        assert keelcli.spec_path() == SPEC

    def test_report_path_replaces_the_extension(self):
        assert (
            keelcli.report_path("/root/instance.yaml")
            == "/root/instance.report.txt"
        )

    def test_report_path_without_an_extension(self):
        assert keelcli.report_path("/root/spec") == "/root/spec.report.txt"


class TestCall:
    def test_runs_keel_as_an_argv_list_capturing_both_streams(
        self, monkeypatch
    ):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            seen["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, 14, "out\n", "err\n")

        monkeypatch.setattr(keelcli.subprocess, "run", fake_run)

        got = keelcli.call(["diff", "--format", "json"])

        assert seen["command"] == ["keel", "diff", "--format", "json"]
        assert seen["kwargs"] == {
            "capture_output": True,
            "text": True,
            "check": False,
        }
        assert got == keelcli.Result(
            ("keel", "diff", "--format", "json"), 14, "out\n", "err\n"
        )

    def test_a_missing_keel_raises_one_clear_message(self, monkeypatch):
        def fake_run(command, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", "keel")

        monkeypatch.setattr(keelcli.subprocess, "run", fake_run)

        with pytest.raises(keelcli.KeelNotInstalled) as raised:
            keelcli.call(["spec", "validate"])

        assert str(raised.value) == keelcli.NOT_INSTALLED
        assert raised.value.__cause__ is None

    def test_result_command_and_output(self):
        got = result(3, "line one\n", "Error: bad\n", ("keel", "spec"))

        assert got.command == "keel spec"
        assert got.output == "line one\nError: bad"


class TestDescribeExit:
    @pytest.mark.parametrize(
        "command, code, message",
        [
            ("validate", 0, "the spec is valid"),
            ("apply", 0, "the spec was applied"),
            ("apply", 1, "usage error: keel rejected an option or argument"),
            (
                "apply",
                2,
                "the spec file cannot be read or is not valid YAML",
            ),
            (
                "apply",
                3,
                "the spec is valid YAML but fails validation; every error"
                " is listed above",
            ),
            (
                "apply",
                4,
                "a referenced secret is missing or is readable by somebody"
                " other than its owner",
            ),
            ("apply", 5, "the conf file cannot be written"),
            ("diff", 0, "no drift: every declared field matches the machine"),
            (
                "diff",
                13,
                "no drift, but some declared fields could not be observed",
            ),
            (
                "diff",
                14,
                "drift found: at least one declared field differs on the"
                " machine",
            ),
            (
                "inspect",
                0,
                "spec written; every required field was inferred",
            ),
            ("inspect", 5, "the spec or the report could not be written"),
            (
                "inspect",
                13,
                "spec written, but some fields could not be inferred and"
                " need editing; see the report",
            ),
        ],
    )
    def test_known_codes(self, command, code, message):
        assert (
            keelcli.describe_exit(command, code)
            == f"keel {command}: exit {code}, {message}"
        )

    def test_a_code_without_a_message_is_still_reported(self):
        assert (
            keelcli.describe_exit("diff", 9)
            == "keel diff: exit 9, keel exited with code 9"
        )

    def test_an_unknown_command_uses_the_common_table(self):
        assert (
            keelcli.describe_exit("verify", 0) == "keel verify: exit 0, done"
        )


class TestReadText:
    def test_returns_the_file_text(self, tmp_path):
        path = tmp_path / "instance.yaml"
        path.write_text("version: 1\n")

        assert keelcli.read_text(str(path)) == "version: 1\n"

    def test_an_unreadable_file_becomes_one_line(self, tmp_path):
        path = tmp_path / "missing.yaml"

        assert (
            keelcli.read_text(str(path))
            == f"{path}: No such file or directory"
        )


class TestRenderDiff:
    @pytest.mark.parametrize(
        "value, cell",
        [
            (None, "-"),
            (True, "true"),
            (False, "false"),
            (["2001:db8::53", "2001:db8::54"], "2001:db8::53, 2001:db8::54"),
            ("blog", "blog"),
            (64, "64"),
        ],
    )
    def test_format_value(self, value, cell):
        assert keelcli.format_value(value) == cell

    def test_clip_keeps_a_short_cell(self):
        assert keelcli.clip("2001:db8:1::10/64") == "2001:db8:1::10/64"

    def test_clip_cuts_a_long_cell_to_the_width_with_an_ellipsis(self):
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGFiOSxekesBapFyo96U"

        clipped = keelcli.clip(key)

        assert len(clipped) == keelcli.MAX_CELL
        assert clipped == key[:37] + "..."

    def test_rows_clip_declared_and_observed_but_not_the_field(self):
        long_field = "network.interfaces.eth0.ipv6.address.much.longer.than"
        rows = keelcli.diff_rows(
            [
                {
                    "field": long_field,
                    "status": "same",
                    "declared": ["a" * 30, "b" * 30],
                    "observed": ["a" * 30, "b" * 30],
                }
            ]
        )

        assert rows[0][0] == long_field
        assert rows[0][2] == "a" * 30 + ", " + "b" * 5 + "..."
        assert rows[0][3] == rows[0][2]

    def test_rows_show_the_reason_where_nothing_was_observed(self):
        rows = keelcli.diff_rows(DIFF_DOCUMENT["fields"])

        assert rows[4] == (
            "security.updates",
            "unknown",
            "force",
            "/etc/cron-apt/config permission denie...",
        )
        assert rows[5] == (
            "secrets",
            "not compared",
            "-",
            "values are never read, on either side",
        )

    def test_rows_without_a_reason_keep_the_dash(self):
        rows = keelcli.diff_rows(
            [{"field": "x", "status": "unknown", "declared": "a"}]
        )

        assert rows == [("x", "unknown", "a", "-")]

    def test_rows_tolerate_a_field_without_keys(self):
        assert keelcli.diff_rows([{}]) == [("-", "-", "-", "-")]

    def test_align_pads_every_column_to_its_widest_cell(self):
        lines = keelcli.align([("a", "bb", "c"), ("dddd", "e", "f")])

        assert lines == ["a     bb  c", "dddd  e   f"]

    def test_summary_words_the_counts_like_keel(self):
        assert keelcli.summary(DIFF_DOCUMENT) == (
            "diff: 3 same, 1 drift, 1 unknown, 0 not declared,"
            " 1 not compared; drift found"
        )

    def test_summary_without_counts_reads_zero_and_no_drift(self):
        assert keelcli.summary({}) == (
            "diff: 0 same, 0 drift, 0 unknown, 0 not declared,"
            " 0 not compared; no drift"
        )

    def test_render_diff_is_a_table_then_the_summary(self):
        lines = keelcli.render_diff(json.dumps(DIFF_DOCUMENT))

        assert lines[0].split() == ["field", "status", "declared", "observed"]
        assert lines[1].startswith("instance.hostname")
        assert "same" in lines[1] and "blog" in lines[1]
        assert lines[2].startswith("instance.fqdn")
        assert "shop.example.org" in lines[2]
        assert "2001:db8:1::53, 2001:db8:1::54" in lines[3]
        assert lines[4].endswith("true")
        assert lines[-2] == ""
        assert lines[-1].endswith("drift found")
        assert len(lines) == 1 + len(DIFF_DOCUMENT["fields"]) + 2

    def test_render_diff_rejects_text_that_is_not_json(self):
        with pytest.raises(ValueError):
            keelcli.render_diff("instance.hostname: same (blog)\n")

    def test_render_diff_rejects_a_document_without_fields(self):
        with pytest.raises(ValueError, match="not a keel diff document"):
            keelcli.render_diff('{"spec": "x"}')

    def test_render_diff_rejects_a_json_list(self):
        with pytest.raises(ValueError, match="not a keel diff document"):
            keelcli.render_diff("[1, 2]")


class TestScreens:
    def test_view_text_shows_the_file_then_the_validation(self):
        got = result(
            0,
            f"{SPEC}: ok (secret files not checked)\n",
            "",
            ("keel", "spec", "validate", "--no-secret-files", "--spec", SPEC),
        )

        text = keelcli.view_text(SPEC, "version: 1\n", got)

        assert text == (
            f"{SPEC}\n\nversion: 1\n\n"
            f"$ keel spec validate --no-secret-files --spec {SPEC}\n"
            f"{SPEC}: ok (secret files not checked)\n\n"
            "keel validate: exit 0, the spec is valid"
        )

    def test_apply_text_shows_output_and_verdict(self):
        got = result(
            4,
            "",
            "Error: secret root_password: file missing\n",
            ("keel", "spec", "apply", "--non-interactive"),
        )

        assert keelcli.apply_text(got) == (
            "$ keel spec apply --non-interactive\n"
            "Error: secret root_password: file missing\n\n"
            "keel apply: exit 4, a referenced secret is missing or is"
            " readable by somebody other than its owner"
        )

    def test_drift_text_renders_the_table_when_there_is_json(self):
        got = result(14, json.dumps(DIFF_DOCUMENT))

        text = keelcli.drift_text(got)

        assert text.startswith("field")
        assert "\ndiff: 3 same, 1 drift" in text
        assert text.endswith(
            "\n\nkeel diff: exit 14, drift found: at least one declared"
            " field differs on the machine"
        )

    def test_drift_text_falls_back_to_the_output_without_json(self):
        got = result(2, "", f"Error: {SPEC}: not valid YAML\n")

        assert keelcli.drift_text(got) == (
            f"Error: {SPEC}: not valid YAML\n\n"
            "keel diff: exit 2, the spec file cannot be read or is not"
            " valid YAML"
        )

    def test_drift_text_for_an_absent_spec(self):
        got = result(0, "", f"{SPEC}: not found, nothing to do\n")

        assert keelcli.drift_text(got) == (
            f"{SPEC}: not found, nothing to do\n\n"
            "keel diff: exit 0, no drift: every declared field matches"
            " the machine"
        )

    def test_export_text_names_both_files_then_the_report(self):
        got = result(13, "", "", ("keel", "inspect"))

        text = keelcli.export_text(
            "/root/instance.yaml",
            "/root/instance.report.txt",
            "instance.hostname: /etc/hostname\napp.email: not inferred\n",
            got,
        )

        assert text == (
            "spec: /root/instance.yaml\nreport: /root/instance.report.txt\n\n"
            "instance.hostname: /etc/hostname\napp.email: not inferred\n\n"
            "keel inspect: exit 13, spec written, but some fields could not"
            " be inferred and need editing; see the report"
        )
