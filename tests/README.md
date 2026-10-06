# Tests

## What is needed

Python 3.13 (the version CI runs) with
`pytest`, `coverage` and `pyyaml`:

    python3 -m pip install pytest coverage pyyaml

Nothing else: no root, no network, no real console and no installed
confconsole package. `tests/conftest.py` puts the repository root on
`sys.path` and, when they are not importable, registers stand-ins for the
Debian-only modules the code imports: `netinfo` (turnkey-netinfo),
`dialog` (pythondialog), `systemd.journal` and `requests`. No dialog
opens: the screens are driven by a scripted fake console. No test touches
`/etc` or the live network.

The tests target Linux, as CI does (`ubuntu-latest`): some use
`os.getuid()` and Unix file modes, so on Windows run them under WSL.

Where `/tmp` carries an ACL that makes new files writable by others
(GitHub Codespaces does: `ls -ld /tmp` ends in `+`), the tests that
write the Keel Cloud flag fail with "writable by group or others". Give
pytest a directory without one by adding `--basetemp=$HOME/pytmp/run` to
the commands below.

## Running them as CI does

From the repository root. The modules to measure are read from `package:`
in `.github/workflows/tests.yml`, the list CI uses, so the command stays
right when a module is added:

    MODULES=$(python -c "import yaml; print(yaml.safe_load(open('.github/workflows/tests.yml'))['jobs']['tests']['with']['package'])")
    PYTHONPATH=. python -m coverage run --branch --source="$MODULES" -m pytest -q tests
    python -m coverage report --show-missing

CI fails when the report is under its threshold; to check that locally:

    python -m coverage report --show-missing --fail-under=100

The threshold is 100 percent, lines and branches, for the measured modules
(set in `.github/workflows/tests.yml`, only ever raised). Which modules are
measured, why `confconsole.py` is not, and the plan for the rest live in
`COVERAGE.md`.

To run the tests without coverage, or one file or test:

    python -m pytest -q tests
    python -m pytest -q tests/test_keelfit.py
    python -m pytest -q tests -k static6

## Skipped tests

A few tests skip unless a real keel is present: the
`TestWithTheRealKeel` classes in `test_keelmenu.py` (needs the `keel`
Python package) and in `test_first_boot.py` and `test_overlay_screen.py`
(needs a `keel` command of version 0.11 or later, found on `PATH` or named
by the `KEEL` environment variable). `python -m pytest -rs tests` lists
them with the reason.

## Layout

- `conftest.py`: shared fixtures, the module stand-ins and the scripted
  fake console.
- Configuration file: `test_conf.py` (`confconsole.conf`, read and
  `default_nic` written back).
- Network: `test_ifutil_parse.py` (stanza parsing and rendering),
  `test_ifutil_interfaces.py` (the interfaces file, on a scratch copy),
  `test_ifutil_system.py` (ifup/ifdown and resolvconf wrappers, stubbed),
  `test_ifutil_static6.py` (the static IPv6 writer),
  `test_confconsole_ifconf6.py` (the static IPv6 dialog).
- Main screen and boxes: `test_confconsole_usage.py` (the usage screen),
  `test_keelbanner.py` (the Keel mark above it), `test_keelfit.py` and
  `test_confconsole_boxes.py` (box sizes on the terminal), `test_brand.py`
  (Keel Linux, not TurnKey, on screen).
- Keel screens: `test_keelcli.py` (the keel client), `test_keelmenu.py`
  (which screens a machine shows), `test_instance_menu.py` (the Instance
  menu entries), `test_database_mode.py` and `test_database_handout.py`
  (database mode), `test_overlay_screen.py` (the overlay network),
  `test_first_boot.py` (first boot role and Keel Cloud key).
- Let's Encrypt: `test_lets_encrypt.py` (the certificate screen and the
  instance description).
