"""The database mode screens: what they build, stage, ask and show.

Decision 0013 settled that each screen configures the machine it runs on.
These tests hold the screens to that: the description they write, the
order of stage, validate, commit, apply, and the one question in the menu
whose Yes loses data. No dialog opens and no keel runs.
"""

from pathlib import Path

import pytest
import yaml

import dbscreen
import keelcli
from conftest import BASE, FakeConsole, make_result

PRIMARY_HOST = "2804:710:d0:5:bc:24ff:fe25:b2"
PREFIX = "2804:710:d0:5::/64"
SECRET = "/etc/keel/secrets/replication_password"


@pytest.fixture(autouse=True)
def no_machine_addresses(monkeypatch):
    """The machine is never asked for its addresses by these tests"""
    monkeypatch.setattr(dbscreen, "local_addresses", lambda: [])


class TestWhatTheScreensBuild:
    """The description each role writes, and nothing about anybody else"""

    def test_standalone_names_the_engine_the_role_and_the_addresses(self):
        found = keelcli.standalone_server("mariadb", "::1, 127.0.0.1")

        assert found == {
            "engine": "mariadb",
            "role": "standalone",
            "listen": ["::1", "127.0.0.1"],
        }

    def test_an_empty_listen_field_leaves_the_packaged_setting(self):
        assert "listen" not in keelcli.standalone_server("mariadb", "  ")

    def test_a_primary_holds_authorizations_and_a_credential(self):
        found = keelcli.primary_server(
            "mariadb", "::", f"{PREFIX} 2001:db8::20", SECRET
        )

        assert found["role"] == "primary"
        assert found["replication"] == {
            "allowed_from": [PREFIX, "2001:db8::20"],
            "secret": {"file": SECRET},
        }

    def test_a_primary_names_no_replica_anywhere(self):
        found = keelcli.primary_server("mariadb", "::", PREFIX, SECRET)

        assert "primary" not in found["replication"]

    def test_a_replica_names_the_endpoint_it_replicates_from(self):
        found = keelcli.replica_server(
            "mariadb", "::1", PRIMARY_HOST, "3307", SECRET
        )

        assert found["role"] == "replica"
        assert found["replication"]["primary"] == {
            "host": PRIMARY_HOST, "port": 3307
        }

    def test_a_blank_port_leaves_the_engine_default_to_keel(self):
        found = keelcli.replica_server(
            "mariadb", "::1", PRIMARY_HOST, "  ", SECRET
        )

        assert found["replication"]["primary"] == {"host": PRIMARY_HOST}

    def test_a_port_that_is_not_a_number_is_kept_for_keel_to_refuse(self):
        # The console does not validate; keel does, and the screen shows
        # what it said. A value dropped here would be a value the
        # operator never learns was wrong.
        found = keelcli.replica_server(
            "mariadb", "::1", PRIMARY_HOST, "http", SECRET
        )

        assert found["replication"]["primary"]["port"] == "http"

    def test_the_rest_of_the_description_is_copied_and_not_edited(self):
        document = {"version": 1, "instance": {"hostname": "mariadb"}}

        found = keelcli.with_server(
            document, keelcli.standalone_server("mariadb", "::1")
        )

        assert found["instance"] == {"hostname": "mariadb"}
        assert "database" not in document

    def test_a_client_section_beside_it_survives(self):
        document = {"database": {"client": {"engine": "mariadb"}}}

        found = keelcli.with_server(
            document, keelcli.standalone_server("mariadb", "::1")
        )

        assert found["database"]["client"] == {"engine": "mariadb"}


class TestReadingAndWritingTheDescription:
    def test_a_description_that_is_not_there_says_so(self, tmp_path):
        document, problem = keelcli.load_spec(str(tmp_path / "absent.yaml"))

        assert document == {}
        assert "absent.yaml" in problem

    def test_a_description_that_is_not_yaml_says_so(self, tmp_path):
        path = tmp_path / "instance.yaml"
        path.write_text("database: [\n")

        document, problem = keelcli.load_spec(str(path))

        assert document == {}
        assert "not valid YAML" in problem

    def test_a_description_that_is_not_a_mapping_says_so(self, tmp_path):
        path = tmp_path / "instance.yaml"
        path.write_text("- one\n- two\n")

        _, problem = keelcli.load_spec(str(path))

        assert "not a mapping" in problem

    def test_an_empty_file_reads_as_an_empty_description(self, tmp_path):
        path = tmp_path / "instance.yaml"
        path.write_text("")

        assert keelcli.load_spec(str(path)) == ({}, "")

    def test_a_description_without_the_section_has_no_server(self):
        assert keelcli.server_of({}) == {}
        assert keelcli.server_of({"database": None}) == {}
        assert keelcli.server_of({"database": "nonsense"}) == {}

    def test_staging_writes_beside_the_description_and_not_over_it(
        self, tmp_path
    ):
        path = str(tmp_path / "instance.yaml")
        Path(path).write_text("version: 1\n")

        staged, problem = keelcli.stage_spec({"version": 2}, path)

        assert problem == ""
        assert Path(path).read_text() == "version: 1\n"
        assert yaml.safe_load(Path(staged).read_text()) == {"version": 2}
        assert Path(staged).stat().st_mode & 0o777 == 0o600

    def test_a_staged_description_that_cannot_be_written_says_why(
        self, tmp_path
    ):
        _, problem = keelcli.stage_spec(
            {"version": 1}, str(tmp_path / "nowhere" / "instance.yaml")
        )

        assert "instance.yaml" in problem

    def test_committing_moves_it_into_place(self, tmp_path):
        path = str(tmp_path / "instance.yaml")
        staged, _ = keelcli.stage_spec({"version": 2}, path)

        assert keelcli.commit_spec(staged, path) == ""
        assert yaml.safe_load(Path(path).read_text()) == {"version": 2}

    def test_a_commit_that_cannot_happen_says_why(self, tmp_path):
        problem = keelcli.commit_spec(
            str(tmp_path / "absent"), str(tmp_path / "instance.yaml")
        )

        assert "instance.yaml" in problem

    def test_discarding_removes_it_and_forgives_one_already_gone(
        self, tmp_path
    ):
        path = str(tmp_path / "instance.yaml")
        staged, _ = keelcli.stage_spec({"version": 2}, path)

        keelcli.discard_spec(staged)
        keelcli.discard_spec(staged)

        assert not Path(staged).exists()


class TestTheRefusalTheOperatorConfirms:
    def test_the_refusal_is_read_out_of_what_apply_printed(self):
        result = make_result(
            ["spec", "apply"],
            stdout=(
                "database.server: write the drop-in: done\n"
                "database.server.replication.primary: refused: becoming a"
                " replica replaces the local database\n"
            ),
        )

        assert keelcli.was_refused(result) == (
            "becoming a replica replaces the local database"
        )

    def test_a_run_that_refused_nothing_has_no_refusal(self):
        assert keelcli.was_refused(make_result(["x"], stdout="done\n")) == ""

    def test_a_line_that_says_refused_and_nothing_else_is_not_one(self):
        found = keelcli.was_refused(make_result(["x"], stdout="refused: "))

        assert found == ""

    def test_the_question_repeats_keels_own_words(self):
        question = keelcli.destroy_question("it holds wordpress")

        assert "it holds wordpress" in question
        assert "cannot be undone" in question


class TestWhatTheScreensShow:
    def test_every_mode_screen_says_there_is_no_failover(self):
        text = keelcli.mode_text(
            {"role": "primary"}, "/etc/keel/instance.yaml",
            make_result(["spec", "apply", "--system-only"]),
        )

        assert "NO AUTOMATIC FAILOVER" in text
        assert "database.server.role: primary" in text

    def test_promoting_says_it_too(self):
        text = keelcli.promote_text(make_result(["database", "promote"]))

        assert "NO AUTOMATIC FAILOVER" in text
        assert "still says" in text

    def test_an_invalid_description_says_the_file_was_not_changed(self):
        text = keelcli.invalid_text(
            "/etc/keel/instance.yaml",
            make_result(["spec", "validate"], code=3, stderr="bad host"),
        )

        assert "was NOT changed" in text
        assert "bad host" in text


class TestTheFlow:
    """Stage, validate, commit, apply, in that order and no other"""

    def commands(self, keel):
        return [call[0] + " " + (call[1] if len(call) > 1 else "")
                for call in keel["calls"]]

    def test_a_valid_description_is_validated_then_committed_then_applied(
        self, spec, keel
    ):
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "Cloud: primary",
            keelcli.primary_server("mariadb", "::1", PREFIX, SECRET),
        )

        assert self.commands(keel) == ["spec validate", "spec apply"]
        written = yaml.safe_load(spec.read_text())
        assert written["database"]["server"]["role"] == "primary"
        assert written["instance"] == {"hostname": "mariadb"}

    def test_an_invalid_description_never_reaches_the_file(self, spec, keel):
        keel["answers"] = [(3, "", "database.server.listen: bad")]
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "Cloud: primary",
            keelcli.primary_server("mariadb", "nonsense", PREFIX, SECRET),
        )

        assert self.commands(keel) == ["spec validate"]
        assert yaml.safe_load(spec.read_text()) == BASE
        assert [one.name for one in spec.parent.iterdir()] == [spec.name]
        assert "was NOT changed" in console.calls[-1][2]

    def test_a_missing_keel_is_said_once_and_nothing_is_written(
        self, spec, keel
    ):
        keel["answers"] = [keelcli.KeelNotInstalled("keel is not installed")]
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "Cloud: primary",
            keelcli.primary_server("mariadb", "::1", PREFIX, SECRET),
        )

        assert yaml.safe_load(spec.read_text()) == BASE
        assert console.calls[-1][2] == "keel is not installed"

    def test_a_description_that_cannot_be_read_stops_before_anything(
        self, tmp_path, monkeypatch, keel
    ):
        broken = tmp_path / "broken.yaml"
        broken.write_text("database: [\n")
        monkeypatch.setenv("KEEL_SPEC", str(broken))
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "Cloud: primary",
            keelcli.primary_server("mariadb", "::1", PREFIX, SECRET),
        )

        assert keel["calls"] == []
        assert "broken.yaml" in console.calls[-1][2]

    def test_a_fresh_appliance_with_no_description_gets_one(
        self, tmp_path, monkeypatch, keel
    ):
        absent = tmp_path / "instance.yaml"
        monkeypatch.setenv("KEEL_SPEC", str(absent))

        dbscreen.apply_mode(
            FakeConsole(), "x", keelcli.standalone_server("mariadb", "::1")
        )

        assert yaml.safe_load(absent.read_text()) == {
            "version": 1,
            "database": {"server": {
                "engine": "mariadb", "role": "standalone", "listen": ["::1"],
            }},
        }
        assert absent.stat().st_mode & 0o777 == 0o600

    def test_a_description_that_cannot_be_staged_stops_there(
        self, tmp_path, monkeypatch, keel
    ):
        path = tmp_path / "instance.yaml"
        path.write_text("version: 1\n")
        monkeypatch.setenv("KEEL_SPEC", str(path))
        monkeypatch.setattr(
            keelcli, "stage_spec", lambda document, where: ("", "no room")
        )
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "x", keelcli.standalone_server("mariadb", "::1")
        )

        assert keel["calls"] == []
        assert console.calls[-1][2] == "no room"

    def test_a_commit_that_fails_stops_before_applying(
        self, spec, keel, monkeypatch
    ):
        monkeypatch.setattr(
            keelcli, "commit_spec", lambda staged, where: "read only"
        )
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "x", keelcli.standalone_server("mariadb", "::1")
        )

        assert self.commands(keel) == ["spec validate"]
        assert "read only" in console.calls[-1][2]
        assert "was NOT changed" in console.calls[-1][2]
        assert [one.name for one in spec.parent.iterdir()] == [spec.name]


class TestTheOneQuestionThatLosesData:
    REFUSAL = (
        "database.server.replication.primary: refused: becoming a replica"
        " replaces the local database with a copy of the primary\n"
    )

    def replica(self, console, keel):
        dbscreen.apply_mode(
            console, "Cloud: replica",
            keelcli.replica_server(
                "mariadb", "::1", PRIMARY_HOST, "", SECRET
            ),
            may_destroy=True,
        )

    def test_a_refusal_is_put_to_the_operator_before_anything_is_dropped(
        self, spec, keel
    ):
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]
        console = FakeConsole(yesno=["ok"])

        self.replica(console, keel)

        assert keel["calls"][-1][-1] == "--destroy-local-database"
        question = [one for one in console.calls if one[0] == "yesno"][0][1]
        assert "replaces the local database" in question

    def test_no_leaves_the_machine_as_it_is(self, spec, keel):
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]
        console = FakeConsole(yesno=["cancel"])

        self.replica(console, keel)

        # validate, the refused apply, and the old description applied
        # again: keel wrote the server's configuration before it refused.
        assert len(keel["calls"]) == 3
        assert all(
            "--destroy-local-database" not in call for call in keel["calls"]
        )
        assert yaml.safe_load(spec.read_text()) == BASE
        assert "NOT a replica" in console.calls[-1][2]
        assert "applied again" in console.calls[-1][2]

    def test_a_keel_that_vanished_before_applying_says_so(self, spec, keel):
        keel["answers"] = [
            (0, "", ""), keelcli.KeelNotInstalled("keel is not installed"),
        ]
        console = FakeConsole()

        self.replica(console, keel)

        assert console.calls[-1][2] == "keel is not installed"
        assert [one for one in console.calls if one[0] == "yesno"] == []

    def test_nothing_is_asked_when_keel_refused_nothing(self, spec, keel):
        console = FakeConsole()

        self.replica(console, keel)

        assert [one for one in console.calls if one[0] == "yesno"] == []
        assert len(keel["calls"]) == 2

    def test_the_other_screens_never_offer_it(self, spec, keel):
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "Cloud: primary",
            keelcli.primary_server("mariadb", "::1", PREFIX, SECRET),
        )

        assert [one for one in console.calls if one[0] == "yesno"] == []

    def test_a_keel_that_vanished_between_the_two_runs_says_so(
        self, spec, keel
    ):
        keel["answers"] = [
            (0, "", ""), (16, self.REFUSAL, ""),
            keelcli.KeelNotInstalled("keel is not installed"),
        ]
        console = FakeConsole(yesno=["ok"])

        self.replica(console, keel)

        assert console.calls[-1][2] == "keel is not installed"


class TestTheForm:
    def test_it_is_prefilled_with_what_the_description_says_now(self):
        server = keelcli.replica_server(
            "mariadb", "::1, 127.0.0.1", PRIMARY_HOST, "3307", SECRET
        )

        found = dbscreen.defaults(server)

        assert found["listen"] == "::1, 127.0.0.1"
        assert found["host"] == PRIMARY_HOST
        assert found["port"] == "3307"
        assert found["secret"] == SECRET

    def test_an_empty_description_offers_the_documented_defaults(self):
        found = dbscreen.defaults({})

        assert found["listen"] == keelcli.DEFAULT_LISTEN
        assert found["secret"] == keelcli.DEFAULT_SECRET
        assert found["host"] == ""
        assert found["allowed_from"] == ""

    def test_the_engine_comes_from_the_description_without_asking(
        self, keel
    ):
        console = FakeConsole()

        found = dbscreen.engine_of(console, "x", {"engine": "postgresql"})

        assert found == "postgresql"
        assert keel["calls"] == []

    def test_otherwise_the_machine_is_asked_what_it_runs(
        self, keel, tmp_path, monkeypatch
    ):
        inspected = tmp_path / "inspected.yaml"
        inspected.write_text(
            yaml.safe_dump({"database": {"server": {"engine": "mariadb"}}})
        )
        monkeypatch.setattr(dbscreen, "INSPECTED", str(inspected))
        console = FakeConsole()

        found = dbscreen.engine_of(console, "x", {})

        assert found == "mariadb"
        assert keel["calls"][0][0] == "inspect"

    def test_a_machine_running_no_database_server_has_no_mode(
        self, keel, tmp_path, monkeypatch
    ):
        inspected = tmp_path / "inspected.yaml"
        inspected.write_text(yaml.safe_dump({"version": 1}))
        monkeypatch.setattr(dbscreen, "INSPECTED", str(inspected))
        console = FakeConsole()

        assert dbscreen.engine_of(console, "x", {}) == ""
        assert "No database server was found" in console.calls[-1][2]

    def test_an_inspection_that_cannot_be_read_says_so(
        self, keel, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            dbscreen, "INSPECTED", str(tmp_path / "absent.yaml")
        )
        console = FakeConsole()

        assert dbscreen.engine_of(console, "x", {}) == ""
        assert "could not be asked" in console.calls[-1][2]

    def test_an_uninstalled_keel_cannot_be_asked_either(self, keel):
        keel["answers"] = [keelcli.KeelNotInstalled("keel is not installed")]
        console = FakeConsole()

        assert dbscreen.engine_of(console, "x", {}) == ""

    def test_asking_returns_the_answers_keyed_the_way_the_screen_asked(
        self, spec, keel
    ):
        console = FakeConsole(forms=[("ok", ["::1", PREFIX, SECRET])])

        found = dbscreen.ask(
            console, "Cloud: primary", "text",
            [
                ("Answer on", "listen", 20, 40),
                ("Allow from", "allowed_from", 20, 40),
                ("Password file", "secret", 20, 40),
            ],
        )

        assert found == {
            "listen": "::1", "allowed_from": PREFIX, "secret": SECRET,
            "engine": "mariadb",
        }

    def test_a_cancelled_form_answers_nothing(self, spec, keel):
        console = FakeConsole(forms=[("cancel", [])])

        assert dbscreen.ask(
            console, "x", "text", [("Answer on", "listen", 20, 40)]
        ) is None

    def test_an_unreadable_description_asks_nothing(
        self, tmp_path, monkeypatch, keel
    ):
        broken = tmp_path / "broken.yaml"
        broken.write_text("- not\n- a mapping\n")
        monkeypatch.setenv("KEEL_SPEC", str(broken))
        console = FakeConsole()

        assert dbscreen.ask(
            console, "x", "text", [("Answer on", "listen", 20, 40)]
        ) is None
        assert "broken.yaml" in console.calls[-1][2]

    def test_a_machine_with_no_engine_asks_nothing(
        self, keel, tmp_path, monkeypatch
    ):
        bare = tmp_path / "instance.yaml"
        bare.write_text(yaml.safe_dump({"version": 1}))
        monkeypatch.setenv("KEEL_SPEC", str(bare))
        inspected = tmp_path / "inspected.yaml"
        inspected.write_text(yaml.safe_dump({"version": 1}))
        monkeypatch.setattr(dbscreen, "INSPECTED", str(inspected))
        console = FakeConsole()

        assert dbscreen.ask(
            console, "x", "text", [("Answer on", "listen", 20, 40)]
        ) is None

    def test_the_fields_are_laid_out_one_per_line(self):
        found = dbscreen.format_fields([("Answer on", "::1", 20, 40)])

        assert found == [("Answer on", 1, 1, "::1", 1, 22, 40, 40)]


class TestTheScreensThemselves:
    NAMES = [
        "01Standalone.py",
        "Cloud/01Primary.py",
        "Cloud/02Replica.py",
        "Cloud/03Promote_this_replica.py",
    ]

    @pytest.mark.parametrize("name", NAMES)
    def test_every_screen_has_a_docstring_and_a_run(self, screen, name):
        loaded, _ = screen(name)

        assert loaded.module.__doc__.strip()
        assert callable(loaded.module.run)

    @pytest.mark.parametrize("name", NAMES[1:])
    def test_every_cloud_screen_states_that_there_is_no_failover(
        self, screen, name
    ):
        loaded, _ = screen(name)
        text = getattr(loaded.module, "TEXT", None) or loaded.module.QUESTION

        assert keelcli.NO_FAILOVER in text

    def test_the_standalone_screen_says_it_configures_this_node(
        self, screen
    ):
        loaded, _ = screen("01Standalone.py")

        assert keelcli.THIS_NODE in loaded.module.TEXT

    def test_the_primary_screen_prefers_a_prefix_and_warns_about_a_name(
        self, screen
    ):
        loaded, _ = screen("Cloud/01Primary.py")

        assert "prefix is the form to prefer" in loaded.module.TEXT
        assert "fragile" in loaded.module.TEXT

    def test_the_replica_screen_says_the_local_database_is_replaced(
        self, screen
    ):
        loaded, _ = screen("Cloud/02Replica.py")

        assert "REPLACES the database it holds" in loaded.module.TEXT

    def test_the_standalone_screen_applies_its_own_role(
        self, screen, spec, keel
    ):
        loaded, _ = screen("01Standalone.py", forms=[("ok", ["::1"])])

        loaded.module.run()

        assert yaml.safe_load(spec.read_text())["database"]["server"][
            "role"
        ] == "standalone"

    @pytest.mark.parametrize("name", NAMES[:3])
    def test_a_cancelled_screen_changes_nothing(
        self, screen, spec, keel, name
    ):
        loaded, _ = screen(name, forms=[("cancel", [])])

        loaded.module.run()

        assert yaml.safe_load(spec.read_text()) == BASE
        assert keel["calls"] == []

    def test_promoting_asks_first_and_calls_the_command(
        self, screen, spec, keel
    ):
        loaded, console = screen(
            "Cloud/03Promote_this_replica.py", yesno=["ok"]
        )

        loaded.module.run()

        assert keel["calls"] == [["database", "promote"]]
        question = [one for one in console.calls if one[0] == "yesno"][0][1]
        assert "two writable servers" in question

    def test_declining_the_promotion_calls_nothing(self, screen, keel):
        loaded, _ = screen(
            "Cloud/03Promote_this_replica.py", yesno=["cancel"]
        )

        loaded.module.run()

        assert keel["calls"] == []

    def test_promoting_without_keel_says_so(self, screen, keel):
        keel["answers"] = [keelcli.KeelNotInstalled("keel is not installed")]
        loaded, console = screen(
            "Cloud/03Promote_this_replica.py", yesno=["ok"]
        )

        loaded.module.run()

        assert console.calls[-1][2] == "keel is not installed"
