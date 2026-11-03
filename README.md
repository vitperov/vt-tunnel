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
- ssh key at `~/.ssh/id_rsa` that can access your server without a password

## Installation (Debian/Ubuntu)

Download the latest `.deb` from [Releases](https://github.com/vitperov/vt-tunnel/releases), then:

```bash
sudo dpkg -i package-vt-tunnel_1.1.2_all.deb
```

This installs:
- `vt-tunnel.service` — systemd unit
- `/etc/systemd/vt-tunnel.cfg` — config file

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