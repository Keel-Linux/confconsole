#!/usr/bin/env bats
# Tests for the shell files of the Let's Encrypt plugin under
# share/letsencrypt: challenge.sh (who answers the http-01 challenge, and
# the init fence), the http-01 hook and the renewal cron job.
#
# On image web 19.0-14 (keel 0.23.96, confconsole 2.2.3+keel24) each
# issue and renewal stopped nginx for about 30 s, for the add-water server
# (confconsole#44); and a request while the init fence was up got the
# fence's 404 and used the CA's failed-validation limit (keel#320).
#
# systemctl, nginx and the wrapper are stubs on PATH; the files are scratch
# paths.

bats_require_minimum_version 1.5.0

REPO=$(cd "$BATS_TEST_DIRNAME/.." && pwd)
SHARE=$REPO/share/letsencrypt
HOOK=$SHARE/dehydrated-confconsole.hook-http-01.sh
CRON=$SHARE/dehydrated-confconsole.cron
WELLKNOWN=/var/lib/dehydrated/acme-challenges

setup() {
    STUBS=$BATS_TEST_TMPDIR/stubs
    mkdir -p "$STUBS"
    PATH=$STUBS:$PATH
    # every unit is active, and nginx serves keel-web's challenge location
    stub systemctl 'exit 0'
    stub nginx "[ \"\$1\" = -T ] && printf '%s\n' 'server {' '	location ^~ /.well-known/acme-challenge/ {' '		alias $WELLKNOWN/;' '	}' '}'; exit 0"
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

# --- challenge.sh: the init fence ----------------------------------------

@test "the fence is up while its unit is active" {
    source "$SHARE/challenge.sh"

    fence_up

    [ "$(calls systemctl)" = "--quiet is-active turnkey-init-fence.service" ]
}

@test "the fence is down when its unit is not active" {
    stub systemctl 'exit 3'
    source "$SHARE/challenge.sh"

    run ! fence_up
}

@test "the fence has its own exit code and message" {
    source "$SHARE/challenge.sh"

    [ "$FENCE_EXIT" -eq 75 ]
    [ "$FENCE_MESSAGE" = "first-login setup not finished; the certificate is requested after it" ]
}

# --- challenge.sh: who answers the challenge -----------------------------

@test "nginx answers when it owns port 80 and serves the WELLKNOWN directory" {
    source "$SHARE/challenge.sh"

    run challenge_server nginx "$WELLKNOWN"

    [ "$status" -eq 0 ]
    [ "$output" = nginx ]
}

@test "the directory matches with or without its last slash" {
    stub nginx "printf '%s\n' '		alias $WELLKNOWN;'"
    source "$SHARE/challenge.sh"

    run challenge_server nginx "$WELLKNOWN/"

    [ "$output" = nginx ]
}

@test "add-water answers when another server owns port 80" {
    source "$SHARE/challenge.sh"

    run challenge_server apache2 "$WELLKNOWN"

    [ "$output" = add-water ]
    [ ! -e "$STUBS/nginx.calls" ]
}

@test "add-water answers when nothing owns port 80" {
    source "$SHARE/challenge.sh"

    run challenge_server "" "$WELLKNOWN"

    [ "$output" = add-water ]
}

@test "add-water answers when nginx is not active" {
    stub systemctl 'exit 3'
    source "$SHARE/challenge.sh"

    run challenge_server nginx "$WELLKNOWN"

    [ "$output" = add-water ]
    [ "$(calls systemctl)" = "--quiet is-active nginx.service" ]
}

@test "add-water answers when no location of nginx serves the directory" {
    stub nginx "printf '%s\n' '		alias /srv/other/acme-challenges/;'"
    source "$SHARE/challenge.sh"

    run challenge_server nginx "$WELLKNOWN"

    [ "$output" = add-water ]
}

@test "a commented alias does not count" {
    stub nginx "printf '%s\n' '#		alias $WELLKNOWN/;'"
    source "$SHARE/challenge.sh"

    run challenge_server nginx "$WELLKNOWN"

    [ "$output" = add-water ]
}

@test "add-water answers when nginx -T fails" {
    stub nginx "echo '		alias $WELLKNOWN/;'; exit 1"
    source "$SHARE/challenge.sh"

    run challenge_server nginx "$WELLKNOWN"

    [ "$output" = add-water ]
}

# --- challenge.sh: the reload --------------------------------------------

@test "nginx is tested, then reloaded, never restarted" {
    source "$SHARE/challenge.sh"

    run reload_nginx

    [ "$status" -eq 0 ]
    [ "$(calls nginx)" = "-t" ]
    [ "$(calls systemctl)" = "reload nginx.service" ]
}

@test "a refused test reloads nothing and says so" {
    stub nginx 'echo "nginx: [emerg] unknown directive" >&2; exit 1'
    source "$SHARE/challenge.sh"

    run reload_nginx

    [ "$status" -eq 1 ]
    [[ "$output" == *"unknown directive"* ]]
    [[ "$output" == *"nginx -t refused the configuration"* ]]
    [ ! -e "$STUBS/systemctl.calls" ]
}

@test "a failed reload says so" {
    stub systemctl 'exit 1'
    source "$SHARE/challenge.sh"

    run reload_nginx

    [ "$status" -eq 1 ]
    [[ "$output" == *"systemctl reload nginx.service failed"* ]]
}

# --- the http-01 hook ----------------------------------------------------

# hook_env: the variables the wrapper exports for the hook
hook_env() {
    export HTTP=add-water-client HTTP_BIN=$STUBS/add-water-client
    export HTTP_PID=$BATS_TEST_TMPDIR/pid HTTP_LOG=/dev/null
    export TKL_KEYFILE=$BATS_TEST_TMPDIR/cert.key
    export TKL_CERTFILE=$BATS_TEST_TMPDIR/cert.crt
    export TKL_COMBINED=$BATS_TEST_TMPDIR/cert.pem
    export TKL_DHPARAM=$BATS_TEST_TMPDIR/dhparams.pem
    export WELLKNOWN
    stub add-water-client
}

@test "with nginx, the hook leaves the token to dehydrated and nginx" {
    hook_env
    export CHALLENGE_SERVER=nginx

    run bash "$HOOK" deploy_challenge blog.example.org token value

    [ "$status" -eq 0 ]
    [[ "$output" == *"nginx serves $WELLKNOWN/token"* ]]
    run bash "$HOOK" clean_challenge blog.example.org token value
    [ "$status" -eq 0 ]
    [ ! -e "$STUBS/add-water-client.calls" ]
}

@test "with add-water, the hook hands the token to add-water" {
    hook_env
    export CHALLENGE_SERVER=add-water

    run bash "$HOOK" deploy_challenge blog.example.org token value
    [ "$status" -eq 0 ]
    run bash "$HOOK" clean_challenge blog.example.org token value

    [ "$status" -eq 0 ]
    [ "$(calls add-water-client)" = "--deploy $WELLKNOWN/token
--clean $WELLKNOWN/token" ]
}

@test "the hook writes the certificate where every service reads it" {
    hook_env
    echo key > "$BATS_TEST_TMPDIR/privkey.pem"
    echo chain > "$BATS_TEST_TMPDIR/fullchain.pem"
    echo dh > "$TKL_DHPARAM"

    run bash "$HOOK" deploy_cert blog.example.org "$BATS_TEST_TMPDIR/privkey.pem" \
        cert.pem "$BATS_TEST_TMPDIR/fullchain.pem" chain.pem 1

    [ "$status" -eq 0 ]
    [ "$(cat "$TKL_KEYFILE")" = key ]
    [ "$(cat "$TKL_CERTFILE")" = chain ]
    [ "$(cat "$TKL_COMBINED")" = "chain
key
dh" ]
}

@test "an unchanged certificate is only logged" {
    hook_env

    run bash "$HOOK" unchanged_cert blog.example.org

    [ "$status" -eq 0 ]
    [[ "$output" == *"cert for blog.example.org is unchanged"* ]]
}

@test "the hook refuses to run without the wrapper's variables" {
    hook_env
    unset TKL_DHPARAM

    run bash "$HOOK" deploy_challenge blog.example.org token value

    [ "$status" -eq 1 ]
    [[ "$output" == *"TKL_DHPARAM is not set"* ]]
}

# --- the renewal cron job ------------------------------------------------

# cron_env DAYS: a certificate that ends in DAYS days, and the wrapper
# stub
cron_env() {
    export CONFCONSOLE_LE_CERT=$BATS_TEST_TMPDIR/cert.pem
    export CONFCONSOLE_LE_LOG=$BATS_TEST_TMPDIR/letsencrypt.log
    export CONFCONSOLE_LE_WRAPPER=$STUBS/dehydrated-wrapper
    openssl req -x509 -newkey rsa:2048 -nodes -subj /CN=blog.example.org \
        -days "$1" -keyout "$BATS_TEST_TMPDIR/cert.key" \
        -out "$CONFCONSOLE_LE_CERT" 2>/dev/null
    stub dehydrated-wrapper 'echo renewed'
}

@test "the cron job does nothing while the certificate is far from its end" {
    cron_env 90

    run bash "$CRON"

    [ "$status" -eq 0 ]
    [ ! -e "$STUBS/dehydrated-wrapper.calls" ]
    grep -q "Nothing to do." "$CONFCONSOLE_LE_LOG"
}

@test "the cron job renews a certificate near its end" {
    cron_env 10

    run bash "$CRON"

    [ "$status" -eq 0 ]
    [ "$(calls dehydrated-wrapper)" = --force ]
    grep -q "certificate renewed" "$CONFCONSOLE_LE_LOG"
}

@test "the cron job defers a renewal while the init fence is up" {
    cron_env 10
    stub dehydrated-wrapper 'echo "first-login setup not finished" >&2; exit 75'

    run bash "$CRON"

    [ "$status" -eq 0 ]
    grep -q "deferred: first-login setup not finished" "$CONFCONSOLE_LE_LOG"
    run ! grep -q "ERR:" "$CONFCONSOLE_LE_LOG"
}

@test "the cron job fails when the wrapper fails" {
    cron_env 10
    stub dehydrated-wrapper 'exit 1'

    run bash "$CRON"

    [ "$status" -eq 1 ]
    grep -q "ERR: dehydrated-wrapper exited with a non-zero exit code." "$CONFCONSOLE_LE_LOG"
}
