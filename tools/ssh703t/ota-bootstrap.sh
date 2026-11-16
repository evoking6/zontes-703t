#!/bin/sh
# 703T_SSH_OTA_BOOTSTRAP_V1
# The factory updater waits in system() here. Never return into its MCU tail.
# This entrypoint is for the authenticated, baseline-bound SSH-only OTA bundle.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
hold() {
    while :; do /bin/busybox sleep 60; done
}
trap 'hold' EXIT HUP INT TERM

# Remove only this bundle's three entrypoints before installing. In particular,
# updateFile.sh must not be replayed by the original Launcher after reboot.
for entry in /etc/updateFile/updateFile.sh /etc/updateFile/updateFile_GT.sh /etc/updateFile/updateFile_HW.sh; do
    if [ -e "$entry" ] || [ -L "$entry" ]; then
        if [ -L "$entry" ] || ! /bin/busybox grep -q '^# 703T_SSH_OTA_BOOTSTRAP_V1$' "$entry"; then
            echo 'SSH bootstrap: unexpected replay entrypoint; holding without reboot.' >&2
            hold
        fi
        /bin/busybox rm -f "$entry"
        if [ -e "$entry" ] || [ -L "$entry" ]; then
            echo 'SSH bootstrap: could not remove replay entrypoint; holding without reboot.' >&2
            hold
        fi
    fi
done
/bin/busybox sync

if printf '%s\n' '__INSTALL_SHA__  /etc/updateFile/ssh703t/install.sh' | /bin/busybox sha256sum -c -; then
    /bin/sh /etc/updateFile/ssh703t/install.sh
    result=$?
    echo "SSH bootstrap: installer exit=$result; transaction result is in /opt/703t-ssh/transactions."
else
    echo 'SSH bootstrap: installer checksum failed; no component installation performed.' >&2
fi

# The installer has synchronously committed or rolled back before this point.
# Force the Linux reboot syscall after sync: an init-mediated reboot could kill
# this child before the parent and allow the factory MCU branch to resume.
# A failed reboot syscall must keep the factory parent blocked as well.
/bin/busybox sync
/bin/busybox reboot -f
echo 'SSH bootstrap: reboot returned unexpectedly; holding to prevent MCU update.' >&2
hold
