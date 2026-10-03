"""Tests for configuration discovery, parsing, and persistence."""

import pytest

import conf


class TestPath:
    def test_finds_configuration_in_local_conf_directory(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "conf"
        config_dir.mkdir()
        config_file = config_dir / "confconsole.conf"
        config_file.write_text("", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert conf.path("confconsole.conf") == "conf/confconsole.conf"

    def test_raises_when_configuration_file_is_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with pytest.raises(conf.ConfconsoleConfError, match="missing.conf"):
            conf.path("missing.conf")


class TestConf:
    def _write_config(self, tmp_path, content):
        config_dir = tmp_path / "conf"
        config_dir.mkdir()
        config_file = config_dir / "confconsole.conf"
        config_file.write_text(content, encoding="utf-8")
        return config_file

    def test_defaults_are_loaded_from_an_empty_configuration(self, tmp_path, monkeypatch):
        self._write_config(tmp_path, "")
        monkeypatch.chdir(tmp_path)

        loaded = conf.Conf()

        assert loaded.conf_file == "conf/confconsole.conf"
        assert loaded.default_nic is None
        assert loaded.publicip_cmd is None
        assert loaded.networking is True
        assert loaded.copy_paste is True

    def test_loads_values_comments_blanks_and_ignored_autostart(self, tmp_path, monkeypatch):
        self._write_config(
            tmp_path,
            "\n# keep this comment\ndefault_nic eth0\n"
            "publicip_cmd curl https://example.test/ip\n"
            "networking false\nautostart yes\ncopy_paste false\n",
        )
        monkeypatch.chdir(tmp_path)

        loaded = conf.Conf()

        assert loaded.default_nic == "eth0"
        assert loaded.publicip_cmd == "curl https://example.test/ip"
        assert loaded.networking is False
        assert loaded.copy_paste is False

    def test_accepts_uppercase_copy_paste_boolean(self, tmp_path, monkeypatch):
        self._write_config(tmp_path, "copy_paste TRUE\n")
        monkeypatch.chdir(tmp_path)

        assert conf.Conf().copy_paste is True

    @pytest.mark.parametrize(
        "line",
        ["networking yes", "copy_paste enabled", "unknown value"],
    )
    def test_rejects_illegal_configuration_lines(self, tmp_path, monkeypatch, line):
        self._write_config(tmp_path, line + "\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(conf.ConfconsoleConfError, match="illegal configuration line"):
            conf.Conf()

    def test_load_conf_ignores_a_missing_explicit_file(self, tmp_path):
        loaded = object.__new__(conf.Conf)
        loaded.conf_file = str(tmp_path / "does-not-exist")
        loaded.default_nic = None
        loaded.publicip_cmd = None
        loaded.networking = True
        loaded.copy_paste = True

        loaded._load_conf()

        assert loaded.default_nic is None
        assert loaded.networking is True

    def test_set_default_nic_replaces_existing_setting_and_preserves_other_lines(
        self, tmp_path, monkeypatch
    ):
        config_file = self._write_config(
            tmp_path,
            "# header\ndefault_nic eth0\nnetworking false\ndefault_nic old\n",
        )
        monkeypatch.chdir(tmp_path)
        loaded = conf.Conf()

        loaded.set_default_nic("ens3")

        assert config_file.read_text(encoding="utf-8") == (
            "# header\ndefault_nic ens3\nnetworking false\ndefault_nic ens3\n"
        )
        assert loaded.default_nic == "ens3"

    def test_set_default_nic_appends_with_newline_to_existing_file(self, tmp_path, monkeypatch):
        config_file = self._write_config(tmp_path, "# header")
        monkeypatch.chdir(tmp_path)
        loaded = conf.Conf()

        loaded.set_default_nic("eth1")

        assert config_file.read_text(encoding="utf-8") == "# header\ndefault_nic eth1\n"

    def test_set_default_nic_appends_to_empty_file(self, tmp_path, monkeypatch):
        config_file = self._write_config(tmp_path, "")
        monkeypatch.chdir(tmp_path)
        loaded = conf.Conf()

        loaded.set_default_nic("lo")

        assert config_file.read_text(encoding="utf-8") == "default_nic lo\n"

    def test_set_default_nic_creates_a_missing_configuration_file(self, tmp_path):
        loaded = object.__new__(conf.Conf)
        loaded.conf_file = str(tmp_path / "new.conf")
        loaded.default_nic = None

        loaded.set_default_nic("eth2")

        assert (tmp_path / "new.conf").read_text(encoding="utf-8") == "default_nic eth2\n"
