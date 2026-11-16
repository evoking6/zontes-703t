#!/bin/sh
# 703T_SSH_MANAGED_V1: root maintenance service, started asynchronously by rcS.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
BASE=/opt/703t-ssh
RELEASE=__RELEASE__
HERE="$BASE/releases/$RELEASE"
BIN="$HERE/dropbearmulti"
RUN=/tmp/703t-ssh
LOCK="$RUN/supervisor"
HOST="$BASE/hostkeys/ed25519"

owned_pid() {
    case "$1" in ''|*[!0-9]*) return 1;; esac
    [ -r "/proc/$1/cmdline" ] && tr '\000' ' ' < "/proc/$1/cmdline" | grep -Fq "$HERE/service.sh"
}

case "${1:-start}" in
start)
    umask 077
    [ ! -L "$RUN" ] && [ ! -L "$LOCK" ] || exit 1
    if [ -e "$RUN" ]; then
        listing=$(ls -ldn "$RUN"); set -- $listing
        [ "${3:-}" = 0 ] || exit 1
        case "${1:-}" in ?????w*|????????w*) exit 1;; esac
    fi
    mkdir -p "$RUN"
    if ! mkdir "$LOCK" 2>/dev/null; then
        [ -f "$LOCK/pid" ] || exit 0
        previous=$(cat "$LOCK/pid")
        if owned_pid "$previous" && kill -0 "$previous" 2>/dev/null; then exit 0; fi
        rm -f "$LOCK/pid"
        rmdir "$LOCK" || exit 1
        mkdir "$LOCK" || exit 1
    fi
    "$HERE/service.sh" run >> "$RUN/service.log" 2>&1 &
    ;;
run)
    umask 077
    child=
    cleanup() {
        trap - TERM INT EXIT
        if [ -n "$child" ]; then kill "$child" 2>/dev/null || :; wait "$child" 2>/dev/null || :; fi
        rm -f "$RUN/dropbear.pid" "$LOCK/pid"
        rmdir "$LOCK" 2>/dev/null || :
    }
    trap cleanup EXIT
    trap 'exit 0' TERM INT
    echo $$ > "$LOCK/pid"
    mkdir -p "$BASE/hostkeys"
    chmod 700 "$BASE/hostkeys"
    if [ ! -s "$HOST" ]; then
        rm -f "$HOST.new"
        "$BIN" dropbearkey -t ed25519 -f "$HOST.new"
        chmod 600 "$HOST.new"
        mv "$HOST.new" "$HOST"
        sync
    fi
    chmod 600 "$HOST"
    "$BIN" dropbearkey -y -f "$HOST" > "$BASE/hostkeys/public.txt"
    while :; do
        # A missing AP address/interface fails closed; retry without delaying Launcher.
        "$BIN" dropbear -F -p 192.168.3.1:22 -l wlan0 \
            -G root -D "$HERE/keys" -r "$HOST" -P "$RUN/dropbear.pid" \
            -K 30 -I 600 -T 3 &
        child=$!
        wait "$child" || :
        child=
        # Limit retained errors across retries when the AP is unavailable.
        if [ "$(wc -c < "$RUN/service.log")" -gt 32768 ]; then : > "$RUN/service.log"; fi
        sleep 5 &
        child=$!
        wait "$child" || :
        child=
    done
    ;;
stop)
    [ -f "$LOCK/pid" ] || exit 0
    previous=$(cat "$LOCK/pid")
    if owned_pid "$previous"; then kill "$previous"; fi
    ;;
status)
    if [ -f "$LOCK/pid" ] && owned_pid "$(cat "$LOCK/pid")"; then
        echo '703T SSH supervisor running; see /tmp/703t-ssh/service.log and dropbear.pid'
    else
        echo '703T SSH stopped'; exit 1
    fi
    ;;
*) echo 'Usage: service.sh start|stop|status' >&2; exit 2;;
esac
