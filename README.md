# vt-tunnel

![vt-tunnel logo](doc/tunnel-logo.png)

## About

Imagine you left your laptop at home with important files on it.
You're at the office, you want to grab a file or SSH in — but you can't.
Your home machine sits behind a NAT, it has no address the outside world
can reach.

Or: you've deployed an early prototype to a customer. It crashes sometimes,
and you need SSH access to collect the logs. The customer's network is
behind a NAT too — so instead of digging through logs you'd have to drive
there in person.

**vt-tunnel** solves both — if you have your own VPS or server with a
public IP. Your laptop or prototype then becomes accessible as
`myserver.com:1234`.

It does it with a plain SSH **reverse tunnel**: vt-tunnel runs as a daemon
on your machine (or the prototype) and opens an SSH connection *out* to
your server. From that moment you can connect *back* through the server —
from the office, from home, from anywhere — straight to the machine
behind the NAT. No public IP on your machine, no router port forwarding,
no third-party tunnel services.

## Requirements

- Debian/Ubuntu with systemd
- `autossh` (pulled in automatically with the package)
- **passwordless ssh access to your server** — the daemon runs unattended
  and can't type passwords. See Quick start below.

## Installation (Debian/Ubuntu)

Download the latest `.deb` from [Releases](https://github.com/vitperov/vt-tunnel/releases), then:

```bash
sudo dpkg -i package-vt-tunnel_2.0.0_all.deb
```

This installs:
- `vt-tunnel@.service` — systemd template unit; every connection runs
  as its own service instance `vt-tunnel@<name>.service`
- `/etc/vt-tunnel/connections.d/` — directory holding one `<name>.conf`
  file per connection, plus a starter `example.conf`

## Quick start

0. If you haven't yet, copy your ssh key to the server — the tunnel runs
   unattended, so access must be passwordless:

   ```bash
   ssh-copy-id user_on_your_server@myserver.com
   ```

1. Copy the example to a named connection — the file name is the
   connection's name:

   ```bash
   sudo cp /etc/vt-tunnel/connections.d/example.conf \
           /etc/vt-tunnel/connections.d/home.conf
   ```

2. Edit the copy (the keys are described in
   [gui/doc/config.md](gui/doc/config.md)):

   ```bash
   sudoedit /etc/vt-tunnel/connections.d/home.conf
   ```

   With this config, port `22` on this machine shows up as port `5001`
   on `myserver.com`. (`ENABLED` is not used yet — the tunnel is
   switched on by enabling its service instance, see step 3.)

3. Enable and start this connection's instance:

   ```bash
   sudo systemctl enable --now vt-tunnel@home
   ```

4. From anywhere, connect back:

   ```bash
   ssh -p 5001 your_local_user@myserver.com
   ```

Every connection file runs as its own service instance, so several
tunnels can run at once — just add more files. Applying an edit to a
running connection means restarting its instance
(`sudo systemctl restart vt-tunnel@home`).

Don't want to hand-edit? The `vt-tunnel-gui` package installs a desktop
app that manages the connection files for you — creating, editing,
renaming and deleting them, and checking each connection's ssh access
and daemon state.

## Building from source

Requires `fakeroot` and `lintian`:

```bash
sudo apt install fakeroot lintian
```

Then:

```bash
cd daemon
./buildDebianDaemon.sh
```

The package lands in `daemon/build/`.

## Future plans

vt-tunnel is functional but minimal. Multi-connection support is done:
every connection file under `/etc/vt-tunnel/connections.d/` runs as its
own service instance, so several tunnels run at once. The
`vt-tunnel-gui` package installs a desktop app that manages connection
files — create, edit, rename and delete them, and check the daemon
state and ssh access of each connection. What's still on the roadmap:

- **A privileged polkit helper**, so the GUI can write connection files
  and restart services without running as root.
- **A system tray icon** — state display and enable/disable from the
  tray.
- **A desktop-entry icon.**

## License

[MIT](LICENSE)