#!/bin/bash
# FortGNOME VPN — installer for Debian/Ubuntu desktops.  Run:  sudo ./install.sh
set -e
if [ "$(id -u)" -ne 0 ]; then echo "Please run with sudo:  sudo ./install.sh" >&2; exit 1; fi
SRC="$(cd "$(dirname "$0")/src" && pwd)"

echo "==> Installing dependencies (strongSwan + GUI)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y \
  strongswan strongswan-starter libcharon-extra-plugins libstrongswan-extra-plugins \
  python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
  libnotify-bin iproute2 >/dev/null

echo "==> Installing application files…"
install -d -m 755 /usr/lib/fortgnome/icons
install -m 644 "$SRC"/icons/* /usr/lib/fortgnome/icons/
install -m 755 "$SRC/fortgnome-gui.py" /usr/lib/fortgnome/fortgnome-gui.py
[ -f /usr/lib/fortgnome/defaults.conf ] || install -m 644 "$SRC/defaults.conf" /usr/lib/fortgnome/defaults.conf
install -m 755 "$SRC/fortgnome"        /usr/bin/fortgnome
install -m 755 "$SRC/fortgnome-apply"  /usr/bin/fortgnome-apply
install -m 644 "$SRC/fortgnome-vpn.desktop" /usr/share/applications/fortgnome-vpn.desktop
install -d -m 755 /etc/xdg/autostart
install -m 644 "$SRC/fortgnome-vpn-autostart.desktop" /etc/xdg/autostart/fortgnome-vpn.desktop
install -m 440 "$SRC/fortgnome.sudoers" /etc/sudoers.d/fortgnome
visudo -cf /etc/sudoers.d/fortgnome >/dev/null || { echo "sudoers validation failed"; rm -f /etc/sudoers.d/fortgnome; exit 1; }
update-desktop-database /usr/share/applications 2>/dev/null || true

echo "==> Enabling strongSwan at boot…"
systemctl enable strongswan-starter.service >/dev/null 2>&1 || true
systemctl start  strongswan-starter.service >/dev/null 2>&1 || true

cat <<'DONE'

==> FortGNOME VPN installed.

Next (as the normal desktop user, NOT root):
  1. Log out/in (indicator autostarts) or run:  /usr/lib/fortgnome/fortgnome-gui.py &
  2. Top-bar shield (or "FortGNOME VPN" in the app grid) -> Settings…
     -> enter your Username + Password (server/PSK/destination are pre-filled) -> Save
  3. Click Connect. Blue shield + green check = connected.

Terminal:  fortgnome up | down | toggle | status
DONE
