# FortGNOME VPN — install instructions for Claude Code

You are helping a user install **FortGNOME VPN**, a GNOME desktop client for a
FortiGate-style IPsec VPN (IKEv1 + XAuth), built on strongSwan.

## Install (do this when the user says "install" / "set this up")

This targets **Debian/Ubuntu** desktops. Two equivalent paths:

1. **Prebuilt package (preferred if present):**
   ```bash
   sudo apt install -y ./dist/fortgnome-vpn_*.deb
   ```
2. **From source:**
   ```bash
   sudo ./install.sh
   ```

Either installs strongSwan + GUI dependencies, the app under `/usr/lib/fortgnome`,
the `fortgnome`/`fortgnome-apply` commands, an app-grid launcher, a login
autostart entry, and a scoped `/etc/sudoers.d/fortgnome` rule, and enables
`strongswan-starter` at boot.

## After installing, tell the user to:
1. Log out and back in (so the top-bar shield indicator starts), or run
   `/usr/lib/fortgnome/fortgnome-gui.py &` for now.
2. Open **FortGNOME VPN** (app grid or the top-bar shield) → **Settings…**,
   enter their **Username** and **Password** (server, PSK and destination
   network are pre-filled), **Save**, then **Connect**.
3. Verify with `fortgnome status` (or watch for the green check on the shield).

## Notes / troubleshooting
- The user must be in the `sudo` group (normal for a desktop admin) for the
  passwordless control rule to apply.
- If connecting fails, run `sudo ipsec up fortgnome` and read the charon log:
  `sudo journalctl -t charon -f`. The phase2 **must be no-PFS** (the `esp` line
  ends with `!`) or the FortiGate returns `NO_PROPOSAL_CHOSEN`.
- **Not Debian/Ubuntu?** Adapt: install the equivalents of `strongswan`,
  `python3-gi`, `gtk3`, `libayatana-appindicator3` + its GIR typelib via the
  native package manager (dnf/pacman/zypper), then copy the files as `install.sh`
  does. On Fedora/RHEL the admin group is `wheel`, not `sudo` — adjust
  `/etc/sudoers.d/fortgnome` accordingly.
- Uninstall: `sudo apt remove fortgnome-vpn` or `sudo ./uninstall.sh`.

## What NOT to do
- Don't commit anyone's personal `~/.config/fortgnome/config.ini` (it holds
  their password).
- Don't change the strongSwan crypto (`ike=`/`esp=`) — those values are
  required by this FortiGate.
