"""The Let's Encrypt screen is driven by the instance description.

Its domain boxes are prefilled from tls.acme.domains, else instance.fqdn
(the name the first boot recorded, Keel-Linux/inithooks#36), else from
dehydrated's domains file as before, example.com on a fresh machine. When
the operator confirms the domains and the certificate is issued, the
description gets tls.acme.domains and tls.acme.enabled: true, written as
every Instance screen writes it (keelcli: staged, validated by keel,
moved into place); a request that fails writes nothing to it. dehydrated
still reads its domains file, which is kept as it was.

The plugin is loaded the way confconsole loads it, with the scripted fake
console of conftest; requests, dehydrated-wrapper and keel are replaced,
and every path is under tmp_path.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

import keelbanner
import keelcli
import keelfit
import plugin
from conftest import FakeConsole

ROOT = Path(__file__).resolve().parent.parent
SCREEN = ROOT / "plugins.d" / "Lets_Encrypt" / "get_certificate.py"
SHARE = ROOT / "share" / "letsencrypt"
TOS = "https://letsencrypt.example/terms"
FQDN = "blog.example.org"
FIVE = [FQDN, "", "", "", ""]
EXAMPLE = ["example.com", "", "", "", ""]


class FakeResponse:
    def json(self):
        return {"meta": {"termsOfService": TOS}}


@pytest.fixture
def spec(tmp_path, monkeypatch):
    """A description KEEL_SPEC points at; call it to write one"""
    path = tmp_path / "instance.yaml"
    monkeypatch.setenv("KEEL_SPEC", str(path))

    def _write(document):
        path.write_text(yaml.safe_dump(document, sort_keys=False))
        return path

    _write.path = path
    return _write


@pytest.fixture
def screen(tmp_path, monkeypatch):
    """The plugin with dehydrated's files under tmp_path, Let's Encrypt
    answering its terms, and dehydrated-wrapper a recorded stand-in
    exiting `state["status"]`"""
    loaded = plugin.Plugin(str(SCREEN))
    module = loaded.module
    etc = tmp_path / "dehydrated"
    etc.mkdir()
    monkeypatch.setattr(module, "dehydrated_conf", str(etc))
    monkeypatch.setattr(module, "domain_path",
                        str(etc / "confconsole.domains.txt"))
    monkeypatch.setattr(module, "d_conf_path", str(etc / "confconsole.config"))
    monkeypatch.setattr(module, "d_conf_example",
                        str(SHARE / "dehydrated-confconsole.config"))
    monkeypatch.setattr(module, "d_dom_example",
                        str(SHARE / "dehydrated-confconsole.domains"))
    monkeypatch.setattr(module.requests, "get", lambda url: FakeResponse())
    state = {"status": 0, "runs": [], "etc": etc, "module": module}

    def run(argv, **kwargs):
        state["runs"].append(list(argv))
        return subprocess.CompletedProcess(argv, state["status"], "",
                                           "challenge failed")

    monkeypatch.setattr(module.subprocess, "run", run)
    return state


def read(path):
    return yaml.safe_load(Path(path).read_text())


def domains_file(state):
    return (state["etc"] / "confconsole.domains.txt").read_text()


def console(values, more_forms=()):
    """A console answering Yes to the terms, http-01, Yes to the DNS
    warning, VALUES in the domain boxes and Yes to overwriting"""
    return FakeConsole(forms=[("ok", list(values)), *more_forms],
                       yesno=["ok", "ok", "ok", "ok"],
                       menus=[("ok", "http-01")])


def run_screen(state, fake):
    state["module"].console = fake
    state["module"].run()
    return fake


class TestWhatTheDescriptionSays:
    """keelcli: the domains a description offers, and the one written"""

    def test_declared_acme_domains_come_first(self):
        document = {"instance": {"fqdn": FQDN},
                    "tls": {"acme": {"domains": ["www.example.org", FQDN]}}}

        assert keelcli.acme_domains(document) == ["www.example.org", FQDN]

    def test_the_fqdn_when_no_domain_is_declared(self):
        for tls in (None, {}, {"acme": {}}, {"acme": {"domains": []}},
                    {"acme": {"enabled": False}}):
            document = {"instance": {"fqdn": FQDN}}
            if tls is not None:
                document["tls"] = tls
            assert keelcli.acme_domains(document) == [FQDN], tls

    def test_nothing_when_the_description_names_no_domain(self):
        for document in ({}, {"version": 1}, {"instance": {"hostname": "b"}},
                         {"instance": "x"}, {"tls": "x"}, {"tls": {"acme": 1}},
                         {"tls": {"acme": {"domains": "not a list"}}}):
            assert keelcli.acme_domains(document) == [], document

    def test_the_domains_are_strings(self):
        document = {"tls": {"acme": {"domains": [FQDN, 1]}}}

        assert keelcli.acme_domains(document) == [FQDN, "1"]

    def test_with_acme_declares_the_domains_and_turns_acme_on(self):
        document = {"version": 1, "instance": {"fqdn": FQDN}}

        after = keelcli.with_acme(document, [FQDN])

        assert after == {"version": 1, "instance": {"fqdn": FQDN},
                         "tls": {"acme": {"domains": [FQDN], "enabled": True}}}
        assert document == {"version": 1, "instance": {"fqdn": FQDN}}

    def test_with_acme_keeps_the_rest_of_the_section(self):
        document = {"version": 1, "tls": {"acme": {
            "enabled": False, "challenge": "http-01", "agree_tos": True,
            "domains": ["old.example.org"]}}}

        after = keelcli.with_acme(document, [FQDN, "www.example.org"])

        assert after["tls"]["acme"] == {
            "enabled": True, "challenge": "http-01", "agree_tos": True,
            "domains": [FQDN, "www.example.org"]}

    def test_with_acme_replaces_a_section_of_another_shape(self):
        after = keelcli.with_acme({"tls": {"acme": "yes"}}, [FQDN])

        assert after["tls"] == {"acme": {"domains": [FQDN], "enabled": True}}

    def test_bare_domains_drop_blanks_aliases_and_spaces(self):
        values = [" blog.example.org ", "", "www.example.org > alias", " "]

        assert keelcli.bare_domains(values) == [FQDN, "www.example.org"]

    def test_a_wildcard_is_not_recordable(self):
        # keel.spec.fields.LABEL_RE takes no `*`, so keel spec validate
        # would refuse the description and nothing would be recorded
        values = ["*.example.org > star", "example.org", "", "", ""]

        assert keelcli.recordable_domains(values) == (
            ["example.org"], ["*.example.org"])

    def test_the_wildcard_notices_name_the_file(self):
        assert "instance.yaml" in keelcli.ACME_WILDCARDS.format(
            path="/etc/keel/instance.yaml", wildcards="*.x", recorded="x")
        assert "nothing was recorded" in keelcli.ACME_NOTHING_RECORDED


class TestSaveAcme:
    def test_the_description_is_validated_then_written(self, keel, spec):
        spec({"version": 1, "instance": {"hostname": "blog"}})

        problem = keelcli.save_acme(str(spec.path), read(spec.path), [FQDN])

        assert problem == ""
        assert read(spec.path) == {
            "version": 1, "instance": {"hostname": "blog"},
            "tls": {"acme": {"domains": [FQDN], "enabled": True}}}
        assert keel["calls"][0][:3] == ["spec", "validate",
                                        "--no-secret-files"]
        assert keel["calls"][0][4] != str(spec.path)

    def test_a_description_keel_refuses_is_not_written(self, keel, spec):
        spec({"version": 1})
        keel["answers"] = [(3, "", "Error: tls.acme.domains: bad")]

        problem = keelcli.save_acme(str(spec.path), read(spec.path), [FQDN])

        assert "NOT changed" in problem
        assert "tls.acme.domains: bad" in problem
        assert read(spec.path) == {"version": 1}
        assert sorted(spec.path.parent.iterdir()) == [spec.path]

    def test_without_keel_nothing_is_written(self, keel, spec):
        spec({"version": 1})
        keel["answers"] = [keelcli.KeelNotInstalled(keelcli.NOT_INSTALLED)]

        problem = keelcli.save_acme(str(spec.path), read(spec.path), [FQDN])

        assert problem == keelcli.NOT_INSTALLED
        assert read(spec.path) == {"version": 1}
        assert sorted(spec.path.parent.iterdir()) == [spec.path]

    def test_a_file_that_cannot_be_staged_is_said(self, keel, spec):
        path = spec.path.parent / "missing" / "instance.yaml"

        problem = keelcli.save_acme(str(path), {"version": 1}, [FQDN])

        assert "missing" in problem
        assert keel["calls"] == []

    def test_a_file_that_cannot_be_replaced_is_said(self, keel, spec):
        spec.path.mkdir()

        problem = keelcli.save_acme(str(spec.path), {"version": 1}, [FQDN])

        assert "NOT changed" in problem
        assert sorted(spec.path.parent.iterdir()) == [spec.path]


class TestThePrefill:
    """load_domains: the description first, dehydrated's file after it"""

    def test_declared_domains_fill_the_boxes(self, screen, spec):
        spec({"version": 1, "tls": {"acme": {
            "domains": ["www.example.org", FQDN]}}})

        domains, alias = screen["module"].load_domains()

        assert domains == ["www.example.org", FQDN, "", "", ""]
        assert alias is None

    def test_the_fqdn_fills_the_first_box(self, screen, spec):
        spec({"version": 1, "instance": {"hostname": "blog", "fqdn": FQDN}})

        domains, _ = screen["module"].load_domains()

        assert domains == FIVE

    def test_more_than_five_declared_domains_fill_five_boxes(self, screen,
                                                             spec):
        many = [f"d{n}.example.org" for n in range(7)]
        spec({"version": 1, "tls": {"acme": {"domains": many}}})

        domains, _ = screen["module"].load_domains()

        assert domains == many[:5]

    def test_dehydrated_s_file_is_still_made_from_the_example(self, screen,
                                                              spec):
        # dehydrated reads it: the file stays, whatever filled the boxes
        spec({"version": 1, "instance": {"fqdn": FQDN}})

        screen["module"].load_domains()

        assert domains_file(screen) == (
            SHARE / "dehydrated-confconsole.domains").read_text()

    def test_without_a_declared_name_the_file_fills_the_boxes(self, screen,
                                                              spec):
        spec({"version": 1, "instance": {"hostname": "blog"}})
        (screen["etc"] / "confconsole.domains.txt").write_text(
            "# mine\nshop.example.org www.shop.example.org\n")

        domains, alias = screen["module"].load_domains()

        assert domains == ["shop.example.org", "www.shop.example.org",
                           "", "", ""]
        assert alias is None
        assert (screen["etc"] / "confconsole.domains.txt.bak").exists()

    def test_the_file_s_alias_is_kept_beside_declared_domains(self, screen,
                                                              spec):
        spec({"version": 1, "tls": {"acme": {"domains": [FQDN]}}})
        (screen["etc"] / "confconsole.domains.txt").write_text(
            "*.example.org > star_example_org\n")

        domains, alias = screen["module"].load_domains()

        assert domains == FIVE
        assert alias == "star_example_org"

    def test_a_fresh_machine_without_a_description_shows_example_com(
        self, screen, spec
    ):
        domains, _ = screen["module"].load_domains()

        assert domains == EXAMPLE
        assert not spec.path.exists()

    def test_a_description_that_does_not_read_is_no_description(
        self, screen, spec
    ):
        spec.path.write_text("version: [1")

        domains, _ = screen["module"].load_domains()

        assert domains == EXAMPLE


class TestTheScreen:
    """run(): what happens once the operator confirms the domains"""

    def test_an_issued_certificate_is_recorded_in_the_description(
        self, screen, spec, keel
    ):
        spec({"version": 1, "instance": {"hostname": "blog", "fqdn": FQDN},
              "app": {"email": "admin@example.org"}})

        fake = run_screen(screen, console([FQDN, "www.example.org", "", "",
                                           ""]))

        assert read(spec.path) == {
            "version": 1, "instance": {"hostname": "blog", "fqdn": FQDN},
            "app": {"email": "admin@example.org"},
            "tls": {"acme": {"domains": [FQDN, "www.example.org"],
                             "enabled": True}}}
        assert domains_file(screen).splitlines()[3] == (
            f"{FQDN} www.example.org   ")
        assert screen["runs"][0][1:] == [
            str(SCREEN.parent / "dehydrated-wrapper"), "--register",
            "--log-info", "--challenge", "http-01"]
        assert [call for call in fake.calls if call[0] == "msgbox"] == []

    def test_the_boxes_the_operator_saw_came_from_the_description(
        self, screen, spec, keel
    ):
        spec({"version": 1, "instance": {"fqdn": FQDN}})

        fake = run_screen(screen, console(FIVE))

        form = [call for call in fake.calls if call[0] == "form"][0]
        assert [field[3] for field in form[2]] == FIVE
        assert [field[0] for field in form[2]] == [
            "Domain 1", "Domain 2", "Domain 3", "Domain 4", "Domain 5"]

    def test_a_request_that_fails_writes_nothing_to_the_description(
        self, screen, spec, keel
    ):
        spec({"version": 1, "instance": {"fqdn": FQDN}})
        screen["status"] = 1

        fake = run_screen(screen, console(FIVE, more_forms=[("cancel", FIVE)]))

        assert read(spec.path) == {"version": 1, "instance": {"fqdn": FQDN}}
        assert keel["calls"] == []
        assert ("msgbox", "Error!", "challenge failed") in fake.calls
        # dehydrated's file was written, as before: it is what it reads
        assert domains_file(screen).splitlines()[3] == f"{FQDN}    "

    def test_a_description_keel_refuses_is_said_and_left_as_it_was(
        self, screen, spec, keel
    ):
        spec({"version": 1})
        keel["answers"] = [(3, "", "Error: tls.acme.domains: bad")]

        fake = run_screen(screen, console(FIVE))

        assert read(spec.path) == {"version": 1}
        boxes = [call for call in fake.calls if call[0] == "msgbox"]
        assert boxes[0][1] == "Instance description"
        assert "NOT changed" in boxes[0][2]
        assert "tls.acme.domains: bad" in boxes[0][2]
        assert "certificate" in boxes[0][2]

    def test_a_machine_without_a_description_gets_one(self, screen, spec,
                                                      keel):
        run_screen(screen, console(FIVE))

        assert read(spec.path) == {
            "version": 1,
            "tls": {"acme": {"domains": [FQDN], "enabled": True}}}

    def test_aliases_and_blanks_are_not_domains(self, screen, spec, keel):
        spec({"version": 1})

        run_screen(screen, console([FQDN, "", "www.example.org > www", "",
                                    ""]))

        assert read(spec.path)["tls"]["acme"]["domains"] == [
            FQDN, "www.example.org"]

    def test_a_description_that_does_not_read_is_said_not_written(
        self, screen, spec, keel
    ):
        spec.path.write_text("version: [1")

        fake = run_screen(screen, console(FIVE))

        assert spec.path.read_text() == "version: [1"
        boxes = [call for call in fake.calls if call[0] == "msgbox"]
        assert "not valid YAML" in boxes[0][2]

    def test_a_wildcard_is_left_out_and_said(self, screen, spec, keel):
        # the DNS-01 flow confirms the boxes the same way; what reaches
        # the description is decided here
        spec({"version": 1})

        notice = screen["module"].record_domains(
            ["*.example.org > star", "example.org", "", "", ""])

        assert read(spec.path) == {
            "version": 1,
            "tls": {"acme": {"domains": ["example.org"], "enabled": True}}}
        assert "*.example.org" in notice
        assert "not recorded" in notice
        assert "Recorded: example.org" in notice

    def test_a_wildcard_alone_records_nothing_and_says_so(
        self, screen, spec, keel
    ):
        spec({"version": 1})

        notice = screen["module"].record_domains(
            ["*.example.org", "", "", "", ""])

        assert read(spec.path) == {"version": 1}
        assert keel["calls"] == []
        assert "nothing was recorded" in notice
        assert "*.example.org" in notice

    def test_a_cancelled_form_writes_nothing(self, screen, spec, keel):
        spec({"version": 1})

        run_screen(screen, FakeConsole(forms=[("cancel", FIVE)],
                                       yesno=["ok", "ok"],
                                       menus=[("ok", "http-01")]))

        assert read(spec.path) == {"version": 1}
        assert screen["runs"] == []


class TestTheText:
    def test_the_form_fits_an_80_by_24_console(self, screen, monkeypatch):
        # five boxes under the text, the buttons and the frame below them
        rows, cols = keelbanner.available(24, 80)
        inside = cols - keelfit.TEXT_CHROME
        text = screen["module"].DESC
        for line in text.splitlines():
            assert len(line) <= inside, line
        boxes = 5
        assert (keelbanner.text_rows(text + "\n ", inside) + boxes + 1
                + keelbanner.BOX_CHROME) <= rows

    def test_the_text_says_where_the_boxes_come_from(self, screen):
        assert "instance.yaml" in screen["module"].DESC
