# vt-tunnel

<p align="center">
  <img src="doc/tunnel-logo.png" alt="vt-tunnel logo" width="250">
</p>

<p align="center">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Debian package" src="https://img.shields.io/badge/package-v1.1.0-blue.svg">
</p>

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