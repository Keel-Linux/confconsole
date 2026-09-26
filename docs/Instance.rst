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
