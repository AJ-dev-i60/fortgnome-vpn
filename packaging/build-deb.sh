#!/bin/bash
# Build fortgnome-vpn_<ver>_all.deb from ../src into ../dist
set -e
VER="${1:-1.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"
OUT="$HERE/../dist"
BUILD="$(mktemp -d)"
PKG="$BUILD/fortgnome-vpn"
trap 'rm -rf "$BUILD"' EXIT

# ---- file tree ----
install -d -m 755 "$PKG/usr/lib/fortgnome/icons"
install -m 644 "$SRC"/icons/* "$PKG/usr/lib/fortgnome/icons/"
install -m 755 "$SRC/fortgnome-gui.py" "$PKG/usr/lib/fortgnome/fortgnome-gui.py"
install -m 644 "$SRC/defaults.conf"    "$PKG/usr/lib/fortgnome/defaults.conf"
install -d -m 755 "$PKG/usr/bin"
install -m 755 "$SRC/fortgnome"        "$PKG/usr/bin/fortgnome"
install -m 755 "$SRC/fortgnome-apply"  "$PKG/usr/bin/fortgnome-apply"
install -d -m 755 "$PKG/usr/share/applications"
install -m 644 "$SRC/fortgnome-vpn.desktop" "$PKG/usr/share/applications/fortgnome-vpn.desktop"
install -d -m 755 "$PKG/etc/xdg/autostart"
install -m 644 "$SRC/fortgnome-vpn-autostart.desktop" "$PKG/etc/xdg/autostart/fortgnome-vpn.desktop"
install -d -m 755 "$PKG/etc/sudoers.d"
install -m 440 "$SRC/fortgnome.sudoers" "$PKG/etc/sudoers.d/fortgnome"

# ---- control metadata ----
install -d -m 755 "$PKG/DEBIAN"
cat > "$PKG/DEBIAN/control" <<EOF
Package: fortgnome-vpn
Version: $VER
Architecture: all
Maintainer: FortGNOME VPN <fortgnome@users.noreply.github.com>
Section: net
Priority: optional
Depends: strongswan, strongswan-starter, libcharon-extra-plugins, python3-gi, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1, libayatana-appindicator3-1, libnotify-bin, iproute2
Description: FortGNOME VPN - desktop client for FortiGate IPsec (IKEv1/XAuth) VPNs
 A simple GTK GUI with a top-bar indicator to connect to a FortiGate
 FortiClient-style IPsec VPN on GNOME desktops, built on strongSwan.
 Enter your credentials in Settings and connect with one click.
EOF

cat > "$PKG/DEBIAN/conffiles" <<EOF
/etc/sudoers.d/fortgnome
/etc/xdg/autostart/fortgnome-vpn.desktop
EOF

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
chmod 440 /etc/sudoers.d/fortgnome 2>/dev/null || true
if ! visudo -cf /etc/sudoers.d/fortgnome >/dev/null 2>&1; then
  echo "FortGNOME: sudoers rule invalid, removing it"; rm -f /etc/sudoers.d/fortgnome
fi
systemctl enable strongswan-starter.service >/dev/null 2>&1 || true
systemctl start  strongswan-starter.service >/dev/null 2>&1 || true
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
exit 0
EOF
chmod 755 "$PKG/DEBIAN/postinst"

cat > "$PKG/DEBIAN/prerm" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
  ipsec down fortgnome >/dev/null 2>&1 || true
  rm -f /etc/ipsec.d/fortgnome.conf /etc/ipsec.d/fortgnome.secrets
  sed -i '\#include /etc/ipsec.d/fortgnome.conf#d'    /etc/ipsec.conf    2>/dev/null || true
  sed -i '\#include /etc/ipsec.d/fortgnome.secrets#d' /etc/ipsec.secrets 2>/dev/null || true
  ipsec reload >/dev/null 2>&1 || true
  pkill -f /usr/lib/fortgnome/fortgnome-gui.py 2>/dev/null || true
fi
exit 0
EOF
chmod 755 "$PKG/DEBIAN/prerm"

cat > "$PKG/DEBIAN/postrm" <<'EOF'
#!/bin/bash
set -e
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
exit 0
EOF
chmod 755 "$PKG/DEBIAN/postrm"

# ---- build ----
mkdir -p "$OUT"
DEB="$OUT/fortgnome-vpn_${VER}_all.deb"
dpkg-deb --root-owner-group --build "$PKG" "$DEB"
echo "Built: $DEB"
dpkg-deb --info "$DEB" | sed -n '1,20p'
