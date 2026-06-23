#!/usr/bin/env python3
"""FortGNOME VPN — GUI + top-bar indicator for a FortiGate IPsec VPN.

Settings (server / username / password / PSK / destination subnet) are stored
per-user in ~/.config/fortgnome/config.ini and applied to strongSwan via the
privileged helper `fortgnome-apply` (run through sudo). First run with no config
opens the Settings dialog automatically.
"""
import os, configparser, subprocess, threading, time, gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, GdkPixbuf, AyatanaAppIndicator3 as AppIndicator

PREFIX   = "/usr/lib/fortgnome"
ICONS    = os.path.join(PREFIX, "icons")
LOGO     = os.path.join(ICONS, "fortgnome-app.png")
DEFAULTS = os.path.join(PREFIX, "defaults.conf")
CFG_DIR  = os.path.expanduser("~/.config/fortgnome")
CFG      = os.path.join(CFG_DIR, "config.ini")
HELPER   = "/usr/bin/fortgnome"
APPLY    = "/usr/bin/fortgnome-apply"
APP_ID   = "fortgnome-vpn"

FIELDS = [  # key, label, is_secret
    ("server",        "VPN server (gateway IP/host)", False),
    ("username",      "Username",                     False),
    ("password",      "Password",                     True),
    ("psk",           "Pre-shared key (PSK)",         True),
    ("remote_subnet", "Destination network (CIDR)",   False),
]

GLib.set_prgname("fortgnome-vpn")
try: Gtk.Window.set_default_icon_from_file(LOGO)
except Exception: pass


def load_config():
    cp = configparser.ConfigParser()
    cp.read([DEFAULTS, CFG])  # shipped defaults, then the user's own values on top
    return dict(cp["vpn"]) if cp.has_section("vpn") else {}

def have_config():
    return os.path.exists(CFG)

def write_config(values):
    # merge onto any existing file so advanced keys (e.g. client_subnet) survive
    cp = configparser.ConfigParser(); cp.read(CFG)
    if not cp.has_section("vpn"): cp.add_section("vpn")
    for k, v in values.items():
        cp.set("vpn", k, v)
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, "w") as f:
        cp.write(f)
    os.chmod(CFG, 0o600)

def apply_config():
    """Run the privileged apply. Returns (ok, message). Safe to call off the
    main thread; has a timeout so a stuck daemon can't block forever."""
    try:
        r = subprocess.run(["sudo", "-n", APPLY], capture_output=True, text=True, timeout=90)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "apply timed out (is the VPN daemon stuck? try Disconnect first)"
    except Exception as e:
        return False, str(e)

def vpn_is_up():
    try:
        out = subprocess.run(["ip", "route", "show", "table", "220"],
                             capture_output=True, text=True, timeout=4).stdout
        return bool(out.strip())
    except Exception:
        return False


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, on_saved):
        super().__init__(title="FortGNOME VPN — Settings", transient_for=parent, flags=0)
        self.on_saved = on_saved
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        self.set_default_size(400, -1)
        cur = load_config()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        for m in ("top", "bottom", "start", "end"): getattr(grid, "set_margin_"+m)(16)
        self.entries = {}
        for row, (key, label, secret) in enumerate(FIELDS):
            lbl = Gtk.Label(label=label, xalign=0)
            ent = Gtk.Entry(); ent.set_hexpand(True); ent.set_text(cur.get(key, ""))
            if secret:
                ent.set_visibility(False)
                ent.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "view-reveal-symbolic")
                ent.connect("icon-press", lambda e, *a: e.set_visibility(not e.get_visibility()))
            if key == "remote_subnet":
                ent.set_placeholder_text("e.g. 10.0.0.0/24")
            grid.attach(lbl, 0, row, 1, 1); grid.attach(ent, 1, row, 1, 1)
            self.entries[key] = ent
        self.msg = Gtk.Label(xalign=0); self.msg.get_style_context().add_class("dim-label")
        grid.attach(self.msg, 0, len(FIELDS), 2, 1)
        self.get_content_area().add(grid)
        self.show_all()
        self.connect("response", self._on_response)

    def _on_response(self, dlg, resp):
        if resp != Gtk.ResponseType.OK:
            self.destroy(); return
        values = {k: e.get_text().strip() for k, e in self.entries.items()}
        missing = [lbl for (k, lbl, _) in FIELDS if not values[k]]
        if missing:
            self.msg.set_markup('<span foreground="red">Please fill: %s</span>' % ", ".join(missing))
            self.stop_emission_by_name("response"); return
        # write the (fast) config file now, then apply in the background so the
        # GUI never freezes while strongSwan reloads.
        write_config(values)
        self.stop_emission_by_name("response")          # keep dialog open until apply finishes
        self.set_response_sensitive(Gtk.ResponseType.OK, False)
        self.set_response_sensitive(Gtk.ResponseType.CANCEL, False)
        self.msg.set_markup("<i>Applying…</i>")
        def worker():
            ok, info = apply_config()
            GLib.idle_add(self._apply_done, ok, info)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_done(self, ok, info):
        if ok:
            self.destroy(); self.on_saved()
        else:
            self.set_response_sensitive(Gtk.ResponseType.OK, True)
            self.set_response_sensitive(Gtk.ResponseType.CANCEL, True)
            self.msg.set_markup('<span foreground="red">Apply failed: %s</span>'
                                % GLib.markup_escape_text(info or "see terminal"))
        return False


class StatusWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="FortGNOME VPN")
        self.app = app
        try: self.set_icon_from_file(LOGO)
        except Exception: pass
        self.set_default_size(320, 320); self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", lambda *_: (self.hide(), True)[1])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for m in ("top", "bottom", "start", "end"): getattr(box, "set_margin_"+m)(18)
        self.img = Gtk.Image(); box.pack_start(self.img, False, False, 0)
        self.lbl = Gtk.Label(); box.pack_start(self.lbl, False, False, 0)
        self.btn = Gtk.Button(); self.btn.set_size_request(-1, 44)
        self.btn.connect("clicked", self.app.on_toggle)
        box.pack_start(self.btn, False, False, 0)
        setb = Gtk.Button(label="Settings…")
        setb.connect("clicked", lambda *_: self.app.open_settings())
        box.pack_start(setb, False, False, 0)
        self.add(box)

    def update(self, up, busy):
        ico = "fortgnome-wait" if busy else ("fortgnome-on" if up else "fortgnome-off")
        self.img.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(
            os.path.join(ICONS, ico + ".png"), 96, 96))
        if busy:
            self.lbl.set_markup("<b>Working…</b>"); self.btn.set_sensitive(False); return
        self.btn.set_sensitive(True)
        if up:
            sub = load_config().get("remote_subnet", "")
            self.lbl.set_markup('<b><span foreground="#1a8a1a">Connected</span></b>'
                                + (f'\n<small>{GLib.markup_escape_text(sub)} reachable</small>' if sub else ""))
            self.btn.set_label("Disconnect")
        else:
            self.lbl.set_markup('<b><span foreground="#888">Disconnected</span></b>')
            self.btn.set_label("Connect")


class ProgressWindow(Gtk.Window):
    STEPS = [
        ("contact", "Contacting VPN gateway"),
        ("auth",    "Authenticating (username & password)"),
        ("netcfg",  "Getting network configuration"),
        ("tunnel",  "Establishing encrypted tunnel"),
    ]
    MARK = {"pending": ("○", "#888888"), "active": ("➤", "#1976d2"),
            "done": ("✓", "#1a8a1a"), "fail": ("✗", "#c0271a")}

    def __init__(self, app):
        super().__init__(title="Connecting — FortGNOME VPN")
        self.app = app
        try: self.set_icon_from_file(LOGO)
        except Exception: pass
        self.set_default_size(380, -1); self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", lambda *_: (self.hide(), True)[1])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for m in ("top", "bottom", "start", "end"): getattr(box, "set_margin_"+m)(18)
        head = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner(); self.spinner.start()
        head.pack_start(self.spinner, False, False, 0)
        self.title = Gtk.Label(xalign=0); self.title.set_markup("<b>Connecting…</b>")
        head.pack_start(self.title, True, True, 0)
        box.pack_start(head, False, False, 0)
        self.rows = {}
        for key, text in self.STEPS:
            row = Gtk.Box(spacing=8)
            ic = Gtk.Label(); tx = Gtk.Label(label=text, xalign=0)
            row.pack_start(ic, False, False, 0); row.pack_start(tx, True, True, 0)
            box.pack_start(row, False, False, 0)
            self.rows[key] = (ic, tx, text)
            self._mark(key, "pending")
        self.detail = Gtk.Label(xalign=0); self.detail.set_line_wrap(True)
        self.detail.get_style_context().add_class("dim-label")
        box.pack_start(self.detail, False, False, 0)
        self.btn = Gtk.Button(label="Close")
        self.btn.connect("clicked", lambda *_: self.destroy())
        self.btn.set_no_show_all(True)
        box.pack_start(self.btn, False, False, 0)
        self.add(box); self.show_all()

    def _mark(self, key, state, note=None):
        ic, tx, text = self.rows[key]
        ch, col = self.MARK[state]
        ic.set_markup('<span foreground="%s" weight="bold">%s</span>' % (col, ch))
        label = text + ("  —  " + note if note else "")
        if state == "fail":
            tx.set_markup('<span foreground="%s">%s</span>' % (col, GLib.markup_escape_text(label)))
        else:
            tx.set_text(label)

    def set_step(self, key, state, note=None):
        self._mark(key, state, note); return False

    def finish_ok(self):
        self.spinner.stop()
        self.title.set_markup('<b><span foreground="#1a8a1a">Connected ✓</span></b>')
        self.app._connect_finished(True)
        GLib.timeout_add_seconds(2, lambda: (self.destroy(), False)[1])
        return False

    def finish_fail(self, key, reason):
        self.spinner.stop()
        self.title.set_markup('<b><span foreground="#c0271a">Connection failed</span></b>')
        self._mark(key, "fail")
        self.detail.set_markup('<span foreground="#c0271a">%s</span>' % GLib.markup_escape_text(reason))
        self.btn.show()
        self.app._connect_finished(False)
        return False


class FortGnome:
    def __init__(self):
        self.busy = False; self.win = None
        self.ind = AppIndicator.Indicator.new_with_path(
            APP_ID, "fortgnome-off", AppIndicator.IndicatorCategory.SYSTEM_SERVICES, ICONS)
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.ind.set_title("FortGNOME VPN")
        m = Gtk.Menu()
        self.mi_status = Gtk.MenuItem(label="…"); self.mi_status.set_sensitive(False)
        self.mi_toggle = Gtk.MenuItem(label="Connect"); self.mi_toggle.connect("activate", self.on_toggle)
        mi_win = Gtk.MenuItem(label="Open window…");   mi_win.connect("activate", lambda *_: self.show_window())
        mi_set = Gtk.MenuItem(label="Settings…");      mi_set.connect("activate", lambda *_: self.open_settings())
        mi_quit = Gtk.MenuItem(label="Quit indicator"); mi_quit.connect("activate", lambda *_: Gtk.main_quit())
        for w in (self.mi_status, Gtk.SeparatorMenuItem(), self.mi_toggle, mi_win, mi_set,
                  Gtk.SeparatorMenuItem(), mi_quit):
            m.append(w)
        m.show_all(); self.ind.set_menu(m)
        self.refresh()
        GLib.timeout_add_seconds(5, self._tick)
        if not have_config():
            GLib.timeout_add(400, lambda: (self.open_settings(), False)[1])

    def set_state(self, up):
        if self.busy: return
        self.ind.set_icon_full("fortgnome-on" if up else "fortgnome-off",
                               "FortGNOME VPN connected" if up else "FortGNOME VPN disconnected")
        self.mi_status.set_label("● Connected" if up else "○ Disconnected")
        self.mi_toggle.set_label("Disconnect" if up else "Connect")
        if self.win: self.win.update(up, False)

    def refresh(self): self.set_state(vpn_is_up())
    def _tick(self):
        if not self.busy: self.refresh()
        return True

    def on_toggle(self, *_):
        if self.busy: return
        if not have_config():
            self.open_settings(); return
        if vpn_is_up(): self._disconnect()
        else:           self._connect()

    def _connect(self):
        self.busy = True
        self.ind.set_icon_full("fortgnome-wait", "FortGNOME VPN connecting")
        self.mi_status.set_label("Connecting…")
        if self.win: self.win.update(True, True)
        prog = ProgressWindow(self)
        threading.Thread(target=self._connect_worker, args=(prog,), daemon=True).start()

    def _disconnect(self):
        self.busy = True
        self.ind.set_icon_full("fortgnome-wait", "FortGNOME VPN working")
        self.mi_status.set_label("Disconnecting…")
        if self.win: self.win.update(False, True)
        def w():
            subprocess.run([HELPER, "down"], capture_output=True)
            GLib.idle_add(self._connect_finished, False)
        threading.Thread(target=w, daemon=True).start()

    def _connect_finished(self, success):
        self.busy = False; self.refresh(); return False

    def _connect_worker(self, prog):
        # make sure the daemon is up first
        if subprocess.run(["pgrep", "-x", "charon"], capture_output=True).returncode != 0:
            subprocess.run(["sudo", "-n", "ipsec", "start"], capture_output=True)
            for _ in range(20):
                if subprocess.run(["sudo", "-n", "ipsec", "status"], capture_output=True).returncode == 0:
                    break
                time.sleep(0.3)
        GLib.idle_add(prog.set_step, "contact", "active")
        done, fail = set(), None
        try:
            proc = subprocess.Popen(["sudo", "-n", "ipsec", "up", "fortgnome"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
        except Exception as e:
            GLib.idle_add(prog.finish_fail, "contact", str(e)); return
        for line in proc.stdout:
            l = line.strip()
            if "IKE_SA" in l and "established between" in l and "contact" not in done:
                done.add("contact")
                GLib.idle_add(prog.set_step, "contact", "done")
                GLib.idle_add(prog.set_step, "auth", "active")
            elif "XAuth authentication" in l and "successful" in l and "auth" not in done:
                done.add("auth")
                GLib.idle_add(prog.set_step, "auth", "done")
                GLib.idle_add(prog.set_step, "netcfg", "active")
            elif "installing new virtual IP" in l and "netcfg" not in done:
                done.add("netcfg")
                GLib.idle_add(prog.set_step, "netcfg", "done", l.split()[-1])
                GLib.idle_add(prog.set_step, "tunnel", "active")
            elif ("established successfully" in l or ("CHILD_SA" in l and "established with" in l)) and "tunnel" not in done:
                done.add("tunnel")
                GLib.idle_add(prog.set_step, "tunnel", "done")
            if "giving up after" in l and not fail:
                fail = ("contact", "No reply from the VPN gateway. Check your internet "
                        "connection and server address, and that this network allows VPN "
                        "(UDP ports 500/4500 — some Wi-Fi/hotspots block them).")
            elif "NO_PROPOSAL_CHOSEN" in l and not fail:
                fail = ("tunnel" if ("auth" in done or "netcfg" in done) else "contact",
                        "The gateway rejected the connection settings (encryption or "
                        "destination network). Check the destination CIDR in Settings.")
        proc.wait(); time.sleep(0.5)
        up = subprocess.run(["ip", "route", "show", "table", "220"],
                            capture_output=True, text=True).stdout.strip() != ""
        if up and "tunnel" in done:
            GLib.idle_add(prog.finish_ok)
        else:
            if not fail:
                if "contact" not in done:
                    fail = ("contact", "Couldn't reach the VPN gateway — check your network and the server address.")
                elif "auth" not in done:
                    fail = ("auth", "Login rejected — check your username and password.")
                elif "netcfg" not in done:
                    fail = ("netcfg", "The gateway didn't assign a network configuration.")
                else:
                    fail = ("tunnel", "Couldn't establish the encrypted tunnel.")
            GLib.idle_add(prog.finish_fail, fail[0], fail[1])

    def open_settings(self):
        SettingsDialog(self.win, on_saved=self.refresh)  # shows itself; response-driven

    def show_window(self):
        if not self.win: self.win = StatusWindow(self)
        self.win.show_all(); self.win.present(); self.win.update(vpn_is_up(), self.busy)


if __name__ == "__main__":
    FortGnome(); Gtk.main()
