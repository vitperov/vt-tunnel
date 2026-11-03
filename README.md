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
sudo dpkg -i package-vt-tunnel_1.1.2_all.deb
```

This installs:
- `vt-tunnel.service` — systemd unit
- `/etc/systemd/vt-tunnel.cfg` — config file

## Quick start

0. If you haven't yet, copy your ssh key to the server — the tunnel runs
   unattended, so access must be passwordless:

   ```bash
   ssh-copy-id user_on_your_server@myserver.com
   ```

1. Edit `/etc/systemd/vt-tunnel.cfg`:

   ```bash
   RUN_DAEMON_USER=your_local_user

   REMOTE_USER=user_on_your_server
   REMOTE_SERVER=myserver.com
   REMOTE_SSH_PORT=22

   LOCAL_PORT1=22
   REMOTE_PORT1=5001
   ```

   With this config, port `22` on this machine shows up as port `5001`
   on `myserver.com`.

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

## License

[MIT](LICENSE)