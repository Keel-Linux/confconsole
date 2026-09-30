"""What the primary hands the operator, and the password both ends hold.

Decision 0013: the primary's screen shows what its replicas need (the
address to replicate from, IPv6 first, the replication account and where
its password is kept), and the replica's screen asks for the primary's
address and that password and warns before it acts. keel refuses to
generate a replication credential, because both ends must hold the same
value, so the console generates it on the primary and shows it once.
No dialog opens and no keel runs.
"""

import os
from pathlib import Path

import pytest
import yaml

import dbscreen
import keelcli
from conftest import BASE, FakeConsole

PRIMARY_HOST = "2001:db8:1::5"
PREFIX = "2001:db8:1::/64"
NODE6 = "2001:db8:1::10"
NODE4 = "192.0.2.10"
TEMPORARY6 = "2001:db8:1::beef"
PUBLIC6 = "2804:710:d0:5::10"
ULA6 = "fd00:218:88::10"
REFUSAL = (
    "database.server.replication.primary: refused: becoming a replica"
    " replaces the local database with a copy of the primary\n"
)


@pytest.fixture(autouse=True)
def machine(monkeypatch):
    """This node's addresses, as the usage screen would read them"""
    found = [NODE6, NODE4]
    monkeypatch.setattr(dbscreen, "local_addresses", lambda: list(found))
    return found


@pytest.fixture
def secret(tmp_path):
    """Where the description says the password is: not there yet"""
    return tmp_path / "secrets" / "replication_password"


def server_from(spec_path):
    return yaml.safe_load(spec_path.read_text())["database"]["server"]


def messages(console):
    return [one[2] for one in console.calls if one[0] == "msgbox"]


def questions(console):
    return [one[1] for one in console.calls if one[0] == "yesno"]


class TestTheAddressesAReplicaCanUse:
    def test_a_loopback_only_server_is_reachable_by_nobody(self):
        assert keelcli.reachable(["::1", "127.0.0.1"], [NODE6]) == []

    def test_the_global_literals_of_listen_ipv6_first(self):
        found = keelcli.reachable(["::1", NODE4, NODE6], [TEMPORARY6])

        assert found == [NODE6, NODE4]

    def test_public_before_unique_local_within_a_family(self):
        found = keelcli.ipv6_first([NODE4, ULA6, PUBLIC6])

        assert found == [PUBLIC6, ULA6, NODE4]

    def test_what_is_not_an_address_keeps_its_place(self):
        found = keelcli.ipv6_first(["db.example.org", NODE4, PUBLIC6])

        assert found == ["db.example.org", PUBLIC6, NODE4]

    def test_the_wildcard_means_every_address_of_the_machine(self):
        assert keelcli.reachable(["::"], [NODE4, NODE6]) == [NODE6, NODE4]

    def test_no_listen_means_the_packaged_setting_and_the_machine(self):
        assert keelcli.reachable([], [NODE6, NODE6]) == [NODE6]

    def test_link_local_and_names_are_not_offered(self):
        found = keelcli.reachable(["fe80::1", "db.example.org", "[::]"], [])

        assert found == []

    def test_a_loopback_only_primary_is_offered_this_nodes_addresses(self):
        found = keelcli.primary_listen("::1, 127.0.0.1", [NODE4, NODE6])

        assert found == f"{NODE6}, {NODE4}, ::1, 127.0.0.1"

    def test_a_choice_the_operator_already_made_is_kept(self):
        assert keelcli.primary_listen("::", [NODE6]) == "::"
        assert keelcli.primary_listen(NODE6, [NODE6, NODE4]) == NODE6

    def test_a_machine_with_no_address_offers_what_there_was(self):
        assert keelcli.primary_listen("::1", []) == "::1"


class TestWhatThePrimaryHandsOut:
    def test_it_names_the_address_the_account_and_the_file(self):
        text = keelcli.handout_text("mariadb", [NODE6, NODE4], "/s/r")

        assert text.index(NODE6) < text.index(NODE4)
        assert f"[{NODE6}]:3306" in text
        assert f"{NODE4}:3306" in text
        assert "Replication account: repl" in text
        assert "Password kept in: /s/r" in text
        assert "not shown here" in text

    def test_a_generated_password_is_shown_once(self):
        text = keelcli.handout_text("mariadb", [NODE6], "/s/r", "s3cret")

        assert "shown ONCE" in text
        assert "  s3cret" in text

    def test_a_primary_nobody_can_reach_says_so(self):
        text = keelcli.handout_text("mariadb", [], "/s/r")

        assert keelcli.LOOPBACK_ONLY in text

    def test_the_replica_warning_names_the_primary_and_this_node(self):
        text = keelcli.replica_warning(NODE6)

        assert f"[{NODE6}]" in text
        assert "REPLACES the data on this node" in text
        assert keelcli.THIS_NODE in text


class TestTheSecretFile:
    def test_it_is_written_root_only_with_one_newline(self, secret):
        assert keelcli.write_secret(str(secret), "s3cret") == ""

        assert secret.read_text() == "s3cret\n"
        assert secret.stat().st_mode & 0o777 == 0o600
        assert secret.parent.stat().st_mode & 0o777 == 0o700

    def test_a_wider_mode_already_there_is_narrowed(self, secret):
        secret.parent.mkdir()
        secret.write_text("old\n")
        secret.chmod(0o644)

        keelcli.write_secret(str(secret), "new")

        assert secret.stat().st_mode & 0o777 == 0o600
        assert secret.read_text() == "new\n"

    def test_a_file_that_cannot_be_written_says_why(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("")

        problem = keelcli.write_secret(str(blocker / "secret"), "x")

        assert "secret" in problem

    def test_an_empty_or_absent_file_holds_no_password(self, secret):
        assert not keelcli.secret_exists(str(secret))
        secret.parent.mkdir()
        secret.write_text("")
        assert not keelcli.secret_exists(str(secret))
        secret.write_text("x\n")
        assert keelcli.secret_exists(str(secret))

    def test_a_generated_password_survives_a_paste_and_keels_quoting(self):
        found = keelcli.generate_password()

        assert len(found) >= 32
        assert found.isascii() and found.isprintable()
        assert found != keelcli.generate_password()


class TestTheMachinesAddresses:
    def test_every_reachable_interface_ipv6_first(
        self, monkeypatch, tmp_path
    ):
        for name in ("eth0", "lo", "veth1a", "eth1"):
            (tmp_path / name).mkdir()
        monkeypatch.setattr(dbscreen, "NET_DIR", str(tmp_path))
        # What VM1 showed: one interface holding a unique local address
        # and a public one, the unique local listed first by the kernel.
        six = {
            "eth0": [
                (ULA6, "64", {"dynamic", "mngtmpaddr"}),
                (PUBLIC6, "64", {"dynamic", "mngtmpaddr"}),
                (TEMPORARY6, "64", {"dynamic", "temporary"}),
                ("2804:710:d0:5::dead", "64", {"deprecated"}),
            ],
            "eth1": [],
        }
        four = {"eth0": NODE4, "eth1": None}
        monkeypatch.setattr(
            dbscreen.ifutil, "_list_ipv6_global", lambda name: six[name]
        )
        monkeypatch.setattr(
            dbscreen.ifutil, "get_ipconf",
            lambda name: (four[name], None, None, []),
        )

        found = REAL_LOCAL_ADDRESSES()

        assert found == [PUBLIC6, ULA6, NODE4]

    def test_a_machine_whose_interfaces_cannot_be_listed_has_none(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(dbscreen, "NET_DIR", str(tmp_path / "absent"))

        assert REAL_LOCAL_ADDRESSES() == []


REAL_LOCAL_ADDRESSES = dbscreen.local_addresses


class TestThePasswordSteps:
    def test_a_password_already_there_is_kept_and_never_asked(self, secret):
        secret.parent.mkdir()
        secret.write_text("kept\n")
        console = FakeConsole()

        assert dbscreen.primary_password(console, "x", str(secret)) == ""
        assert console.calls == []

    def test_the_primary_offers_to_generate_one(self, secret, monkeypatch):
        monkeypatch.setattr(keelcli, "generate_password", lambda: "g3n")
        console = FakeConsole(yesno=["ok"])

        assert dbscreen.primary_password(console, "x", str(secret)) == "g3n"
        assert "shown ONCE" in questions(console)[0]

    def test_declining_lets_the_operator_type_one(self, secret):
        console = FakeConsole(yesno=["cancel"], passwords=[("ok", " t ")])

        assert dbscreen.primary_password(console, "x", str(secret)) == "t"
        box = [one for one in console.calls if one[0] == "passwordbox"][0]
        assert box[3]["insecure"] is True

    def test_typing_nothing_stops_and_says_why(self, secret):
        console = FakeConsole(yesno=["cancel"], passwords=[("ok", "")])

        assert dbscreen.primary_password(console, "x", str(secret)) is None
        assert "Nothing was changed" in messages(console)[0]

    def test_cancelling_the_box_stops_quietly(self, secret):
        console = FakeConsole(yesno=["cancel"], passwords=[("cancel", "")])

        assert dbscreen.primary_password(console, "x", str(secret)) is None
        assert messages(console) == []

    def test_the_replica_takes_the_pasted_password(self, secret):
        console = FakeConsole(passwords=[("ok", "p4ste\n")])

        assert dbscreen.replica_password(console, "x", str(secret)) == (
            "p4ste"
        )

    def test_a_blank_keeps_the_replicas_file_when_it_has_one(self, secret):
        secret.parent.mkdir()
        secret.write_text("kept\n")
        console = FakeConsole(passwords=[("ok", "")])

        assert dbscreen.replica_password(console, "x", str(secret)) == ""

    def test_a_blank_with_no_file_stops(self, secret):
        console = FakeConsole(passwords=[("ok", "")])

        assert dbscreen.replica_password(console, "x", str(secret)) is None
        assert "Nothing was changed" in messages(console)[0]

    def test_cancelling_the_replicas_box_stops(self, secret):
        console = FakeConsole(passwords=[("cancel", "")])

        assert dbscreen.replica_password(console, "x", str(secret)) is None

    def test_the_file_is_the_one_the_description_names(self):
        assert dbscreen.secret_path({}) == keelcli.DEFAULT_SECRET
        assert dbscreen.secret_path(
            {"replication": {"secret": {"file": "/s"}}}
        ) == "/s"


class TestThePasswordAndTheDescription:
    def primary(self, secret):
        return keelcli.primary_server("mariadb", "::", PREFIX, str(secret))

    def test_it_is_written_after_validation_and_before_the_apply(
        self, spec, keel, secret, monkeypatch
    ):
        seen = []

        def fake_call(argv):
            seen.append((argv[:2], secret.exists()))
            return keelcli.Result(("keel", *argv), 0, "", "")

        monkeypatch.setattr(keelcli, "call", fake_call)
        console = FakeConsole()

        result = dbscreen.apply_mode(
            console, "x", self.primary(secret), password="s3cret"
        )

        assert seen == [
            (["spec", "validate"], False), (["spec", "apply"], True)
        ]
        assert secret.read_text() == "s3cret\n"
        assert result.code == 0

    def test_a_description_keel_refused_leaves_no_password(
        self, spec, keel, secret
    ):
        keel["answers"] = [(3, "", "bad")]

        dbscreen.apply_mode(
            FakeConsole(), "x", self.primary(secret), password="s3cret"
        )

        assert not secret.exists()

    def test_a_password_that_cannot_be_written_changes_nothing(
        self, spec, keel, tmp_path
    ):
        blocker = tmp_path / "file"
        blocker.write_text("")
        console = FakeConsole()

        result = dbscreen.apply_mode(
            console, "x",
            keelcli.primary_server("mariadb", "::", PREFIX,
                                   str(blocker / "secret")),
            password="s3cret",
        )

        assert result is None
        assert yaml.safe_load(spec.read_text()) == BASE
        assert [call[0] for call in keel["calls"]] == ["spec"]
        assert "was NOT changed" in messages(console)[-1]

    def test_no_password_writes_no_file(self, spec, keel, secret):
        dbscreen.apply_mode(FakeConsole(), "x", self.primary(secret))

        assert not secret.exists()


def primary_form(secret):
    return [("ok", [f"{NODE6}, ::1", PREFIX, str(secret)])]


class TestThePrimaryScreen:
    def test_the_form_offers_this_nodes_address_ipv6_first(
        self, screen, spec, keel, secret
    ):
        loaded, console = screen(
            "Cloud/01Primary.py", forms=[("cancel", [])]
        )

        loaded.module.run()

        listen = console.calls[0][2][0][3]
        assert listen.startswith(f"{NODE6}, {NODE4}")

    def test_it_generates_applies_and_hands_out_once(
        self, screen, spec, keel, secret, monkeypatch
    ):
        monkeypatch.setattr(keelcli, "generate_password", lambda: "g3n")
        loaded, console = screen(
            "Cloud/01Primary.py", forms=primary_form(secret), yesno=["ok"]
        )

        loaded.module.run()

        server = server_from(spec)
        assert server["role"] == "primary"
        assert server["replication"]["secret"] == {"file": str(secret)}
        assert secret.read_text() == "g3n\n"
        handout = messages(console)[-1]
        assert handout.index(NODE6) < handout.index("account: repl")
        assert "g3n" in handout
        assert str(secret) in handout
        assert all("g3n" not in call for call in keel["calls"][0])

    def test_a_password_already_there_is_not_shown_again(
        self, screen, spec, keel, secret
    ):
        secret.parent.mkdir()
        secret.write_text("0ld-v4lue\n")
        loaded, console = screen(
            "Cloud/01Primary.py", forms=primary_form(secret)
        )

        loaded.module.run()

        assert questions(console) == []
        assert "0ld-v4lue" not in messages(console)[-1]
        assert "not shown here" in messages(console)[-1]
        assert secret.read_text() == "0ld-v4lue\n"

    def test_declining_every_password_changes_nothing(
        self, screen, spec, keel, secret
    ):
        loaded, _ = screen(
            "Cloud/01Primary.py", forms=primary_form(secret),
            yesno=["cancel"], passwords=[("cancel", "")],
        )

        loaded.module.run()

        assert yaml.safe_load(spec.read_text()) == BASE
        assert keel["calls"] == []

    def test_a_refused_description_hands_nothing_out(
        self, screen, spec, keel, secret
    ):
        keel["answers"] = [(3, "", "bad")]
        loaded, console = screen(
            "Cloud/01Primary.py", forms=primary_form(secret), yesno=["ok"]
        )

        loaded.module.run()

        assert "was NOT changed" in messages(console)[-1]
        assert not secret.exists()


def replica_form():
    return [("ok", [PRIMARY_HOST, "", "::1"])]


class TestTheReplicaScreen:
    @pytest.fixture
    def described(self, spec, secret):
        """A description whose secret lives under the test's tmp dir"""
        document = yaml.safe_load(spec.read_text())
        document["database"]["server"]["replication"] = {
            "secret": {"file": str(secret)}
        }
        spec.write_text(yaml.safe_dump(document))
        return spec

    def test_it_asks_the_address_and_the_password_never_a_file(
        self, screen, described, keel, secret
    ):
        loaded, console = screen(
            "Cloud/02Replica.py", forms=[("cancel", [])]
        )

        loaded.module.run()

        labels = [field[0] for field in console.calls[0][2]]
        assert "Replicate from (address)" in labels
        assert not any("file" in label for label in labels)

    def test_it_warns_before_it_acts_and_no_changes_nothing(
        self, screen, described, keel, secret
    ):
        loaded, console = screen(
            "Cloud/02Replica.py", forms=replica_form(),
            passwords=[("ok", "p4ste")], yesno=["cancel"],
        )

        loaded.module.run()

        assert "REPLACES the data" in questions(console)[0]
        assert keel["calls"] == []
        assert not secret.exists()
        assert yaml.safe_load(described.read_text())["database"]["server"][
            "role"
        ] == "standalone"

    def test_yes_writes_the_password_and_builds_the_replica(
        self, screen, described, keel, secret
    ):
        loaded, console = screen(
            "Cloud/02Replica.py", forms=replica_form(),
            passwords=[("ok", "p4ste")], yesno=["ok"],
        )

        loaded.module.run()

        server = server_from(described)
        assert server["role"] == "replica"
        assert server["replication"]["primary"] == {"host": PRIMARY_HOST}
        assert server["replication"]["secret"] == {"file": str(secret)}
        assert secret.read_text() == "p4ste\n"
        assert os.stat(secret).st_mode & 0o777 == 0o600
        assert "--system-only" in keel["calls"][-1]

    def test_keels_refusal_is_still_asked_after_the_warning(
        self, screen, described, keel, secret
    ):
        keel["answers"] = [(0, "", ""), (16, REFUSAL, ""), (0, "", "")]
        loaded, console = screen(
            "Cloud/02Replica.py", forms=replica_form(),
            passwords=[("ok", "p4ste")], yesno=["ok", "ok"],
        )

        loaded.module.run()

        assert len(questions(console)) == 2
        assert keel["calls"][-1][-1] == "--destroy-local-database"

    def test_a_cancelled_password_changes_nothing(
        self, screen, described, keel, secret
    ):
        loaded, console = screen(
            "Cloud/02Replica.py", forms=replica_form(),
            passwords=[("cancel", "")],
        )

        loaded.module.run()

        assert questions(console) == []
        assert keel["calls"] == []
        assert not Path(secret).exists()
