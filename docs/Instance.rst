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

Which screens a machine shows
-----------------------------

The menu offers a screen only where what it configures is part of the
appliance (handbook decision 0041). ``keelmenu.py`` asks keel to resolve
the appliance the spec names (``appliance.name``) along its chain of
manifests under ``/usr/share/keel``, the same resolution as ``keel
manifest show NAME --resolved``, and reads ``installation.mode`` from the
spec.

+-------------------+--------------------------------------------------------+
| Entry             | Offered when                                           |
+===================+========================================================+
| View, Apply,      | always                                                 |
| Show drift,       |                                                        |
| Export spec       |                                                        |
+-------------------+--------------------------------------------------------+
| Database mode     | a ``mariadb``, ``postgresql`` or ``redis`` data        |
|                   | service is in the chain (an overlay that provides the  |
|                   | engine, or a service the application consumes), or the |
|                   | spec declares ``database.server``. Not on Keel Core or |
|                   | Keel Web. The engines are one set,                     |
|                   | ``keelmenu.DATA_ENGINES``                              |
+-------------------+--------------------------------------------------------+
| Database mode >   | only for an engine whose replication keel applies,     |
| Cloud             | MariaDB and PostgreSQL                                 |
|                   | (``keelmenu.REPLICATING_ENGINES``). keel validates a   |
|                   | Redis primary and replica but converges neither, so    |
|                   | Redis offers Standalone only                           |
+-------------------+--------------------------------------------------------+
| Overlay network   | the ``wireguard`` overlay is in the chain. In the menu |
|                   | in ``cloud_simple`` and ``cloud_advanced``; otherwise  |
|                   | behind **Advanced**, configured or not, so it never    |
|                   | moves once an address or a peer is applied             |
+-------------------+--------------------------------------------------------+
| Keel Cloud        | only once Keel Cloud exists: ``/etc/keel/cloud-        |
|                   | endpoint`` holds the service's endpoint. Hidden by     |
|                   | default, and the first boot (``keelfirstboot.py        |
|                   | cloud``, run by inithooks' ``80keel-cloud``) asks no   |
|                   | key either. Writing that file turns both on            |
+-------------------+--------------------------------------------------------+

``/etc/keel/cloud-endpoint`` holds one URL and nothing else (surrounding
whitespace and a final newline are ignored)::

    https://cloud.example.org
    https://[2001:db8::10]:8443/keel

It must be ``https`` with a host, a bracketed IPv6 literal allowed and a
port optional, in a regular file owned by root and writable by neither
group nor others (``install -m 0644 -o root``). A missing file is the
default and is quiet; any other failure keeps Keel Cloud hidden and is
logged as ``Keel Cloud stays hidden: /etc/keel/cloud-endpoint: <why>``.

When the chain cannot be read (keel or the manifests missing, as on a
machine of before 0041, or a spec that names no appliance) the screens are
offered as before, the overlay behind Advanced.

Every menu is as wide as its widest line, up to what the terminal leaves
(``keelfit.py``), and no box is taller than the terminal; a description
is shortened with an ellipsis only when even the full width is too
narrow. The Keel screens' own descriptions fit an 80 column console.

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
  This node's address on Keel's private mesh, not an address on the LAN,
  and the UDP port the other nodes reach it on. The first time, the field
  holds what ``keel network wireguard suggest-address`` prints: a randomly
  generated unique local address (``fd00::/8``), ``::1`` on its /64. The
  first node keeps it; the other nodes take ``::2``, ``::3`` on the same
  /64. The other entries appear once there is an address.

Add peer
  Another node, as its own screen shows it: its public key, its overlay
  address (routed as one host, ``/128``), its endpoint (``host:port``, an
  IPv6 address in brackets, ``[2001:db8::20]:51820``; blank when that node
  reaches this one) and a keepalive in seconds (25 by default, blank for
  none). A peer with a key already there replaces it. This node's own
  public key, and one of this node's own mesh addresses, are refused; an
  address outside this node's prefix is asked about (a peer is routed as
  one host, so it still works). Either way the form comes back with what
  was typed.

Confirm now
  First, while a network change waits for its confirmation; the screen's
  first line then says the time it reverts at, in UTC. It runs ``keel
  network confirm`` from this session and shows keel's verdict: keel
  accepts it from the machine's console (or a process attached from a
  container's host) and from an SSH session opened after the change over
  the new configuration, and refuses it from a session opened before. The
  screen does not judge the session itself.

Remove peer
  Pick the peer by its key; the screen asks before removing it.

Every change is written the way the database screens write theirs: staged
beside the description, checked by ``keel spec validate --no-secret-files``,
committed only when valid (otherwise the description is left exactly as it
was and keel's errors are shown), then applied with ``keel spec apply
--system-only --non-interactive --defer-certificate --skip-uplink``.
Unlike the database screens it does not pass ``--skip-network``: bringing
the overlay up is what it is for. It passes ``--skip-uplink`` instead, so
adding or removing a peer never moves ``network.interfaces``, the
interface the operator may have come in on, even when the description
declares a change there. keel brings the overlay up under the
confirmation window of decision 0018, and the screen says what that
means: the change reverts by itself when the window ends (120 seconds)
unless it is confirmed with ``keel network confirm`` from a NEW session,
over the overlay from the other node (which also tests the overlay) or
over this node's usual address. The screen says so whenever a network
change waits after apply: one this run brought up, even if a later step
failed; one that failed and could not be rolled back either, which keel
leaves to its revert timer; or one an earlier run left, which keel names
when it refuses another. It needs keel 0.11.0 or later, the first with
``--skip-uplink``, which the package recommends. It then offers to
confirm from here, Yes by default: keel accepts that from the machine's
own console, and refuses it, changing nothing, from an SSH session
opened before the change. When the change still waits after that (No,
or a refusal), the screen gives the time it reverts at, in UTC, read
from keel's marker (``/var/lib/keel/network/pending.json``: the window
starts when the interface comes up), and the command, ``keel network
confirm``, to run from a new session.

Headless equivalent: edit ``network.overlay.wireguard`` in the
description, ``keel spec apply --system-only --skip-uplink``, then ``keel
network confirm`` from a new session.

Database mode
-------------

Handbook decisions 0013 and 0076. Standalone configures THIS node and
nothing else: it writes ``database.server`` of the instance description,
checks it with ``keel spec validate`` before it replaces the file, and
runs ``keel spec apply --system-only --non-interactive --skip-network
--defer-certificate``. A fresh appliance with no description gets one
started (``version: 1`` plus the database section). The console sends no
SQL; what a role means, and every refusal, is keel's.

::

    Database mode
      Standalone              one server, what the appliance is today
      Cloud
        Primary               First node: the mesh, the invites, the VIP
        Replica               Second node: the join, the pair, the copy
        Promote this replica  an explicit act, never automatic

Standalone
  One field, the addresses the server answers on. No second screen.

Primary and Replica
  The first boot's flows of a cloud node (decision 0076), run again: a
  step that is done is not done again. They need a cloud mode
  (``installation.mode``); a simple node is told so. See "The first boot"
  below.

Promote this replica
  On a node of a pair (``appliance.vip``) it asks Planned or Old primary
  gone, and runs ``keel database promote``, with
  ``--old-primary-gone`` for the second: keel moves the VIP first and the
  database follows it, and the role the description declares is
  information, not drift. On a node without a VIP it asks first, saying
  that nothing stops the old primary, and the description then still says
  replica, which ``keel diff`` reports as drift.

The first boot
--------------

``keelfirstboot.py mode``, then ``role``, then ``cloud``
(inithooks ``75keel-role`` and ``80keel-cloud``). The screen titles are
fixed strings, which the commissioning driver of decision 0075 matches.

Installation mode
  Simple, Cloud simple or Cloud advanced: only the modes the appliance's
  manifest allows (``modes:``, ``keel.manifest.facts.gather``). It writes
  ``appliance.name`` (the declared one, else the installed appliance no
  other is built on), ``installation.mode`` and every overlay of the
  chain at that mode's column, then applies. Skipped when the
  description declares ``installation.mode``. Under keel-init a node
  with a mode sees it, and a Cloud simple node may move to Cloud advanced
  (decision 0057; then ``keel mesh etcd form`` on the node that made the
  mesh). An appliance that allows one mode records it with no screen.

Role of this node
  Cloud simple: Primary or Replica. Cloud advanced: Primary, Replica,
  and Witness where the manifest says ``witness: true`` (Keel Core). A
  simple node has no role screen: a database appliance records
  ``database.server.role: standalone``.

Make the mesh
  ``keel mesh create``, on the primary when it has no mesh.

Invite a node
  ``keel mesh invite --json``, once per node: the replica, and in cloud
  advanced the witness after it. A box says what the line is for; then
  the line itself is printed as plain text, on one line, outside any
  dialog (a dialog wraps it, and its text is in the process list). The
  invite carries the VIP of the pair, which the primary writes as its
  ``appliance.vip``, with its server (role primary, its overlay address
  added to ``listen``), and applies.

Waiting for the nodes
  ``keel mesh status --json`` every 5 s: the member at the invited
  address, and in cloud advanced etcd with 3 healthy voters (the VIP is
  taken only then, so that its claim gets an etcd lease). Back gives Check
  again, Paste accept line, Show the line, Later.

Paste accept line
  ``keel mesh accept -``, with the ``keel1a:`` line the joining node
  printed when it could not reach the inviter.

Join a mesh
  The replica and the witness paste the invite line; ``keel mesh join
  -`` reads the token on standard input, never in the process list. Its
  output, the ``keel1a:`` fallback line among it, goes to the terminal as
  it comes.

Primary of the pair
  On a replica with more than one member, which member is the primary.

Pair with the primary
  The replica writes the VIP the join received, the VIP overlay on, and
  its server (role replica, ``replication.primary.host`` the primary's
  overlay address); in cloud advanced once etcd has 3 voters. Before
  anything changes it warns that the data on this node is replaced. Then
  ``keel vip pair``, a wait for the primary to take the VIP, and the
  apply; keel's refusal to drop local databases is shown word for word
  and only a second Yes adds ``--destroy-local-database``. No puts the
  description back as it was. Keel Web writes no server: its pair is one
  of files (Syncthing). Keel Core pairs nothing.

Take the VIP
  The primary, once the replica has paired (keel keeps the pair record in
  ``/var/lib/keel/vip/<vip>.pair``; Back > Take it now does not wait for
  it): ``keel spec apply``, then ``keel vip promote``.

Status of this node
  ``keel vip status``, ``keel mesh status`` and ``keel database status``,
  read only.

No password, key, address, port or VIP is typed on either node: only the
invite line is copied. A step that has a question and no terminal to ask
it on exits 75, and inithooks leaves it to keel-init.

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
reason; it uses ``dbscreen.call`` and ``dbscreen.format_fields`` of the
database screens.
``tests/test_overlay_screen.py`` covers both with ``keelcli.call``
replaced, and hands the descriptions the screen builds to a real ``keel
spec validate`` when a keel 0.11 or later is on ``PATH`` or named by
``KEEL``.
