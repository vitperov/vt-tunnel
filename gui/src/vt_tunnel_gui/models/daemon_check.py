"""Daemon check: is the vt-tunnel systemd service installed, enabled and
running — and if it failed, what did it say?

Reads the state with ``systemctl show`` (machine-readable, no root
needed) and the service's recent output with ``journalctl``. Reading the
system journal needs membership in the ``adm`` or ``systemd-journal``
group; without it journalctl's own message about that is shown instead.

"Working" means what systemd knows: the service's process is running.
The service runs autossh, which keeps running while it retries a failing
ssh, so the recent log is shown in that case too.

Temporary limitation (daemon rewrite in progress): one service, which
runs only the first connection, stands for every connection — see
:func:`service_for` and :func:`coverage_note`.
"""

import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

SERVICE = "vt-tunnel.service"

SYSTEMCTL = "systemctl"
JOURNALCTL = "journalctl"
TIMEOUT_S = 5  # per command; both are local and normally instant
LOG_LINES = 20

PROPERTIES = (
    "LoadState",
    "LoadError",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "Result",
    "ExecMainStatus",
    "NRestarts",
    "ActiveEnterTimestamp",
)

# UnitFileState values that start the service on boot (or need no
# enabling). Anything else doesn't: "disabled", "masked", "linked", and
# "indirect" (e.g. a template, vt-tunnel@.service, with no instance
# enabled).
ENABLED_STATES = frozenset(
    {"enabled", "enabled-runtime", "static", "alias", "generated",
     "transient"}
)
MASKED_STATES = frozenset({"masked", "masked-runtime"})

NO_LOG = "(no log lines)"


class Status(Enum):
    NOT_INSTALLED = "not_installed"
    NOT_ENABLED = "not_enabled"
    WORKING = "working"
    FAILED = "failed"
    UNKNOWN = "unknown"  # the check itself couldn't run (e.g. no systemd)


@dataclass(frozen=True)
class DaemonResult:
    status: Status
    service: str
    message: str  # summary for the user
    log: str  # recent service output, verbatim (may be empty)
    command: str  # to look at it yourself in a terminal


def service_for(number: int) -> str:
    """The systemd service running connection ``number`` (1-based).

    Temporary: one service for all connections. Once the daemon runs one
    instance per connection, this becomes e.g. ``vt-tunnel@{number}``.
    """
    return SERVICE


def coverage_note(number: int) -> str | None:
    """Say so if ``service_for(number)`` doesn't run that connection."""
    if number == 1:
        return None
    return (
        f"For now {SERVICE} runs only the first connection in the list: "
        f"this result is about that connection, not connection {number}."
    )


def run_check(service: str, timeout: float = TIMEOUT_S) -> DaemonResult:
    command = shlex.join([SYSTEMCTL, "status", service])

    def result(status: Status, message: str, log: str = "") -> DaemonResult:
        return DaemonResult(status, service, message, log, command)

    shown = _run(
        [SYSTEMCTL, "show", service, "--property=" + ",".join(PROPERTIES)],
        timeout,
    )
    if isinstance(shown, str):
        return result(Status.UNKNOWN, "Can't ask systemd.", shown)
    code, stdout, stderr = shown
    if code != 0:
        return result(
            Status.UNKNOWN,
            f"Can't ask systemd ({SYSTEMCTL} exit code {code}).",
            _join(stderr, stdout) or NO_LOG,
        )
    props = parse_properties(stdout)

    load = props.get("LoadState", "")
    if load == "not-found":
        return result(
            Status.NOT_INSTALLED,
            f"{service} is not installed. Install the vt-tunnel package.",
        )

    log = _read_log(service, timeout)
    active = props.get("ActiveState", "")
    sub = props.get("SubState", "")
    file_state = props.get("UnitFileState", "")
    enabled = file_state in ENABLED_STATES
    not_enabled_hint = (
        f"It is not enabled ({file_state or 'unknown'}), so it won't "
        "start at boot."
    )

    if load in MASKED_STATES or file_state in MASKED_STATES:
        return result(
            Status.NOT_ENABLED,
            f"{service} is masked: it can't be started until it is "
            f"unmasked (sudo systemctl unmask {service}).",
            log,
        )
    if load != "loaded":
        detail = props.get("LoadError", "")
        return result(
            Status.FAILED,
            f"systemd can't load {service} ({load or 'unknown state'})"
            + (f": {detail}" if detail else "."),
            log,
        )
    if active == "active":
        since = props.get("ActiveEnterTimestamp", "")
        message = f"{service} is running" + (f" since {since}." if since
                                             else ".")
        if not enabled:
            message += " " + not_enabled_hint
        return result(Status.WORKING, message, log)
    if active == "failed":
        message = f"{service} failed ({_failure(props)})."
        if not enabled:
            message += " " + not_enabled_hint
        return result(Status.FAILED, message, log)
    if not enabled:
        return result(
            Status.NOT_ENABLED,
            f"{service} is installed but not enabled "
            f"({file_state or 'unknown'}) and not running. Enable and "
            f"start it: sudo systemctl enable --now {service}",
            log,
        )
    if sub == "auto-restart":
        restarts = props.get("NRestarts", "")
        return result(
            Status.FAILED,
            f"{service} keeps stopping: systemd will restart it soon "
            f"(restarts so far: {restarts or 'unknown'}).",
            log,
        )
    return result(
        Status.FAILED,
        f"{service} is enabled but not running ({active}/{sub}).",
        log,
    )


def parse_properties(text: str) -> dict[str, str]:
    """Parse ``systemctl show`` output: one ``Key=value`` per line."""
    props = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value
    return props


def _failure(props: dict[str, str]) -> str:
    reason = props.get("Result", "") or "unknown reason"
    status = props.get("ExecMainStatus", "")
    if reason == "exit-code" and status not in ("", "0"):
        return f"exit code {status}"
    return reason


def _read_log(service: str, timeout: float) -> str:
    """Recent output of the service, or the reason it can't be read."""
    ran = _run(
        [JOURNALCTL, "--unit", service, "--lines", str(LOG_LINES),
         "--no-pager"],
        timeout,
    )
    if isinstance(ran, str):
        return f"Can't read the log: {ran}"
    _code, stdout, stderr = ran
    # On failure, or without permission to read the system journal,
    # journalctl says why (e.g. which groups may read it): keep that.
    return _join(stdout, stderr) or NO_LOG


def _run(
    argv: Sequence[str], timeout: float
) -> tuple[int, str, str] | str:
    """Run a local command; its (code, stdout, stderr), or why it couldn't
    run."""
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return f"'{argv[0]}' was not found. Does this system use systemd?"
    except subprocess.TimeoutExpired:
        return f"'{argv[0]}' didn't answer within {timeout:g} seconds."
    except OSError as err:
        return f"Can't run '{argv[0]}': {err.strerror or err}"
    return done.returncode, done.stdout, done.stderr


def _join(*parts: str) -> str:
    return "\n".join(p.strip() for p in parts if p.strip())
