#!/bin/sh
# 703T_SSH_MANAGED_V1: disable autostart, keep host identity and installed files.
set -eu
SERVICE=/opt/703t-ssh/releases/__RELEASE__/service.sh
HOOK=/etc/init.d/S97ssh703t
if [ -x "$SERVICE" ]; then "$SERVICE" stop; fi
if [ -f "$HOOK" ]; then
    grep -q '703T_SSH_MANAGED_V1' "$HOOK" || exit 1
    rm "$HOOK"
    sync
fi
echo '703T SSH autostart disabled. Existing authenticated sessions may remain until they exit.'
