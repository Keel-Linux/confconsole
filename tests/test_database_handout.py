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
import tempfile
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
PEER6 = "fd3d:80b2:d0d7::2"
OTHER6 = "fd3d:80b2:d0d7::3"
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


def textboxes(console):
    return [one[2] for one in console.calls if one[0] == "textbox"]


def first_form(console):
    """The form, which the screen's long text now comes before"""
    return next(one for one in console.calls if one[0] == "form")


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
        text = keelcli.handout_text(
            "mariadb", [NODE6, NODE4], "/s/r", origins=[PREFIX]
        )

        assert text.index(NODE6) < text.index(NODE4)
        assert f"Allowed to replicate: {PREFIX}" in text
        assert "Replication account: repl" in text
        assert "Password kept in: /s/r" in text
        assert "not shown here" in text
        assert keelcli.NO_ORIGIN not in text

    def test_the_address_to_paste_is_bare_and_brackets_only_an_example(
        self
    ):
        text = keelcli.handout_text(
            "mariadb", [NODE6], "/s/r", origins=[PREFIX]
        )

        assert f"\n    {NODE6}\n" in text
        assert f"written [{NODE6}]:3306; type the bare address" in text

    def test_no_origin_is_said_first_and_plainly(self):
        text = keelcli.handout_text("mariadb", [NODE6], "/s/r", origins=[])

        assert text.startswith(keelcli.NO_ORIGIN)

    def test_a_failure_is_said_before_anything_else(self):
        text = keelcli.handout_text(
            "mariadb", [NODE6], "/s/r", "pw", origins=[PREFIX],
            failure="keel apply: exit 16",
        )

        assert text.startswith("THIS NODE IS NOT READY: keel apply: exit 16")
        assert "  pw" in text

    def test_the_origins_offered_are_the_overlay_peers(self):
        found = keelcli.suggested_origin("", [PEER6, OTHER6])

        assert found == f"{PEER6}, {OTHER6}"

    def test_origins_already_declared_are_kept(self):
        assert keelcli.suggested_origin(PREFIX, [PEER6]) == PREFIX

    def test_no_peer_offers_nothing_and_never_a_prefix(self):
        # The /64 of this node was offered until keel 0.11.1 refused it:
        # MariaDB matches the text of the replica's address, and in
        # fd3d:80b2:d0d7::/64 the replica fd3d:80b2:d0d7::2 is not written
        # fd3d:80b2:d0d7:0:..., so the pattern for that /64 refused it.
        assert keelcli.suggested_origin("", []) == ""

    @pytest.mark.parametrize(
        "origin",
        ["fd3d:80b2:d0d7::/64", "2001:db8::/48", "2001:0:0:5::/64",
         "2001:db8::/56", "192.0.2.0/25", "2001::5:%",
         "fd3d:80b2:d0d7:0:%"],
    )
    def test_an_origin_keel_refuses_on_mariadb_is_found(self, origin):
        # keel.spec.origins.mariadb_problem, reproduced like the account.
        assert keelcli.refused_origins(origin, "mariadb") == [origin]

    @pytest.mark.parametrize(
        "origin",
        ["2804:710:d0:5::/64", "2001:db8:0:5::/64", "192.0.2.0/24",
         PEER6, "2001:db8:1:%", "replica.example.org", "::/0x",
         "2001:db8::20/128"],
    )
    def test_an_origin_keel_grants_is_not(self, origin):
        assert keelcli.refused_origins(origin, "mariadb") == []

    def test_another_engine_takes_any_prefix(self):
        assert keelcli.refused_origins(
            "fd3d:80b2:d0d7::/64", "postgresql"
        ) == []

    def test_a_refused_origin_is_replaced_by_the_peers(self):
        found = keelcli.suggested_origin(
            f"fd3d:80b2:d0d7::/64, {PEER6}", [PEER6, OTHER6],
            ["fd3d:80b2:d0d7::/64"],
        )

        assert found == f"{PEER6}, {OTHER6}"

    def test_the_warning_names_the_origin_and_the_peers(self):
        text = keelcli.refused_text(["fd3d:80b2:d0d7::/64"], [PEER6])

        assert "fd3d:80b2:d0d7::/64" in text
        assert "overlay peers" in text
        assert "no overlay peer" in keelcli.refused_text(
            ["fd3d:80b2:d0d7::/64"], []
        )

    def test_a_pasted_bracketed_address_is_stored_bare(self):
        found = keelcli.replica_server(
            "mariadb", "::1", f" [{NODE6}] ", "", "/s/r"
        )

        assert found["replication"]["primary"]["host"] == NODE6

    def test_the_apply_leaves_the_network_and_the_certificate_alone(self):
        assert "--skip-network" in keelcli.APPLY
        assert "--defer-certificate" in keelcli.APPLY
        assert "--system-only" in keelcli.APPLY
        assert "network" in keelcli.THIS_NODE

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

        listen = first_form(console)[2][0][3]
        assert listen.startswith(f"{NODE6}, {NODE4}")

    def test_the_form_offers_the_overlay_peers_addresses(
        self, screen, spec, keel, machine
    ):
        machine[:] = [ULA6, PUBLIC6, NODE4]
        spec.write_text(yaml.safe_dump({**BASE, "network": {"overlay": {
            "wireguard": {"address": "fd3d:80b2:d0d7::1/64", "peers": [
                {"public_key": "k" * 43 + "=",
                 "allowed_ips": [f"{PEER6}/128"]},
                {"public_key": "o" * 43 + "=",
                 "allowed_ips": [f"{OTHER6}/128"]},
            ]},
        }}}))
        loaded, console = screen(
            "Cloud/01Primary.py", forms=[("cancel", [])]
        )

        loaded.module.run()

        assert first_form(console)[2][1][3] == f"{PEER6}, {OTHER6}"

    def test_a_declared_prefix_keel_refuses_is_flagged_and_replaced(
        self, screen, spec, keel
    ):
        spec.write_text(yaml.safe_dump({
            **BASE,
            "database": {"server": {
                "engine": "mariadb", "role": "primary",
                "replication": {"allowed_from": ["fd3d:80b2:d0d7::/64"]},
            }},
            "network": {"overlay": {"wireguard": {
                "address": "fd3d:80b2:d0d7::1/64", "peers": [
                    {"public_key": "k" * 43 + "=",
                     "allowed_ips": [f"{PEER6}/128"]},
                ],
            }}},
        }))
        loaded, console = screen(
            "Cloud/01Primary.py", forms=[("cancel", [])]
        )

        loaded.module.run()

        fields = first_form(console)[2]
        assert fields[1][3] == PEER6
        assert messages(console)[0].startswith(keelcli.refused_text(
            ["fd3d:80b2:d0d7::/64"], [PEER6]
        ))

    def test_the_form_offers_no_prefix_of_this_node(
        self, screen, spec, keel, machine
    ):
        machine[:] = [ULA6, PUBLIC6, NODE4]
        loaded, console = screen(
            "Cloud/01Primary.py", forms=[("cancel", [])]
        )

        loaded.module.run()

        assert first_form(console)[2][1][3] == ""

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
        handout = textboxes(console)[-1]
        assert handout.index(NODE6) < handout.index("account: repl")
        assert "g3n" in handout
        assert str(secret) in handout
        assert "NOT READY" not in handout
        assert keelcli.NO_ORIGIN not in handout
        for call in keel["calls"]:
            assert all("g3n" not in one for one in call)
        assert all("g3n" not in text for text in messages(console))

    def test_the_handout_file_is_root_only_and_gone_afterwards(
        self, screen, spec, keel, secret
    ):
        loaded, console = screen(
            "Cloud/01Primary.py", forms=primary_form(secret), yesno=["ok"]
        )

        loaded.module.run()

        _, _, _, where, mode = [
            one for one in console.calls if one[0] == "textbox"
        ][-1]
        assert mode == 0o600
        assert not os.path.exists(where)
        assert not os.path.exists(os.path.dirname(where))

    def test_a_failed_apply_still_shows_the_password_and_warns(
        self, screen, spec, keel, secret, monkeypatch
    ):
        monkeypatch.setattr(keelcli, "generate_password", lambda: "g3n")
        keel["answers"] = [(0, "", ""), (16, "database.server: failed", "")]
        loaded, console = screen(
            "Cloud/01Primary.py", forms=primary_form(secret), yesno=["ok"]
        )

        loaded.module.run()

        handout = textboxes(console)[-1]
        assert handout.startswith("THIS NODE IS NOT READY")
        assert "exit 16" in handout
        assert "g3n" in handout

    def test_an_empty_origin_list_is_said_plainly(
        self, screen, spec, keel, secret
    ):
        loaded, console = screen(
            "Cloud/01Primary.py",
            forms=[("ok", [NODE6, "  ", str(secret)])], yesno=["ok"],
        )

        loaded.module.run()

        assert server_from(spec)["replication"]["allowed_from"] == []
        assert keelcli.NO_ORIGIN in textboxes(console)[-1]

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
        assert "0ld-v4lue" not in textboxes(console)[-1]
        assert "not shown here" in textboxes(console)[-1]
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

        labels = [field[0] for field in first_form(console)[2]]
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
        applied = keel["calls"][-1]
        assert applied[:2] == ["spec", "apply"]
        for flag in ("--system-only", "--skip-network", "--defer-certificate"):
            assert flag in applied
        for call in keel["calls"]:
            assert all("p4ste" not in one for one in call)

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


class TestWritingAllAtOnce:
    def test_the_secret_leaves_nothing_beside_it(self, secret):
        keelcli.write_secret(str(secret), "one")
        keelcli.write_secret(str(secret), "two")

        assert [one.name for one in secret.parent.iterdir()] == [secret.name]
        assert secret.read_text() == "two\n"

    def test_a_replace_that_fails_leaves_the_old_value_and_no_debris(
        self, secret, monkeypatch
    ):
        keelcli.write_secret(str(secret), "old")

        def refuse(source, target):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(keelcli.os, "replace", refuse)

        problem = keelcli.write_secret(str(secret), "new")

        assert "Permission denied" in problem
        assert secret.read_text() == "old\n"
        assert [one.name for one in secret.parent.iterdir()] == [secret.name]

    def test_a_write_that_fails_midway_leaves_no_debris(
        self, tmp_path, monkeypatch
    ):
        def full(descriptor, mode):
            os.close(descriptor)
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(keelcli.os, "fdopen", full)

        written, problem = keelcli.write_beside(
            str(tmp_path / "instance.yaml"), "x", ".keelcli-new"
        )

        assert written == ""
        assert "No space left" in problem
        assert list(tmp_path.iterdir()) == []

    def test_a_directory_that_takes_no_new_file_says_why(
        self, secret, monkeypatch
    ):
        secret.parent.mkdir()

        def refuse(**kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(keelcli.tempfile, "mkstemp", refuse)

        problem = keelcli.write_secret(str(secret), "x")

        assert "Permission denied" in problem
        assert not secret.exists()

    def test_two_consoles_stage_into_two_files(self, tmp_path):
        path = str(tmp_path / "instance.yaml")

        first, _ = keelcli.stage_spec({"version": 1}, path)
        second, _ = keelcli.stage_spec({"version": 1}, path)

        assert first != second
        assert Path(first).stat().st_mode & 0o777 == 0o600

    def test_a_fresh_appliance_starts_the_smallest_description(
        self, tmp_path
    ):
        found = keelcli.load_description(str(tmp_path / "absent.yaml"))

        assert found == ({"version": 1}, "")


class TestPuttingFilesBack:
    def test_a_file_that_did_not_exist_is_removed_again(self, secret):
        keelcli.write_secret(str(secret), "new")

        assert keelcli.restore(str(secret), None) == ""
        assert not secret.exists()
        assert keelcli.restore(str(secret), None) == ""

    def test_a_file_that_existed_gets_its_text_back(self, secret):
        keelcli.write_secret(str(secret), "old")
        before = keelcli.read_back(str(secret))
        keelcli.write_secret(str(secret), "new")

        assert keelcli.restore(str(secret), before) == ""
        assert secret.read_text() == "old\n"
        assert secret.stat().st_mode & 0o777 == 0o600

    def test_nothing_to_read_back_is_none(self, secret):
        assert keelcli.read_back(str(secret)) is None

    def test_a_removal_that_fails_says_why(self, tmp_path):
        stuck = tmp_path / "stuck"
        stuck.mkdir()
        (stuck / "inside").write_text("")

        assert "stuck" in keelcli.restore(str(stuck), None)


class TestThePrivateDirectory:
    @pytest.mark.parametrize("preset", [None, "/var/tmp"])
    def test_it_is_root_only_and_gone_with_the_environment_restored(
        self, monkeypatch, preset
    ):
        if preset is None:
            monkeypatch.delenv("TMPDIR", raising=False)
        else:
            monkeypatch.setenv("TMPDIR", preset)
        before = tempfile.tempdir

        with pytest.raises(RuntimeError):
            with dbscreen.private_tmp() as directory:
                assert os.stat(directory).st_mode & 0o777 == 0o700
                assert os.environ["TMPDIR"] == directory
                assert tempfile.gettempdir() == directory
                raise RuntimeError("the session dropped")

        assert not os.path.exists(directory)
        assert os.environ.get("TMPDIR") == preset
        assert tempfile.tempdir == before

    def test_the_password_box_runs_inside_it(self, secret):
        seen = []

        class Watching(FakeConsole):
            def _wrapper(self, dialog, text, *args, **kwargs):
                seen.append(os.environ.get("TMPDIR", ""))
                return super()._wrapper(dialog, text, *args, **kwargs)

        console = Watching(passwords=[("ok", "p4ste")])

        dbscreen.replica_password(console, "x", str(secret))

        assert os.path.basename(seen[0]).startswith(dbscreen.PRIVATE_PREFIX)
        assert not os.path.exists(seen[0])


class TestNoToTheDestroyQuestion:
    REFUSAL = (
        "database.server.replication.primary: refused: becoming a replica"
        " replaces the local database with a copy of the primary\n"
    )

    def run_replica(self, screen, answers):
        loaded, console = screen(
            "Cloud/02Replica.py", forms=replica_form(),
            passwords=[("ok", "p4ste")], yesno=["ok", "cancel"],
        )
        loaded.module.run()
        return console

    def test_the_description_and_a_new_password_file_are_undone(
        self, screen, spec, keel, secret, monkeypatch
    ):
        monkeypatch.setattr(keelcli, "DEFAULT_SECRET", str(secret))
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]

        console = self.run_replica(screen, keel)

        assert yaml.safe_load(spec.read_text()) == BASE
        assert not secret.exists()
        assert len(keel["calls"]) == 3
        assert keel["calls"][-1][:2] == ["spec", "apply"]
        assert "NOT a replica" in messages(console)[-1]

    def test_a_password_that_was_there_is_put_back(
        self, screen, spec, keel, secret, monkeypatch
    ):
        monkeypatch.setattr(keelcli, "DEFAULT_SECRET", str(secret))
        keelcli.write_secret(str(secret), "0ld")
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]

        self.run_replica(screen, keel)

        assert secret.read_text() == "0ld\n"

    def test_with_no_description_before_there_is_nothing_to_reapply(
        self, screen, keel, secret, tmp_path, monkeypatch
    ):
        absent = tmp_path / "instance.yaml"
        monkeypatch.setattr(keelcli, "DEFAULT_SECRET", str(secret))
        monkeypatch.setattr(
            dbscreen, "engine_of", lambda console, title, server: "mariadb"
        )
        loaded, console = screen(
            "Cloud/02Replica.py", forms=replica_form(),
            passwords=[("ok", "p4ste")], yesno=["ok", "cancel"],
        )
        monkeypatch.setenv("KEEL_SPEC", str(absent))
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]

        loaded.module.run()

        assert not absent.exists()
        assert len(keel["calls"]) == 2
        assert "There was no" in messages(console)[-1]

    def test_a_file_that_cannot_be_put_back_is_named_and_not_reapplied(
        self, screen, spec, keel, secret, monkeypatch
    ):
        monkeypatch.setattr(keelcli, "DEFAULT_SECRET", str(secret))
        monkeypatch.setattr(keelcli, "restore", lambda where, text: "stuck")
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]

        console = self.run_replica(screen, keel)

        assert len(keel["calls"]) == 2
        assert "could NOT be put back" in messages(console)[-1]
        assert "stuck" in messages(console)[-1]

    def test_an_old_description_without_a_server_is_not_reapplied(
        self, screen, spec, keel, secret, monkeypatch
    ):
        bare = {"version": 1, "instance": {"hostname": "mariadb"}}
        spec.write_text(yaml.safe_dump(bare))
        monkeypatch.setattr(keelcli, "DEFAULT_SECRET", str(secret))
        monkeypatch.setattr(
            dbscreen, "engine_of", lambda console, title, server: "mariadb"
        )
        keel["answers"] = [(0, "", ""), (16, self.REFUSAL, "")]

        console = self.run_replica(screen, keel)

        # validate and the refused apply: nothing of the old description
        # would converge the server back, so it is not claimed to.
        assert len(keel["calls"]) == 2
        assert yaml.safe_load(spec.read_text()) == bare
        assert not secret.exists()
        said = messages(console)[-1]
        assert "declares no database server" in said
        assert "stays until a database mode is applied" in said
        assert "applied again" not in said


class TestACommitThatFails:
    def primary(self, secret):
        return keelcli.primary_server("mariadb", "::", PREFIX, str(secret))

    def fail_commit(self, monkeypatch):
        monkeypatch.setattr(
            keelcli, "commit_spec", lambda staged, where: "read only"
        )

    def test_a_new_password_does_not_outlive_it(
        self, spec, keel, secret, monkeypatch
    ):
        self.fail_commit(monkeypatch)
        console = FakeConsole()

        found = dbscreen.apply_mode(
            console, "x", self.primary(secret), password="n3w"
        )

        assert found is None
        assert not secret.exists()
        assert yaml.safe_load(spec.read_text()) == BASE
        assert [call[:2] for call in keel["calls"]] == [["spec", "validate"]]
        said = messages(console)[-1]
        assert "was NOT changed" in said
        assert "read only" in said
        assert "put back as it was" in said

    def test_an_older_password_is_put_back(
        self, spec, keel, secret, monkeypatch
    ):
        keelcli.write_secret(str(secret), "0ld")
        self.fail_commit(monkeypatch)

        dbscreen.apply_mode(
            FakeConsole(), "x", self.primary(secret), password="n3w"
        )

        assert secret.read_text() == "0ld\n"

    def test_a_password_that_cannot_be_put_back_is_named(
        self, spec, keel, secret, monkeypatch
    ):
        self.fail_commit(monkeypatch)
        monkeypatch.setattr(keelcli, "restore", lambda where, text: "stuck")
        console = FakeConsole()

        dbscreen.apply_mode(
            console, "x", self.primary(secret), password="n3w"
        )

        said = messages(console)[-1]
        assert "could NOT be put back" in said
        assert "stuck" in said


class TestWhatADescriptionDeclares:
    def test_a_server_section_is_a_server(self):
        assert keelcli.declares_server(yaml.safe_dump(BASE))

    @pytest.mark.parametrize(
        "text", [None, "", "version: 1\n", "- a\n- list\n", "database: [\n"]
    )
    def test_anything_else_declares_none(self, text):
        assert not keelcli.declares_server(text)


class TestATerminalTooSmall:
    def test_the_handout_is_shown_anyway_sized_by_dialog(self):
        class Small(FakeConsole):
            def textbox(self, path, height, width, **kwargs):
                if height:
                    raise dbscreen.DialogError("Can't make new window")
                self.sizes = (height, width)
                return super().textbox(path, height, width, **kwargs)

        console = Small()

        dbscreen.show_secret(console, "x", "the password")

        assert console.sizes == (0, 0)
        assert "the password" in textboxes(console)[-1]
