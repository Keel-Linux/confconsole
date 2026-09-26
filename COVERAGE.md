# Test coverage baseline

Measured on 2026-09-26 against master 0f37b48, following the project
decisions 0003 (90 percent floor per repository, 95 percent for every file
our changes touch), 0004 (shell: bats plus kcov) and 0006 (the gate runs in
GitHub Actions and is a required status on the default branch).

The fork's master was fast-forwarded to upstream master the same day: its
previous tip a2d9f70 (2025-10-02) was 50 commits behind and lacked the
IPv6-aware rewrite of `ifutil.py` (upstream pull request #109), which is
the file the static IPv6 work starts from.

## Baseline: 0 percent measured

There is no `tests/` directory, no pytest or unittest suite and no
coverage configuration. `.travis.yml` only built the Debian package on a
service that no longer exists. Nothing is measured, so the baseline is 0
percent, not an estimate.

Line counts are lines neither blank nor comment; `debian/` is packaging and
is excluded. Inventory command:

    git ls-files | grep -v '^debian/' | while read f; do
      h=$(head -1 "$f"); k=""
      case "$f" in *.py) k=py;; *.sh) k=sh;;
        *) case "$h" in *python*) k=py;; *bash*|*/bin/sh*) k=sh;; esac;; esac
      [ -n "$k" ] && echo "$k $(grep -cvE '^\s*(#|$)' "$f") $f"
    done

| Group | Files | Lines | Measured |
|-------|-------|-------|----------|
| confconsole.py (dialog driver, menus, usage screen) | 1 | 811 | 0 percent, no test |
| ifutil.py (`/etc/network/interfaces` parsing and rendering, ifup/ifdown wrappers) | 1 | 663 | 0 percent, no test |
| plugin.py, conf.py, ipaddr.py | 3 | 368 | 0 percent, no test |
| plugins.d Python (get_certificate 386, dns_01 172, mail_relay 142, hostname 115, Secupdates_adv_conf 99, add-water-srv 75, apt 65, cert_auto_renew 49, keyboard 46, Confconsole_auto_start 46, example 28, add-water-client 26, locales 26, tzdata 14, Security_Update 7) | 15 | 1296 | 0 percent, no test |
| Shell (dehydrated-wrapper 268, turnkey-lexicon 77, hook-dns-01 72, mail_relay.sh 63, hook-http-01 48, dehydrated-confconsole.cron 27, confconsole-auto 20) | 7 | 575 | 0 percent, no test |

Total: 20 Python files (3138 lines) and 7 shell files (575 lines), 0
percent measured. `dialog.pyi` is a type stub, `docs/`, `conf/`, `share/`
data files and `release_notes/` are not code.

## How it is measured

Python, from the repository root (`netinfo` comes from the Debian package
`turnkey-netinfo`, which is not on PyPI; the tests provide a stub module
so the parsers can be imported on any host):

    PYTHONPATH=. python3 -m coverage run --branch --source=. -m pytest -q tests
    python3 -m coverage report --show-missing

Inherited modules without tests are listed under `omit` in
`pyproject.toml` once it exists, one entry to remove per module as its
tests land, so the reported number is the number of the files the tests
actually exercise (same semantics as the shell gate). Shell, per decision
0004: bats files under `tests/`, external commands (`dehydrated`,
`systemctl`, `curl`, `netstat`, `ip`, `ifup`) replaced by stubs first in
PATH, kcov for the line count, `tests/coverage.sh` failing below
`COVERAGE_THRESHOLD`.

The gate is `.github/workflows/tests.yml`. On this branch it calls
`test-shell.yml` with threshold 0, which passes with a bootstrap notice
because nothing is measured yet; `test-python.yml` cannot run without a
test file (pytest exits 5 when it collects nothing). The pull request that
adds the first test switches the caller to `test-python.yml` and sets the
threshold to the measured number. The threshold is only ever raised.

## Plan to reach 90 percent per file

Priority order (size: small under 30 lines of test, medium under 150,
large above). Addresses in fixtures are IPv6 wherever the code accepts
them, for example `2001:db8:1::10/64` with gateway `2001:db8:1::1` and
nameserver `2001:db8::53`.

1. `ifutil.py` (663 lines, large). First because the static IPv6 writer
   (plan 04, section 3.2) changes `NetworkInterfaces.set_static()`,
   `set_dhcp()`, `set_manual()`, `gen_default_if_config()` and the
   `inet_family` defaults, and no change lands there without a test.
   Pure functions to cover first: `_preprocess_interface_config`,
   `_list_to_data`, `_data_to_list`, `_get_raw_opts`,
   `_merge_iface_options`, `_strip_static_opts`, `_valid_ip`,
   `IPv4.parse`, `NetworkInterfaces` (`read` and `write` take a
   `conf_file` argument, so a scratch file replaces
   `/etc/network/interfaces`), `_parse_resolv`. Then the thin wrappers
   with stubs: `ifup`, `ifdown`, `get_ipv6conf` (a stub `ip` output with a
   `2001:db8::/64` address), `get_ifmethod`, `get_nameservers`,
   `unconfigure_if`, module `set_static` and `set_dhcp`, `get_ipconf`
   (`InterfaceInfo` stubbed, `sleep` replaced).
2. `ipaddr.py` (72, small): `is_legal_ip`, `IP` arithmetic, `IPRange`
   from CIDR and containment. Plan 04 item A3 makes `is_legal_ip` accept
   IPv6; the test comes first.
3. `conf.py` (73, small): every `op` of `Conf._load_conf` on a scratch
   file, the illegal line error, `path()` lookup order.
4. `plugin.py` (223, medium): plugin discovery from a scratch
   `plugins.d`, ordering, `description` files, `impByPath`, event
   manager.
5. `confconsole.py` (811, large): the dialogs hold logic today (the
   static form validator `_ifconf_staticip._validate`, `_validip`, the
   usage template rendering, the "not configured" decision of the
   network menu). Per brief section 6 that logic moves into functions
   without a dialog, tested directly with `dialog` stubbed; the dialog
   class then stays thin. Plan 04 section 3.2 adds `_ifconf_staticipv6`
   the same way.
6. `plugins.d` Python, smallest first: Security_Update, tzdata,
   add-water-client, locales, example, Confconsole_auto_start, keyboard,
   cert_auto_renew (small each); apt, add-water-srv (request each route
   on `[::1]`), Secupdates_adv_conf, hostname, mail_relay (medium);
   dns_01 and get_certificate (medium to large, `requests`, `lexicon`
   and `dehydrated` stubbed).
7. Shell (decision 0004): confconsole-auto, dehydrated-confconsole.cron,
   hook-http-01, mail_relay.sh, hook-dns-01, turnkey-lexicon (small
   each); dehydrated-wrapper (268, large: split the port check, domain
   parsing and service handling into a sourceable library, stubs for
   `dehydrated`, `systemctl`, `netstat`, `curl`).
