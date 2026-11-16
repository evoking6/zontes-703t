#!/bin/sh
# Restore only the files/activation owned by this SSH component transaction.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
BASE=/opt/703t-ssh
HERE="$BASE/releases/__RELEASE__"
TX=${1:-}
case "$TX" in "$BASE/transactions/txn-__RELEASE__-"[0-9]*) :;; *) echo 'Invalid rollback transaction' >&2; exit 1;; esac
suffix=${TX##*/txn-__RELEASE__-}
case "$suffix" in ''|*[!0-9]*) exit 1;; esac
[ ! -L "$TX" ] && [ "$(cat "$TX/release")" = '__RELEASE__' ] || exit 1
HOOK=/etc/init.d/S97ssh703t
# A retry after a verified rollback is harmless.
if [ -f "$TX/result.json" ] && grep -q '"phase":"ROLLED_BACK"' "$TX/result.json"; then exit 0; fi
"$HERE/service.sh" stop || :
# If activation failed before replacing the hook, also stop the saved owner.
if [ -f "$TX/previous-hook" ]; then /bin/sh "$TX/previous-hook" stop || :; fi
attempt=0
while [ -f /tmp/703t-ssh/supervisor/pid ] && [ "$attempt" -lt 20 ]; do sleep 1; attempt=$((attempt + 1)); done
if [ -f /tmp/703t-ssh/supervisor/pid ]; then echo 'Could not stop candidate SSH supervisor' >&2; exit 1; fi
if [ "$(cat "$TX/had-hook")" = 1 ]; then
    cp "$TX/previous-hook" "$HOOK.new"
    chmod 755 "$HOOK.new"
    sync
    mv "$HOOK.new" "$HOOK"
    cmp "$TX/previous-hook" "$HOOK"
else
    if [ -e "$HOOK" ]; then cmp "$HERE/S97ssh703t" "$HOOK"; rm "$HOOK"; fi
    [ ! -e "$HOOK" ]
fi
if [ -f "$TX/previous-state" ]; then
    cp "$TX/previous-state" "$BASE/component-state.new"
    mv "$BASE/component-state.new" "$BASE/component-state"
else
    rm -f "$BASE/component-state"
fi
if [ "$(cat "$TX/had-hook")" = 1 ]; then "$HOOK" start; fi
printf '%s  %s\n' '__LAUNCHER_SHA__' /usr/bin/Launcher | sha256sum -c - >/dev/null
if [ -f "$BASE/pending" ] && [ "$(cat "$BASE/pending")" = "${TX##*/}" ]; then rm "$BASE/pending"; fi
printf '%s\n' '{"phase":"ROLLED_BACK","release":"__RELEASE__","validation_passed":false,"rollback_verified":true}' > "$TX/result.new"
sync
mv "$TX/result.new" "$TX/result.json"
sync
echo 'ROLLED_BACK: previous SSH startup state restored; original application untouched.'
