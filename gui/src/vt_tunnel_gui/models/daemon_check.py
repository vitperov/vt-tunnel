"""Daemon check: is the vt-tunnel systemd service installed, enabled and
running — and if it failed, what did it say?

Reads the state with ``systemctl show`` (machine-readable, no root
needed) and the service's recent output with ``journalctl``. Reading the
system journal needs membership in the ``adm`` or ``systemd-journal``
group; without it journalctl's own message about that is shown instead.

Results come with suggestions: the ``sudo systemctl`` command to enable
or start the service, and on failure how to test the SSH login.

"Working" means what systemd knows: the service's process is running.
The service runs autossh, which keeps running while it retries a failing
ssh, so the recent log is shown in that case too.

Temporary limitation (daemon rewrite in progress): the per-connection
template ``vt-tunnel@<NAME>.service`` doesn't exist yet, so the old
single service stands for every connection — see :func:`service_for`
and :func:`coverage_note`.
"""

import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from vt_tunnel_gui.models.advice import Suggestion

SERVICE = "vt-tunnel.service"  # the old single service
TEMPLATE = "vt-tunnel@{name}.service"  # planned: one per connection

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
    suggestions: tuple[Suggestion, ...] = ()


def service_for(name: str) -> str:
    """The systemd service running connection ``name``.

    Temporary: the old single service for all connections. Once the
    template exists: ``TEMPLATE.format(name=name)``.
    """
    return SERVICE


def coverage_note(name: str) -> str | None:
    """Say so if ``service_for(name)`` doesn't run connection ``name``."""
    return (
        f"For now this checks {SERVICE}, the old single service: it reads "
        "/etc/systemd/system/vt-tunnel.cfg, not the connection files. The "
        f"per-connection service ({TEMPLATE.format(name=name)}) doesn't "
        "exist yet, so this result isn't about connection "
        f"\u201c{name}\u201d."
    )


# Advice on failure: the usual cause is the SSH login.
CHECK_SSH_ADVICE = (
    "The tunnel logs in to the server with an SSH key, without a "
    "password; a failing login is a common cause. To test it, click "
    "\u201cEdit\u201d on the connection, then \u201cCheck connection\u201d."
)


def _systemctl(verb: str, service: str) -> str:
    return shlex.join(["sudo", SYSTEMCTL, verb, service])


def enable_suggestion(service: str) -> Suggestion:
    return Suggestion(
        "Enable it, so that it starts at boot:",
        _systemctl("enable", service),
    )


def start_suggestion(service: str) -> Suggestion:
    return Suggestion("Start it now:", _systemctl("start", service))


def run_check(service: str, timeout: float = TIMEOUT_S) -> DaemonResult:
    command = shlex.join([SYSTEMCTL, "status", service])

    def result(
        status: Status,
        message: str,
        log: str = "",
        suggestions: tuple[Suggestion, ...] = (),
    ) -> DaemonResult:
        return DaemonResult(
            status, service, message, log, command, suggestions
        )

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
    enable = enable_suggestion(service)
    start = start_suggestion(service)
    check_ssh = Suggestion(CHECK_SSH_ADVICE)
    # Offered only where it applies: the service isn't enabled.
    maybe_enable = () if enabled else (enable,)

    if load in MASKED_STATES or file_state in MASKED_STATES:
        return result(
            Status.NOT_ENABLED,
            f"{service} is masked: it can't be started or enabled until "
            "it is unmasked.",
            log,
            (
                Suggestion(
                    "Unmask it first:", _systemctl("unmask", service)
                ),
                enable,
                start,
            ),
        )
    if load != "loaded":
        detail = props.get("LoadError", "")
        return result(
            Status.FAILED,
            f"systemd can't load {service} ({load or 'unknown state'})"
            + (f": {detail}" if detail else "."),
            log,
            (Suggestion(
                "Its unit file is broken: reinstall the vt-tunnel package "
                "(or fix the file), then make systemd read it again:",
                shlex.join(["sudo", SYSTEMCTL, "daemon-reload"]),
            ),),
        )
    if active == "active":
        since = props.get("ActiveEnterTimestamp", "")
        message = f"{service} is running" + (f" since {since}." if since
                                             else ".")
        if not enabled:
            message += " " + not_enabled_hint
        return result(Status.WORKING, message, log, maybe_enable)
    if active == "failed":
        message = f"{service} failed ({_failure(props)})."
        if not enabled:
            message += " " + not_enabled_hint
        return result(
            Status.FAILED,
            message,
            log,
            (
                check_ssh,
                Suggestion(
                    "Once the cause is fixed, start it again:",
                    _systemctl("restart", service),
                ),
                *maybe_enable,
            ),
        )
    if not enabled:
        return result(
            Status.NOT_ENABLED,
            f"{service} is installed, but not enabled "
            f"({file_state or 'unknown'}) and not running.",
            log,
            (enable, start),
        )
    if sub == "auto-restart":
        restarts = props.get("NRestarts", "")
        return result(
            Status.FAILED,
            f"{service} keeps stopping: systemd will restart it soon "
            f"(restarts so far: {restarts or 'unknown'}).",
            log,
            (check_ssh,),  # systemd retries by itself: nothing to start
        )
    return result(
        Status.FAILED,
        f"{service} is enabled but not running ({active}/{sub}).",
        log,
        (start,),
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
