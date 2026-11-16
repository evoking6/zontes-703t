#!/bin/sh
# Sole owner of post-install validation, commit and recovery after interruption.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
BASE=/opt/703t-ssh
HERE="$BASE/releases/__RELEASE__"
TX=${1:-}
case "$TX" in "$BASE/transactions/txn-__RELEASE__-"[0-9]*) :;; *) exit 1;; esac
suffix=${TX##*/txn-__RELEASE__-}
case "$suffix" in ''|*[!0-9]*) exit 1;; esac
[ ! -L "$TX" ] && [ "$(cat "$TX/release")" = '__RELEASE__' ] || exit 1
if [ -f "$TX/result.json" ] && grep -q '"phase":"COMMITTED"\|"phase":"ROLLED_BACK"' "$TX/result.json"; then
    if [ -f "$BASE/pending" ] && [ "$(cat "$BASE/pending")" = "${TX##*/}" ]; then rm "$BASE/pending"; sync; fi
    exit 0
fi
LOCK="$TX/health.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    [ -f "$LOCK/pid" ] || exit 1
    previous=$(cat "$LOCK/pid")
    case "$previous" in ''|*[!0-9]*) exit 1;; esac
    if [ -r "/proc/$previous/cmdline" ] && tr '\000' ' ' < "/proc/$previous/cmdline" | grep -Fq "$HERE/health-controller.sh"; then exit 0; fi
    rm "$LOCK/pid"; rmdir "$LOCK"; mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
test_pid=
watchdog=
finished=0
cleanup() {
    trap - EXIT INT TERM
    if [ -n "$watchdog" ]; then kill "$watchdog" 2>/dev/null || :; wait "$watchdog" 2>/dev/null || :; fi
    if [ -n "$test_pid" ]; then kill -KILL -"$test_pid" 2>/dev/null || kill -KILL "$test_pid" 2>/dev/null || :; wait "$test_pid" 2>/dev/null || :; fi
    if [ "$finished" = 0 ]; then
        if ! "$HERE/rollback.sh" "$TX" >> "$TX/rollback.log" 2>&1; then
            printf '%s\n' '{"phase":"FAILED","release":"__RELEASE__","validation_passed":false,"rollback_verified":false}' > "$TX/result.json"
            sync
        fi
    fi
    rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || :
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$HERE/service.sh" start
setsid "$HERE/post-install-test.sh" > "$TX/post-install-test.log" 2>&1 &
test_pid=$!
(
    timer=
    trap '[ -z "$timer" ] || kill "$timer" 2>/dev/null; exit 0' TERM INT
    sleep 60 & timer=$!; wait "$timer" || exit 0; timer=
    kill -TERM -"$test_pid" 2>/dev/null || exit 0
    sleep 2 & timer=$!; wait "$timer" || exit 0; timer=
    kill -KILL -"$test_pid" 2>/dev/null || :
) > /dev/null 2>&1 &
watchdog=$!
result=0
wait "$test_pid" || result=$?
kill -KILL -"$test_pid" 2>/dev/null || :
test_pid=
kill "$watchdog" 2>/dev/null || :; wait "$watchdog" 2>/dev/null || :; watchdog=
if [ "$result" != 0 ]; then echo 'Post-install validation failed; rolling back.' >&2; exit 1; fi
printf '%s\n' '__RELEASE__' '__COUNTER__' > "$BASE/component-state.new"
sync
mv "$BASE/component-state.new" "$BASE/component-state"
printf '%s\n' '{"phase":"COMMITTED","release":"__RELEASE__","validation_profile":"ssh-post-install-v1","validation_passed":true,"health_committed":true,"ssh_ready":true,"rollback_available":true}' > "$TX/result.new"
sync
mv "$TX/result.new" "$TX/result.json"
sync
finished=1
if [ -f "$BASE/pending" ] && [ "$(cat "$BASE/pending")" = "${TX##*/}" ]; then rm "$BASE/pending"; sync; fi
finished=1
echo 'COMMITTED: post-install test passed.'
