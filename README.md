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
sudo dpkg -i package-vt-tunnel_1.2.0_all.deb
```

This installs:
- `vt-tunnel.service` — systemd unit
- `/etc/systemd/system/vt-tunnel.cfg` — config file

## Quick start

0. If you haven't yet, copy your ssh key to the server — the tunnel runs
   unattended, so access must be passwordless:

   ```bash
   ssh-copy-id user_on_your_server@myserver.com
   ```

1. Edit `/etc/systemd/system/vt-tunnel.cfg`:

   ```bash
   # ===== Connection 1: home =====
   NAME1=home
   ENABLED1=false
   RUN_DAEMON_USER1=your_local_user
   REMOTE_USER1=user_on_your_server
   REMOTE_SERVER1=myserver.com
   LOCAL_PORT1=22
   REMOTE_PORT1=5001
   ```

   With this config, port `22` on this machine shows up as port `5001`
   on `myserver.com`. (`ENABLED1` is not used yet — the tunnel is
   switched on by enabling the service, see step 2.)

2. Enable and start the service:

   ```bash
   sudo systemctl enable --now vt-tunnel
   ```

3. From anywhere, connect back:

   ```bash
   ssh -p 5001 your_local_user@myserver.com
   ```

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

vt-tunnel is functional but minimal. A config GUI already exists — the
`vt-tunnel-gui` package installs a small desktop app for editing
`/etc/systemd/system/vt-tunnel.cfg`. What's still on the roadmap:

- **Multiple connections.** The config format supports numbered
  connections (`NAME1`, `NAME2`, ...), and the GUI can manage them, but
  the daemon currently tunnels only the first one. Planned: daemon-side
  support for every configured connection, so one daemon can expose SSH
  alongside a web UI, or a VNC/RDP remote desktop.

## License

[MIT](LICENSE)