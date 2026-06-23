# FortGNOME VPN

A small GTK GUI + top-bar indicator for connecting Linux/GNOME desktops to a
FortiGate-style **IPsec VPN** (IKEv1 + XAuth + Mode-Config), built on
[strongSwan](https://www.strongswan.org/). Independent, open-source client —
not affiliated with or endorsed by Fortinet; the shield icon is original art.

- 🛡️ Blue shield in the top bar — adds a green check badge when connected.
- One-click connect/disconnect; a Settings dialog for your connection details.
- Terminal control: `fortgnome up | down | toggle | status`.

## Install (Debian/Ubuntu)

### Option A — double-click package
Download `dist/fortgnome-vpn_1.0_all.deb`, double-click it (opens in your
software installer) **or**:

```bash
sudo apt install ./fortgnome-vpn_1.0_all.deb
```

`apt` pulls in strongSwan and all GUI dependencies automatically.

### Option B — from this repo
```bash
git clone https://github.com/AJ-dev-i60/fortgnome-vpn.git && cd fortgnome-vpn
sudo ./install.sh
```

### Option C — via Claude Code
Open Claude Code in a clone of this repo and say **"install this"**. It follows
`CLAUDE.md` and runs the installer for you.

## First run
Log out/in (the indicator autostarts) or run `/usr/lib/fortgnome/fortgnome-gui.py &`.
Open **FortGNOME VPN** (app grid or the top-bar shield) → **Settings…** and enter:

| Field | Example |
|-------|---------|
| VPN server (gateway) | `vpn.example.com` or `203.0.113.10` |
| Username | your VPN login |
| Password | your VPN password |
| Pre-shared key (PSK) | from your VPN administrator |
| Destination network (CIDR) | `10.0.0.0/24` (the internal network to reach) |

**Save**, then **Connect**. Blue shield + green check = connected.

## Packaging for a team (optional)
An admin can pre-fill the **non-secret** shared values (`server`,
`remote_subnet`) in `src/defaults.conf` so colleagues only enter their own
username/password, then rebuild:

```bash
packaging/build-deb.sh 1.0
```

> ⚠️ Do **not** commit a real PSK or credentials to a public repository. Leave
> `psk` blank in `defaults.conf` and have each user enter it once in Settings,
> or distribute it through a private channel.

## Uninstall
```bash
sudo ./uninstall.sh        # or: sudo apt remove fortgnome-vpn
```

## How it works
`fortgnome-apply` (run as root via a scoped sudoers rule) turns your
`~/.config/fortgnome/config.ini` into a strongSwan `conn fortgnome` under
`/etc/ipsec.d/`. The crypto profile targets common FortiGate IPsec dialups:
IKEv1 main mode, PSK + XAuth (two auth rounds), Mode-Config virtual IP, and a
**no-PFS** phase2 (the `esp=…!` strict proposal — many FortiGate phase2 configs
reject a PFS/KE payload with `NO_PROPOSAL_CHOSEN`). Targets Debian/Ubuntu;
adaptable to other distros (see `CLAUDE.md`).

## Security notes
- Per-user settings live in `~/.config/fortgnome/config.ini` (mode `0600`) and
  in root-only `/etc/ipsec.d/fortgnome.secrets`. Neither is committed.
- The sudoers rule scopes passwordless access to just `ipsec` and
  `fortgnome-apply` for members of the `sudo` group.
