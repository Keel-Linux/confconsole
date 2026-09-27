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
`turnkey-netinfo`, which is not on PyPI; `tests/conftest.py` registers a
stub module with the same two names when the real one is not importable,
so the parsers can be tested on any host):

    PYTHONPATH=. python3 -m coverage run --branch --source=ifutil -m pytest -q tests
    python3 -m coverage report --show-missing

`--source` names the modules that have tests; a module is appended as its
tests land, so the reported number is the number of the files the tests
actually exercise (same semantics as the shell gate, which only reports
files the tests execute). The caller `.github/workflows/tests.yml` passes
the same list as `package:` to the reusable `test-python.yml` and the
threshold as `threshold:`; the threshold is only ever raised. Shell, per
decision 0004: bats files under `tests/`, external commands (`dehydrated`,
`systemctl`, `curl`, `netstat`, `ip`, `ifup`) replaced by stubs first in
PATH, kcov for the line count, `tests/coverage.sh` failing below
`COVERAGE_THRESHOLD`.

The baseline pull request (#1) created the check with the `test-shell.yml`
bootstrap placeholder at threshold 0, because `test-python.yml` cannot run
without a test file (pytest exits 5 when it collects nothing); pull
request #2 switched the caller to `test-python.yml` with the number below.

## Measured on 2026-09-26 with the first tests

| File | Tests | Stmts | Branches | Cover |
|------|-------|-------|----------|-------|
| ifutil.py | 103 (tests/test_ifutil_parse.py, test_ifutil_interfaces.py, test_ifutil_system.py) | 438 | 196 | 99.21 percent; 3 statements missed (lines 216 to 218, the inner function `format_value` of `_merge_iface_options`, which nothing calls); 0 partial branches |

Threshold in the caller: 99. Every other file: 0 percent, no test.

Two observations recorded while writing the tests, both left as they are
because these tests change no behaviour: `_merge_iface_options` keeps an
existing `hostname` line after the new one when both are given (the key
is popped from the new options before the override check), and
`format_value` is dead code. Both belong to the static IPv6 pull request
(plan 04, section 3.2), which touches that function.

## Measured on 2026-09-26 with the static IPv6 change

| File | Tests | Stmts | Branches | Cover |
|------|-------|-------|----------|-------|
| ifutil.py | 152 in the three files above plus tests/test_ifutil_static6.py, and 3 in tests/test_confconsole_ifconf6.py (`get_ip6conf`) | 551 | 230 | 100 percent, 0 missed, 0 partial |
| confconsole.py | 20 in tests/test_confconsole_ifconf6.py: `format_fields`, `_ifconf_staticipv6`, `_get_netmenu`, `_get_ifconfmenu`, `_get_ifconftext` | 811 before the change | | not measured, see below |

Total 175 tests. Threshold in the caller: 100, the measured number for the
measured package (`ifutil`). The two observations above are resolved:
`_merge_iface_options` writes a single hostname line and `format_value`
is gone.

confconsole.py is exercised without launching a dialog: `tests/conftest.py`
registers stubs for the `dialog` and `systemd.journal` modules when they
are not importable, `TurnkeyConsole` is created without `__init__`, its
`console` is replaced by a scripted fake and the `ifutil` calls are
recorded. The file is not added to `package:` because the gate measures
the package as a whole and the rest of confconsole.py (usage screen,
installer, plugin dispatch, the IPv4 form) has no tests yet; adding it
would report about 15 percent and the threshold could not be honoured.
It joins the measured set when plan item 5 below is executed; until then
the new dialog code is tested but its number is not part of the gate.

## Measured on 2026-09-26 with the IPv6-first usage screen

| File | Tests | Stmts | Branches | Cover |
|------|-------|-------|----------|-------|
| ifutil.py | 155 as above (unchanged file) | 551 | 230 | 100 percent, 0 missed, 0 partial |
| confconsole.py | 57 in tests/test_confconsole_ifconf6.py and tests/test_confconsole_usage.py: `format_fields`, `render_usage_line`, `render_usage`, `ipv6_lines`, `describe_interface`, `_ifconf_staticipv6`, `_get_netmenu`, `_get_ifconfmenu`, `_get_ifconftext`, `usage` | 646 | 236 | 38 percent measured locally with `--source=ifutil,confconsole`; the touched and new functions have 0 missed lines and 0 partial branches; the 4 partial branches left are in `_get_ifconftext` (untouched) |

Total 212 tests. Threshold in the caller: 100, unchanged, for the measured
package (`ifutil`). confconsole.py stays out of `package:` for the reason
given above; the number it would report went from about 15 percent to 38
percent with the usage screen tests (`usage()` runs with
`subprocess.run`, `conf.path`, `netinfo.get_hostname` and the address
readers stubbed). The shared dialog fixtures (`FakeConsole`, `tc`,
`net_stubs`) moved to `tests/conftest.py` so every confconsole test file
uses the same stubbing.

## Measured on 2026-09-26 with the Instance menu

| File | Tests | Stmts | Branches | Cover |
|------|-------|-------|----------|-------|
| ifutil.py | 155 as above (unchanged file) | 551 | 230 | 100 percent, 0 missed, 0 partial |
| keelcli.py (new: the keel client of the Instance menu) | 50 in tests/test_keelcli.py: `spec_path`, `report_path`, `call` with `subprocess.run` replaced, the `KeelNotInstalled` path, `describe_exit` for every code of every command, `read_text`, `format_value`, `clip`, `diff_rows`, `align`, `summary`, `render_diff`, the four screen texts | 104 | 16 | 100 percent, 0 missed, 0 partial |
| plugins.d/Instance (new: View_spec, Apply_spec, Show_drift, Export_spec) | 17 in tests/test_instance_menu.py: each entry loaded through `plugin.Plugin` and run with a scripted console and `keelcli.call` replaced; the missing keel message, cancel paths, the exit code messages | 52 | 4 | 100 percent, 0 missed, 0 partial |
| confconsole.py | 57 as above (unchanged file) | 646 | 236 | 38 percent, not measured, as above |

Total 279 tests. Threshold in the caller: 100, unchanged; the measured
package is now `ifutil,keelcli,plugins.d/Instance`. The Instance menu is
the first plugin directory written under brief section 6 (no logic in the
dialogs): the entries only collect input, call `keel` through `keelcli`
and show its text, so they are measured at 100 percent alongside the
client. `keelcli.py` lives at the package root, next to `ifutil.py`,
because `plugin.py` loads entries with `spec_from_file_location` and
never adds the plugin directory to the import path; the root is already
on it. `tests/conftest.py` gained `FakeConsole.inputbox`.

## Measured on 2026-09-26 with the mark on the usage screen

| File | Tests | Stmts | Branches | Cover |
|------|-------|-------|----------|-------|
| ifutil.py | 155 as above (unchanged file) | 551 | 230 | 100 percent, 0 missed, 0 partial |
| keelbanner.py (new: which mark goes above the usage screen, and where) | 22 in tests/test_keelbanner.py: `terminal_size` (reported and fallback), `mark_size`, `fits` (too tall, too wide, empty), `read` (present and absent), `choose` (under the floor, full, small, none, a mark not installed), `above`, `added_rows` | 43 | 14 | 100 percent, 0 missed, 0 partial |
| keelcli.py | 50 as above (unchanged file) | 104 | 16 | 100 percent, 0 missed, 0 partial |
| plugins.d/Instance | 17 as above (unchanged file) | 52 | 4 | 100 percent, 0 missed, 0 partial |
| confconsole.py | 63 in tests/test_confconsole_ifconf6.py and tests/test_confconsole_usage.py, the 6 new ones in `TestUsageMark` | 656 | 238 | 39 percent measured locally, up from 38; the touched lines (`usage`, `Console.msgbox`) have 0 missed and 0 partial |

Total 307 tests. Threshold in the caller: 100, unchanged; the measured
package is now `ifutil,keelbanner,keelcli,plugins.d/Instance`.

The console is a brand surface, so the usage screen carries the mark the
core overlay installs (`/etc/keel/banner.txt` and
`/etc/keel/banner-small.txt`), the same two files the login banner
reads. The decision is a module of its own, `keelbanner.py`, next
to `keelcli.py` and for the same reason: `plugin.py` loads entries with
`spec_from_file_location` and never adds the plugin directory to the
import path, and the repository root is already on it. `usage()` gained
five lines that ask it for a mark and grow the box by what the mark
takes; `Console.msgbox` gained an optional `height`, defaulting to the
box height it always used.

What the module enforces is the rule of the terminal surface: the mark
never costs the screen a line of what it already says. It is dropped to
the small mark, and then to nothing, before the usage text loses a row.
A terminal under 24 rows gets no mark at all; above that a mark needs the
25 rows of the usage box plus its own rows and the blank line between
them, whatever the installed art measures, so an 80 by 24 console and a
narrow serial line both keep the screen exactly as it was.
`tests/conftest.py` gained `FakeConsole.msgbox_kwargs` so a test can read
the height the box was asked for, and the `usage_env` fixture pins the
terminal size and the installed marks, so the existing usage tests do
not depend on the host carrying `/etc/keel`.

## Measured on 2026-09-27 with the centred mark

| File | Tests | Stmts | Branches | Cover |
|------|-------|-------|----------|-------|
| ifutil.py | 155 as above (unchanged file) | 551 | 230 | 100 percent, 0 missed, 0 partial |
| keelbanner.py | 41 in tests/test_keelbanner.py, up from 22: the 11 in `TestCenter` (an odd and an even leftover, a mark wider than the width, a mark exactly the width, a blank line, a line of spaces, trailing whitespace in the art, no trailing whitespace on the block, one indent for every line, the row count, plain ASCII), `inner_width` (the frame, and the width `fits` and `center` share), `mark_size` on blocks of several shapes including ragged and empty, and the fallback ladder on a shrinking screen | 52 | 16 | 100 percent, 0 missed, 0 partial |
| keelcli.py | 50 as above (unchanged file) | 104 | 16 | 100 percent, 0 missed, 0 partial |
| plugins.d/Instance | 17 as above (unchanged file) | 52 | 4 | 100 percent, 0 missed, 0 partial |
| confconsole.py | 68 in tests/test_confconsole_ifconf6.py and tests/test_confconsole_usage.py, the 8 in `TestUsageMark` | 658 | 238 | 39 percent measured locally, unchanged; the touched lines (`usage`) have 0 missed and 0 partial |

Total 328 tests, up from 307. Threshold in the caller: 100, unchanged;
the measured package is unchanged. Command:

    PYTHONPATH=. python3 -m coverage run --branch \
      --source=ifutil,keelbanner,keelcli,plugins.d/Instance -m pytest -q tests
    python3 -m coverage report --show-missing

Two defects were fixed. The mark was prepended as it was read, so it sat
against the left edge of the dialog instead of under its middle;
`keelbanner.center` now shifts the whole block by one indent, measured
from the widest line, which keeps the mark's internal alignment (padding
each line on its own would not) and never truncates a mark as wide as the
box or wider. The width is `keelbanner.inner_width(cols)`, the one
definition `fits` measures against, so the width a mark is admitted on
and the width it is centred on cannot disagree. Only the mark is centred;
the usage text keeps its own left margin.

The second defect was documentation and tests stating how big the art is,
which is not this module's business: the art lives in the core overlay
and is redrawn there. The module docstring no longer names a size, the
fixtures in both test files are synthetic blocks of an arbitrary size
rather than copies of the shipped marks, and every expectation, including
the rows each terminal admits and the indent the screen gives, is derived
from the size the fixture itself measures. Redrawing the art changes no
test.

## Plan to reach 90 percent per file

Priority order (size: small under 30 lines of test, medium under 150,
large above). Addresses in fixtures are IPv6 wherever the code accepts
them, for example `2001:db8:1::10/64` with gateway `2001:db8:1::1` and
nameserver `2001:db8::53`.

1. `ifutil.py` (663 lines, large). Done on 2026-09-26 at 99.21 percent,
   then 100 percent with the static IPv6 change (`set_static6`,
   `set_dhcp6`, `get_ip6conf`, `_list_ipv6_global`, the IPv6 validators),
   see the tables above. First because the static IPv6 writer
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
   class then stays thin. `_ifconf_staticipv6` (plan 04 section 3.2) was
   written that way on 2026-09-26, with the stubbing in place in
   `tests/conftest.py` and `tests/test_confconsole_ifconf6.py` as the
   pattern for the rest of the file. The usage template rendering
   followed the same day (`render_usage`, `render_usage_line`,
   `describe_interface`, pure functions; `usage()` tested with stubs), and
   the mark above it the same way (`keelbanner.py`, measured at 100
   percent; `usage()` only asks it what fits).
   Left: `_ifconf_staticip._validate`, `_validip`, `_get_default_nic`,
   `_get_filtered_ifnames`, `_get_advmenu`, the installer and the loop.
6. `plugins.d` Python, smallest first (the Instance directory is done,
   see above, and is the pattern for the rest: a client module without a
   dialog, entries that only collect input and show text):
   Security_Update, tzdata,
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
