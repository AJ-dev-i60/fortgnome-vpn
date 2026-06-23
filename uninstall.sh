#!/bin/bash
# FortGNOME VPN — uninstaller.  Run:  sudo ./uninstall.sh
set -e
if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo: sudo ./uninstall.sh" >&2; exit 1; fi

echo "==> Bringing tunnel down and removing strongSwan drop-ins…"
ipsec down fortgnome >/dev/null 2>&1 || true
rm -f /etc/ipsec.d/fortgnome.conf /etc/ipsec.d/fortgnome.secrets
sed -i '\#include /etc/ipsec.d/fortgnome.conf#d'    /etc/ipsec.conf    2>/dev/null || true
sed -i '\#include /etc/ipsec.d/fortgnome.secrets#d' /etc/ipsec.secrets 2>/dev/null || true
ipsec reload >/dev/null 2>&1 || true

echo "==> Removing app files…"
pkill -f /usr/lib/fortgnome/fortgnome-gui.py 2>/dev/null || true
rm -rf /usr/lib/fortgnome
rm -f /usr/bin/fortgnome /usr/bin/fortgnome-apply
rm -f /usr/share/applications/fortgnome-vpn.desktop
rm -f /etc/xdg/autostart/fortgnome-vpn.desktop
rm -f /etc/sudoers.d/fortgnome
update-desktop-database /usr/share/applications 2>/dev/null || true

echo "==> Done. Per-user settings remain in ~/.config/fortgnome/ (delete manually if desired)."
echo "    strongSwan was left installed; remove with: apt-get remove strongswan"
