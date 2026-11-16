#!/bin/sh
# Read-only post-install checks. No success marker is written by this script.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
HERE=/opt/703t-ssh/releases/__RELEASE__
BASE=/opt/703t-ssh
RUN=/tmp/703t-ssh
fail() { echo "FAIL $*"; exit 1; }
(cd "$HERE" && sha256sum -c SHA256SUMS) || fail 'installed payload checksum'
printf '%s  %s\n' '__LAUNCHER_SHA__' /usr/bin/Launcher | sha256sum -c - || fail 'original Launcher changed'
rc=$(sha256sum /etc/init.d/rcS); rc=${rc%% *}
case "$rc" in __RCS_HASHES__) :;; *) fail 'original rcS changed';; esac
cmp "$HERE/S97ssh703t" /etc/init.d/S97ssh703t || fail 'startup hook differs'
# The controller enforces a separate wall-clock deadline, including hung scripts.
attempt=0
while [ "$attempt" -lt 30 ]; do
    if [ -r "$RUN/dropbear.pid" ]; then
        pid=$(cat "$RUN/dropbear.pid")
        case "$pid" in ''|*[!0-9]*) fail 'invalid daemon pid';; esac
        if [ -r "/proc/$pid/cmdline" ] && tr '\000' ' ' < "/proc/$pid/cmdline" | grep -Fq "$HERE/dropbearmulti"; then
            if grep -Eq '[[:space:]]0103A8C0:0016[[:space:]]+[[:xdigit:]]+:[[:xdigit:]]+[[:space:]]+0A[[:space:]]' /proc/net/tcp; then
                for path in "$HERE/keys" "$HERE/keys/authorized_keys" "$BASE/hostkeys" "$BASE/hostkeys/ed25519"; do
                    listing=$(ls -ldn "$path"); set -- $listing
                    [ "${3:-}" = 0 ] || fail "owner $path"
                    case "${1:-}" in ?????w*|????????w*) fail "permissions $path";; esac
                done
                "$HERE/dropbearmulti" dropbearkey -y -f "$BASE/hostkeys/ed25519" | grep -q '^ssh-ed25519 ' || fail 'host key invalid'
                echo 'PASS payload, original files, startup hook, key permissions, host key, SSH process and AP listener'
                exit 0
            fi
        fi
    fi
    attempt=$((attempt + 1))
    sleep 1
done
fail 'SSH listener did not become ready'
