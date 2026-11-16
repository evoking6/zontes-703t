#!/bin/sh
# 703T_SSH_MANAGED_V1. Run only from the extracted, trusted candidate package.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BASE=/opt/703t-ssh
RELEASE=__RELEASE__
COUNTER=__COUNTER__
TARGET="$BASE/releases/$RELEASE"
HOOK=/etc/init.d/S97ssh703t
stage=
lock=/tmp/703t-ssh-install.lock
locked=0
TX=
armed=0
cleanup() {
    if [ "$armed" = 1 ] && [ -f "$TX/result.json" ] && grep -q '"phase":"PENDING"' "$TX/result.json"; then
        "$TARGET/rollback.sh" "$TX" >> "$TX/rollback.log" 2>&1 || {
            printf '%s\n' '{"phase":"FAILED","release":"__RELEASE__","validation_passed":false,"rollback_verified":false}' > "$TX/result.json"
            sync
        }
    fi
    if [ -n "$stage" ]; then rm -rf "$stage"; fi
    if [ "$locked" = 1 ]; then rm -f "$lock/pid"; rmdir "$lock" 2>/dev/null || :; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fail() { echo "703T SSH: $*" >&2; exit 1; }

# Read-only checks must finish before any persistent system modification.
[ "$(id -u)" = 0 ] || fail 'root is required'
[ "$(uname -m)" = aarch64 ] || fail 'AArch64 Linux required'
panel=$(cat /proc/lcdv) || fail 'cannot read panel identity'
case "$panel" in GT_G080-11|HW_TFT080X|HW_CLAA080) :;; *) fail 'unknown panel';; esac
printf '%s  %s\n' '__LAUNCHER_SHA__' /usr/bin/Launcher | sha256sum -c - >/dev/null || fail 'factory Launcher baseline mismatch'
rc=$(sha256sum /etc/init.d/rcS); rc=${rc%% *}
case "$rc" in __RCS_HASHES__) :;; *) fail 'unrecognised rcS; autostart must be reviewed';; esac
setsid_path=$(command -v setsid) || fail 'setsid unavailable in system PATH'
[ -x "$setsid_path" ] && [ -x /bin/sh ] && [ -c /dev/urandom ] && [ -c /dev/ptmx ] && [ -d /dev/pts ] || fail 'shell, random source or PTY unavailable'
grep -q '^root:[^:]*:0:0:' /etc/passwd && grep -q '^root:[^:]*:0:' /etc/group || fail 'root account/group layout unsupported'
# Factory directories may be group-writable by root. That is trusted only when
# group 0 cannot grant write access to a non-root account.
root_group_trusted=0
if awk -F: '$4 == 0 && $3 != 0 { bad=1 } END { exit bad }' /etc/passwd &&
   awk -F: '$3 == 0 && $4 != "" && $4 != "root" { bad=1 } END { exit bad }' /etc/group; then
    root_group_trusted=1
fi
printf '%s  %s\n' '__CHECKSUMS_SHA__' "$SOURCE/payload/SHA256SUMS" | sha256sum -c - >/dev/null || fail 'payload manifest mismatch'
(cd "$SOURCE/payload" && sha256sum -c SHA256SUMS >/dev/null) || fail 'payload mismatch'
for path in /opt "$BASE" "$BASE/releases" "$TARGET" "$BASE/hostkeys" "$BASE/transactions" "$BASE/component-state" "$BASE/pending" "$HOOK" "$lock" /tmp/703t-ssh /tmp/703t-ssh/supervisor; do
    [ ! -L "$path" ] || fail "refusing symlink $path"
done
[ ! -e "$HOOK" ] || grep -q '703T_SSH_MANAGED_V1' "$HOOK" || fail 'startup hook already belongs to another service'
for path in / /opt "$BASE" "$BASE/releases" "$TARGET" "$BASE/hostkeys" "$BASE/transactions" "$BASE/component-state" "$BASE/pending" "$HOOK" "$lock" /tmp/703t-ssh /tmp/703t-ssh/supervisor; do
    if [ -e "$path" ]; then
        # The original BusyBox has no stat applet; ls -ldn is available.
        listing=$(ls -ldn "$path")
        set -- $listing
        [ "${3:-}" = 0 ] || fail "untrusted owner $path"
        case "${1:-}" in ????????w*) fail "group/other writable ancestor $path";; esac
        case "${1:-}" in ?????w*)
            [ "${4:-}" = 0 ] && [ "$root_group_trusted" = 1 ] || fail "untrusted writable group on $path";;
        esac
    fi
done
if ! mkdir "$lock" 2>/dev/null; then
    [ -f "$lock/pid" ] || fail 'another installation is being prepared'
    oldpid=$(cat "$lock/pid")
    case "$oldpid" in ''|*[!0-9]*) fail 'invalid installation lock';; esac
    if [ -r "/proc/$oldpid/cmdline" ] && tr '\000' ' ' < "/proc/$oldpid/cmdline" | grep -q 'ssh703t/install.sh'; then fail 'another installation is running'; fi
    rm "$lock/pid"; rmdir "$lock"; mkdir "$lock"
fi
locked=1
echo $$ > "$lock/pid"
[ ! -f "$BASE/pending" ] || fail 'previous validation is pending; resume it before another installation'

if [ -f "$BASE/component-state" ]; then
    previous_counter=$(sed -n '2p' "$BASE/component-state")
    previous_release=$(sed -n '1p' "$BASE/component-state")
    case "$previous_counter" in ''|*[!0-9]*) fail 'invalid committed component counter';; esac
    [ "$COUNTER" -gt "$previous_counter" ] || [ "$previous_release" = "$RELEASE" ] || fail 'component downgrade rejected'
fi
if [ ! -d /opt ]; then mkdir /opt; chmod 755 /opt; fi
mkdir -p "$BASE/releases" "$BASE/hostkeys"
chmod 755 "$BASE" "$BASE/releases"
chmod 700 "$BASE/hostkeys"
if [ -e "$TARGET" ]; then
    [ -d "$TARGET" ] || fail 'release path is not a directory'
    cmp "$SOURCE/payload/SHA256SUMS" "$TARGET/SHA256SUMS" >/dev/null || fail 'release name already has different contents'
    (cd "$TARGET" && sha256sum -c SHA256SUMS >/dev/null) || fail 'installed release is damaged'
else
    stage="$BASE/releases/.$RELEASE.$$"
    mkdir "$stage"
    cp -R "$SOURCE/payload/." "$stage/"
    chmod 755 "$stage" "$stage/dropbearmulti" "$stage/service.sh" "$stage/S97ssh703t" "$stage/disable.sh" "$stage/post-install-test.sh" "$stage/health-controller.sh" "$stage/rollback.sh"
    chmod 700 "$stage/keys"
    chmod 600 "$stage/keys/authorized_keys"
    chmod 644 "$stage/SHA256SUMS" "$stage/LICENSE.dropbear"
    (cd "$stage" && sha256sum -c SHA256SUMS >/dev/null) || fail 'staged copy failed verification'
    sync
    mv "$stage" "$TARGET"
    stage=
fi
if [ -f "$BASE/component-state" ] && [ -f "$HOOK" ] && cmp "$HOOK" "$TARGET/S97ssh703t" >/dev/null; then
    current=$(sed -n '1p' "$BASE/component-state")
    if [ "$current" = "$RELEASE" ]; then
        "$TARGET/post-install-test.sh" || fail 'committed SSH component no longer passes validation'
        echo 'COMMITTED: identical release already installed and revalidated.'
        exit 0
    fi
fi
mkdir -p "$BASE/transactions"
chmod 700 "$BASE/transactions"
tx="txn-$RELEASE-$$"
TX="$BASE/transactions/$tx"
mkdir "$TX"
echo "$RELEASE" > "$TX/release"
if [ -e "$HOOK" ]; then cp "$HOOK" "$TX/previous-hook"; echo 1 > "$TX/had-hook"; else echo 0 > "$TX/had-hook"; fi
if [ -f "$BASE/component-state" ]; then cp "$BASE/component-state" "$TX/previous-state"; fi
printf '%s\n' '{"phase":"PENDING","release":"__RELEASE__","validation_passed":false}' > "$TX/result.json"
echo "$tx" > "$BASE/pending.new"
sync
mv "$BASE/pending.new" "$BASE/pending"
armed=1
sync
if [ -e "$HOOK" ]; then
    "$HOOK" stop
    attempt=0
    while [ -f /tmp/703t-ssh/supervisor/pid ] && [ "$attempt" -lt 20 ]; do sleep 1; attempt=$((attempt + 1)); done
    [ ! -f /tmp/703t-ssh/supervisor/pid ] || fail 'could not stop previous SSH component'
fi
# Publish the hook only after the complete runtime is present.
cp "$TARGET/S97ssh703t" "$HOOK.new"
chmod 755 "$HOOK.new"
sync
mv "$HOOK.new" "$HOOK"
sync
"$TARGET/health-controller.sh" "$TX" || fail "post-install validation failed; see $TX/result.json"
cat "$TX/result.json"
