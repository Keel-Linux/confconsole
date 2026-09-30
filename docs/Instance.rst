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

Database mode
-------------

Handbook decision 0013. MariaDB only for now. Every screen configures
THIS node and nothing else, writes ``database.server`` of the instance
description, checks it with ``keel spec validate`` before it replaces the
file, and runs ``keel spec apply --system-only --non-interactive
--skip-network --defer-certificate``: saving a database mode never
touches the network or asks for a certificate. A fresh appliance with no
description gets one started (``version: 1`` plus the database section).
The console sends no SQL; what a role means, and every refusal, is
keel's. Every Cloud screen says that this replication has no automatic
failover.

::

    Database mode
      Standalone              one server, what the appliance is today
      Cloud
        Primary               other nodes replicate from this one
        Replica               this node replicates from another
        Promote this replica  an explicit act, never automatic

Standalone
  One field, the addresses the server answers on. No second screen.

Primary
  Asks for the addresses the server answers on (a loopback only answer is
  prefilled with this node's own addresses in front, IPv6 first), the
  origins allowed to replicate (prefilled with this node's /64, public
  before unique local, such as ``2001:db8:1::/64``; a prefix is preferred,
  a single address works, a name is accepted and fragile) and the password
  file (``/etc/keel/secrets/replication_password``). An empty origin list
  authorizes nobody: keel drops every replication account, and the
  handout says so first. When the password file holds nothing the screen
  offers to generate a password; No lets the operator type one. After the
  apply it shows what each replica needs::

      Replicate from (address), IPv6 first:
        2001:db8:1::10
        (with a port it is written [2001:db8:1::10]:3306; type the bare address)
      Allowed to replicate: 2001:db8:1::/64
      Port: 3306 (leave the field blank)
      Replication account: repl (keel names it; both ends use it)
      Password kept in: /etc/keel/secrets/replication_password

  followed by a generated password, shown this once. If the apply failed
  the handout starts with THIS NODE IS NOT READY and still shows the
  password, which is already in its file. A password already in the file
  is kept and never shown.

Replica
  Asks for the primary's literal address, a port (blank for the default)
  and the addresses this node answers on, then for the replication
  password, hidden (a blank keeps the one already in the file). Before
  anything changes it warns that becoming a replica replaces the data on
  this node with a copy of the primary; No leaves everything as it was. If
  keel then refuses because the server holds databases of its own, its
  refusal is shown word for word and only a second Yes adds
  ``--destroy-local-database``. No to that question puts the description
  and the password file back as they were and, when the old description
  declares a database server, applies it again, because keel had already
  rewritten the server's configuration before it refused. keel converges
  only what a description declares, so when the old one declares no
  server the screen says the replica configuration stays until a database
  mode is applied. A pasted ``[address]`` is stored bare.

Promote this replica
  Asks first, saying that nothing stops the old primary, and runs
  ``keel database promote``. The description then still says replica,
  which ``keel diff`` reports as drift until the Primary screen is used.

The password is written to its file (root, 0600, directory 0700) all at
once, a new file replacing the old, after the description validated and
before it is committed, so a refused description leaves no credential
behind. It never appears in an argument list: keel reads it from the
file, and the handout that shows it is a dialog textbox reading a file in
a private 0700 directory removed when the box closes, not a msgbox, whose
text dialog would receive as an argument readable by anyone in
``/proc/PID/cmdline``. The password box runs with that private directory
as ``TMPDIR``, so a temporary file of pythondialog's does not outlive a
dropped session in ``/tmp``.

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
