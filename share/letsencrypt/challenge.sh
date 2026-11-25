# shellcheck shell=bash
# Who answers ACME's http-01 challenge on port 80, for dehydrated-wrapper.
#
# Installed as /usr/share/confconsole/letsencrypt/challenge.sh. Sourced by
# plugins.d/Lets_Encrypt/dehydrated-wrapper and by tests/test-letsencrypt.bats.
#
# Two ways (confconsole#44):
#
# - nginx: nginx runs, owns port 80, and its configuration has a location
#   whose alias is dehydrated's WELLKNOWN directory. keel-web (0.4.3 and
#   later) puts one in the public server of port 80 of its default site,
#   before the redirect to HTTPS, on IPv4 and IPv6 (handbook decision
#   0079). dehydrated writes the token there and nginx serves it. Nothing
#   stops: after the certificate is written, nginx is tested and reloaded.
# - add-water: anything else. The web server on port 80, if there is one,
#   stops while the add-water server answers the challenge, as in TurnKey.
#
# The init fence (inithooks' turnkey-init-fence.service) redirects ports 80
# and 443 to its own page for traffic from outside until the first-login
# setup (keel-init) is finished. A certificate authority then gets the
# fence's 404 for each challenge, and each failed validation counts against
# its limit. So no http-01 request goes out while the fence is up
# (keel#320).
#
# The functions use systemctl and nginx from PATH.

# The exit code of dehydrated-wrapper when the init fence is up: 75
# (EX_TEMPFAIL), the code keel-init uses for "initialization not finished".
# shellcheck disable=SC2034  # read by dehydrated-wrapper
FENCE_EXIT=75
# shellcheck disable=SC2034  # read by dehydrated-wrapper
FENCE_MESSAGE="first-login setup not finished; the certificate is requested after it"
FENCE_UNIT=turnkey-init-fence.service
NGINX_UNIT=nginx.service

# fence_up: 0 while the init fence is active
fence_up() {
    systemctl --quiet is-active "$FENCE_UNIT"
}

# nginx_serves_challenges WELLKNOWN: 0 when nginx is active and a location
# of its configuration has WELLKNOWN as its alias (with or without the last
# slash). `nginx -T` prints the whole configuration as nginx reads it,
# every include resolved.
nginx_serves_challenges() {
    local dir="${1%/}" config
    systemctl --quiet is-active "$NGINX_UNIT" || return 1
    config="$(nginx -T 2>/dev/null)" || return 1
    grep -qE "^[[:space:]]*alias[[:space:]]+${dir//./\\.}/?;" <<< "$config"
}

# challenge_server PORT_OWNER WELLKNOWN: prints "nginx" when nginx owns
# port 80 and serves WELLKNOWN, else "add-water"
challenge_server() {
    if [[ "$1" == nginx ]] && nginx_serves_challenges "$2"; then
        echo nginx
    else
        echo add-water
    fi
}

# reload_nginx: tests the configuration, then reloads nginx; never a
# restart, never a stop. 1, with the reason on stderr, when the test or the
# reload fails: nginx then keeps the configuration and the certificate it
# has.
reload_nginx() {
    if ! nginx -t 2>&1; then
        echo "nginx -t refused the configuration: nginx is not reloaded and serves the previous certificate" >&2
        return 1
    fi
    if ! systemctl reload "$NGINX_UNIT"; then
        echo "systemctl reload $NGINX_UNIT failed: nginx serves the previous certificate" >&2
        return 1
    fi
}
