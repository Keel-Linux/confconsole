#!/usr/bin/env bats
# Tests for share/autostart/confconsole-auto, which ~/.bashrc.d sources at
# a login and which opens confconsole when "autostart" says so.
#
# On BR2, 2026-11-05, on a WordPress LXC whose first boot left the root
# password to keel-init:
# - the first login opened confconsole and spent "autostart once", and
#   keel-init never ran: ~/.profile reads ~/.bashrc before ~/.profile.d,
#   where the profile fence starts keel-init;
# - `pct exec CT -- bash -c ...` from an ssh session, a shell that is not
#   interactive, read ~/.bashrc because bash saw SSH_CLIENT, ran confconsole
#   with no terminal (a DialogError traceback) and spent "once" too.
#
# The login is an interactive bash on a new pty whose rc file sources the
# script; confconsole, sudo, whoami and keel-init are stubs on PATH, and
# the configuration file and HOME are scratch paths.

bats_require_minimum_version 1.5.0

REPO=$(cd "$BATS_TEST_DIRNAME/.." && pwd)
SCRIPT=$REPO/share/autostart/confconsole-auto

setup() {
    STUBS=$BATS_TEST_TMPDIR/stubs
    mkdir -p "$STUBS"
    PATH=$STUBS:$PATH
    stub confconsole
    stub sudo 'exec "$@"'
    stub whoami 'echo root'
    stub keel-init 'exit 0'
    export CONFCONSOLE_CONF=$BATS_TEST_TMPDIR/confconsole.conf
    export HOME=$BATS_TEST_TMPDIR/home
    mkdir -p "$HOME/.profile.d"
    export TERM=xterm
    unset SSH_CLIENT
    autostart once
    RC=$BATS_TEST_TMPDIR/rc
    # kcov (tests/coverage.sh) traces bash through BASH_ENV, which an
    # interactive bash does not read: the rc file reads it
    cat > "$RC" <<EOF
if [ -n "\${BASH_ENV:-}" ]; then . "\$BASH_ENV"; fi
source '$SCRIPT'
echo login-went-on
exit 0
EOF
}

# stub NAME [BODY]
# Writes the stub NAME, which records its arguments in NAME.calls and then
# runs BODY (default: exit 0).
stub() {
    {
        echo '#!/bin/bash'
        echo "printf '%s\\n' \"\$*\" >> '$STUBS/$1.calls'"
        echo "${2:-exit 0}"
    } > "$STUBS/$1"
    chmod +x "$STUBS/$1"
}

# calls NAME: the recorded calls of stub NAME
calls() {
    cat "$STUBS/$1.calls" 2>/dev/null || true
}

# autostart VALUE: the configuration file with "autostart VALUE"
autostart() {
    printf 'networking true\nautostart %s\n' "$1" > "$CONFCONSOLE_CONF"
}

# setting: the autostart value the configuration file has now
setting() {
    sed -En 's|^autostart +([a-z]+).*|\1|p' "$CONFCONSOLE_CONF"
}

# login [OUTPUT]
# An interactive bash that sources the script, on a new pty for its
# standard input, output and error. With OUTPUT "pipe", standard output is
# a pipe instead. Prints what the pty showed.
login() {
    timeout 30 python3 - "${1:-pty}" bash --rcfile "$RC" -i <<'PY'
import os, pty, select, subprocess, sys
mode, cmd = sys.argv[1], sys.argv[2:]
master, slave = pty.openpty()
out = subprocess.PIPE if mode == "pipe" else slave
# close_fds=False: the descriptor kcov traces on must reach bash
proc = subprocess.Popen(cmd, stdin=slave, stdout=out, stderr=slave,
                        start_new_session=True, close_fds=False)
os.close(slave)
seen = b""
while True:
    ready, _, _ = select.select([master], [], [], 20)
    if not ready:
        break
    try:
        data = os.read(master, 4096)
    except OSError:
        break
    if not data:
        break
    seen += data
if mode == "pipe":
    seen += proc.stdout.read()
proc.wait()
sys.stdout.write(seen.decode(errors="replace"))
sys.exit(proc.returncode)
PY
}

# --- when confconsole opens ---------------------------------------------

@test "a login on a terminal opens confconsole once, and spends once" {
    run login

    [ "$status" -eq 0 ]
    [[ "$output" == *login-went-on* ]]
    [ "$(wc -l < "$STUBS/confconsole.calls")" -eq 1 ]
    [ "$(setting)" = false ]
    [ "$(calls keel-init)" = "--status" ]
}

@test "autostart true opens confconsole at every login" {
    autostart true

    run login

    [ "$status" -eq 0 ]
    [ -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = true ]
}

@test "a sudo admin opens confconsole through sudo" {
    stub whoami 'echo admin'

    run login

    [ "$status" -eq 0 ]
    [ "$(calls sudo)" = confconsole ]
    [ -e "$STUBS/confconsole.calls" ]
}

@test "without keel-init confconsole opens" {
    rm "$STUBS/keel-init"

    run login

    [ "$status" -eq 0 ]
    [ -e "$STUBS/confconsole.calls" ]
}

# --- when it does not ---------------------------------------------------

@test "autostart false opens nothing" {
    autostart false

    run login

    [ "$status" -eq 0 ]
    [[ "$output" == *login-went-on* ]]
    [ ! -e "$STUBS/confconsole.calls" ]
}

@test "a dumb terminal opens nothing and keeps once" {
    export TERM=dumb

    run login

    [ "$status" -eq 0 ]
    [ ! -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = once ]
}

@test "a shell that is not interactive opens nothing and keeps once" {
    # what bash -c does under pct exec from an ssh session
    export SSH_CLIENT="192.0.2.1 50000 22"

    run bash -c "source '$SCRIPT'; echo went-on"

    [ "$status" -eq 0 ]
    [ "$output" = went-on ]
    [ ! -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = once ]
}

@test "an interactive shell whose output is not a terminal opens nothing" {
    run login pipe

    [ "$status" -eq 0 ]
    [[ "$output" == *login-went-on* ]]
    [ ! -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = once ]
}

@test "an interactive shell whose input is not a terminal opens nothing" {
    run bash --rcfile "$RC" -i < /dev/null

    [ "$status" -eq 0 ]
    [ ! -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = once ]
}

@test "an armed profile fence keeps once for the login after keel-init" {
    install -m 755 /dev/null "$HOME/.profile.d/turnkey-init-fence"

    run login

    [ "$status" -eq 0 ]
    [[ "$output" == *login-went-on* ]]
    [ ! -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = once ]
}

@test "a profile fence that is not armed does not stop confconsole" {
    install -m 644 /dev/null "$HOME/.profile.d/turnkey-init-fence"

    run login

    [ "$status" -eq 0 ]
    [ -e "$STUBS/confconsole.calls" ]
}

@test "a first boot still pending keeps once" {
    # keel-init --status exits 75 while the boot run is pending or running
    stub keel-init 'echo "    The first boot is still running"; exit 75'

    run login

    [ "$status" -eq 0 ]
    [[ "$output" != *"first boot is still running"* ]]
    [ ! -e "$STUBS/confconsole.calls" ]
    [ "$(setting)" = once ]
}

@test "a keel-init status that fails otherwise does not stop confconsole" {
    stub keel-init 'exit 1'

    run login

    [ "$status" -eq 0 ]
    [ -e "$STUBS/confconsole.calls" ]
}
