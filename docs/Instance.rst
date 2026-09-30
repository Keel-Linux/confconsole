Instance
========

The Instance menu is a thin client of the ``keel`` command. Every entry
collects at most one answer, runs ``keel`` with an argument list (never a
shell string), and shows what came back: the command line, its output and
one line for the exit code. No check lives in the dialog; the same command
run from a terminal gives the same result and the same code, which is what
makes a headless run and a menu run equivalent.

The spec file is ``/etc/keel/instance.yaml``, or ``$KEEL_SPEC`` when that
variable is set, the same default the command uses.

Entries and their headless equivalents
--------------------------------------

+----------------+-----------------------------------------------------------+
| Entry          | Headless equivalent                                       |
+================+===========================================================+
| View spec      | ``cat /etc/keel/instance.yaml``                           |
|                | ``keel spec validate --no-secret-files``                  |
+----------------+-----------------------------------------------------------+
| Apply spec     | ``keel spec apply --spec /etc/keel/instance.yaml          |
|                | --non-interactive``                                       |
+----------------+-----------------------------------------------------------+
| Show drift     | ``keel diff --format json`` (``--format text`` for the    |
|                | same content as lines)                                    |
+----------------+-----------------------------------------------------------+
| Export spec    | ``keel inspect --output /root/instance.yaml               |
|                | --report /root/instance.report.txt``                      |
+----------------+-----------------------------------------------------------+

View spec
  Shows the spec file as it is on disk, then the report of
  ``keel spec validate --no-secret-files``. Secrets are references in the
  file (a path, or ``generate: true``), so no value is ever on screen;
  ``--no-secret-files`` checks the shape of every reference without
  requiring the files to exist, so the screen works on a machine that does
  not hold the secrets.

Apply spec
  Asks for confirmation, showing the exact command, then runs
  ``keel spec apply --non-interactive`` and shows its output. Exit 0 means
  the spec was applied (or, as the output says, an existing non empty conf
  was left alone); 1 is a usage error; 2 an unreadable spec; 3 an invalid
  spec, every error listed; 4 a missing or badly protected secret; 5 a conf
  file that could not be written.

Show drift
  Runs ``keel diff --format json`` and renders one row per field with four
  columns: field, status (``same``, ``drift``, ``unknown``, ``not
  declared``, ``not compared``), declared and observed. Where nothing was
  observed the reason takes the place of the value. A declared or
  observed cell longer than 40 characters (a list of SSH keys, say) is
  cut with an ellipsis so the table fits the dialog; ``keel diff`` on a
  terminal shows the full values. The summary line
  follows, then the verdict: exit 0 is clean, 13 means no drift but a
  declared field could not be observed, 14 means drift was found.

Export spec
  Asks for the path to write (default ``/root/instance.yaml``), runs
  ``keel inspect --output PATH --report PATH.report.txt`` and shows the
  report. Exit 13 means the spec was written but a required field could not
  be inferred, so the file needs editing before it can be applied; the
  report names the field and why.

Overlay network (WireGuard)
---------------------------

The WireGuard overlay the nodes of a replicated appliance share (handbook
decision 0020), ``network.overlay.wireguard`` in the instance description
(``docs/spec.md`` of keel). The screen configures THIS node's side of it
only; each node adds the others from its own console.

It opens on this node's public key, overlay address, listen port and
peers. The key comes from ``keel network wireguard key``, which makes the
key pair the first time, on this machine, and prints only the public key.
Then:

Address
  This node's overlay address and port. The first time, the field holds
  what ``keel network wireguard suggest-address`` prints: a random unique
  local address (``fd00::/8``), ``::1`` on its /64. The other nodes take
  ``::2``, ``::3`` on the same /64. The other entries appear once there
  is an address.

Add peer
  Another node, as its own screen shows it: its public key, its overlay
  address (routed as one host, ``/128``), its endpoint (``host:port``, an
  IPv6 address in brackets, ``[2001:db8::20]:51820``; blank when that node
  reaches this one) and a keepalive in seconds (25 by default, blank for
  none). A peer with a key already there replaces it.

Remove peer
  Pick the peer by its key; the screen asks before removing it.

Every change is written the way the database screens write theirs: staged
beside the description, checked by ``keel spec validate --no-secret-files``,
committed only when valid (otherwise the description is left exactly as it
was and keel's errors are shown), then applied with ``keel spec apply
--system-only``. keel brings the overlay up under the confirmation window
of decision 0018, and the screen says what that means: the change reverts
by itself when the window ends (120 seconds) unless it is confirmed with
``keel network confirm`` from a NEW session, over the overlay from the
other node (which also tests the overlay) or over this node's usual
address. The screen then offers to confirm from here: keel accepts that
from the machine's own console, and refuses it from an SSH session opened
before the change, in which case the change reverts unless a new session
confirms it.

Headless equivalent: edit ``network.overlay.wireguard`` in the
description, ``keel spec apply --system-only``, then ``keel network
confirm`` from a new session.

When keel is not installed
--------------------------

Every entry shows one message, ``keel is not installed; install the keel
package``, and returns to the menu. Nothing else happens.

Where the code is
-----------------

``keelcli.py`` at the root of the package (installed as
``/usr/lib/confconsole/keelcli.py``, importable from the plugins as
``ifutil`` is from ``confconsole.py``) holds the client: ``call`` runs the
command and is the only function with a side effect; ``describe_exit`` maps
a command and an exit code to a message; ``render_diff`` turns the JSON
document into the table; ``view_text``, ``apply_text``, ``drift_text`` and
``export_text`` compose each screen. The four entries under
``plugins.d/Instance`` each fit in a screen and are loaded by the plugin
manager like every other entry. ``tests/test_keelcli.py`` covers the
client with ``subprocess.run`` replaced, ``tests/test_instance_menu.py``
loads each entry through ``plugin.Plugin`` with a scripted console.

The overlay screen is ``wgcli.py`` (what it builds and says, pure) and
``wgscreen.py`` (the dialog flow), beside ``keelcli.py`` for the same
reason; it shares ``dbscreen.commit`` with the database screens.
``tests/test_overlay_screen.py`` covers both with ``keelcli.call``
replaced, and hands the descriptions the screen builds to a real ``keel
spec validate`` when a keel 0.11 or later is on ``PATH`` or named by
``KEEL``.
