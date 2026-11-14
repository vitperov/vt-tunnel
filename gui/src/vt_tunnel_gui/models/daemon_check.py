"""The daemon check: systemd state of one connection's service.

Every connection maps to one instance of the ``vt-tunnel@`` template
unit. The check asks systemd for that instance's state with one
machine-readable ``systemctl show`` call (no root needed), parses the
``Key=value`` answer, and — for every unit systemd knows — reads the
service's recent log with one ``journalctl`` call. It reports a frozen
result: a status, the service name, a summary message, the service log
(verbatim, may be empty), a command to look yourself, and suggestions.
When systemd cannot be asked at all — the binary is missing, hangs,
exits nonzero, or cannot be started — the result is UNKNOWN. The check
never raises: every command failure becomes part of the result.
"""

import dataclasses
import subprocess

from vt_tunnel_gui.models.advice import Suggestion

# Each command is given this long to answer by default.
DEFAULT_TIMEOUT = 5

# Status of a check that could not ask systemd at all.
UNKNOWN = "unknown"

# Statuses of a check that asked systemd and recognized the state.
NOT_INSTALLED = "not-installed"
WORKING = "working"
NOT_ENABLED = "not-enabled"
FAILED = "failed"

# Shown in place of the log when journalctl printed nothing.
_NO_LOG_LINES = "(no log lines)"

# The number of recent journal lines the check reads.
LOG_LINES = 20

# Unit-file states that start the service on boot, or need no enabling.
ENABLED_STATES = frozenset(
    {"enabled", "enabled-runtime", "static", "alias", "generated", "transient"}
)

# Load and unit-file states that mean the unit is masked.
MASKED_STATES = frozenset({"masked", "masked-runtime"})

# The exact properties the state query asks for, in this order.
QUERY_PROPERTIES = (
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


@dataclasses.dataclass(frozen=True)
class DaemonCheckResult:
    """One finished daemon check.

    ``status`` is one of the module's status constants; ``service`` is
    the queried systemd instance; ``message`` is the summary shown to
    the user; ``log`` is the recent service log, verbatim (may be
    empty); ``command`` is the look-yourself command line, ready to
    paste into a terminal; ``suggestions`` is a tuple of Suggestion
    records (see the advice module).
    """

    status: str
    service: str
    message: str
    log: str
    command: str
    suggestions: tuple


def service_for(name):
    """The service instance of the template unit for one connection."""
    return f"vt-tunnel@{name}.service"


def check(name, timeout=DEFAULT_TIMEOUT):
    """Check the systemd state of one connection's service.

    ``name`` is the connection name; the queried unit is the
    ``vt-tunnel@<name>.service`` instance of the template. ``name``
    goes to systemctl as-is — the caller validates it first (a value
    starting with a dash would be taken for an option). Returns a
    DaemonCheckResult; never raises.
    """
    service = service_for(name)
    argv = [
        "systemctl",
        "show",
        service,
        f"--property={','.join(QUERY_PROPERTIES)}",
    ]

    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return _unknown(
            service,
            message="'systemctl' was not found. Does this system use systemd?",
        )
    except subprocess.TimeoutExpired:
        return _unknown(
            service,
            log=f"No answer from systemctl within {timeout} seconds.",
        )
    except OSError as error:
        return _unknown(service, log=str(error))

    if proc.returncode != 0:
        return _unknown(service, log=_joined(proc.stdout, proc.stderr))

    properties = parse_properties(proc.stdout)
    if properties.get("LoadState", "") == "not-found":
        # Nothing to read a log of: systemd knows no such unit.
        return _not_installed(service)
    return _decide(properties, service, _read_log(service, timeout))


def parse_properties(text):
    """Parse systemctl's ``Key=value`` answer into a dict.

    One property per line; only the first ``=`` separates, so a value
    may contain ``=``. Lines without a ``=`` — and lines with an empty
    key — are junk and are ignored; a repeated key keeps its last
    value.
    """
    properties = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key:
            continue
        properties[key] = value
    return properties


def _read_log(service, timeout):
    """The service's recent log, or a message about why there is none.

    One ``journalctl`` call for the unit's own entries; both captured
    streams are joined, so journalctl's own message survives when
    reading fails (reading the system journal needs membership in the
    ``adm`` or ``systemd-journal`` group). Empty output becomes the
    "(no log lines)" placeholder; a command that cannot run becomes a
    "Can't read the log: <reason>" line.
    """
    argv = ["journalctl", "--unit", service, "--lines", str(LOG_LINES), "--no-pager"]
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return "Can't read the log: 'journalctl' was not found."
    except subprocess.TimeoutExpired:
        return f"Can't read the log: no answer within {timeout} seconds."
    except OSError as error:
        return f"Can't read the log: {error}"
    return _joined(proc.stdout, proc.stderr) or _NO_LOG_LINES


def _decide(properties, service, log):
    """Decide the result from the parsed state properties.

    ``properties`` holds the query's parsed answer; ``log`` is the
    recent service log as read by ``_read_log``. The caller reads the
    log only for units systemd knows, so every branch here carries it.
    """
    load_state = properties.get("LoadState", "")
    file_state = properties.get("UnitFileState", "")
    active_state = properties.get("ActiveState", "")

    if load_state in MASKED_STATES or file_state in MASKED_STATES:
        return _masked(service, log)
    if load_state != "loaded":
        # systemd has the unit but cannot load it: the file is broken.
        return _broken(properties, service, log)
    if active_state == "active":
        return _working(properties, service, file_state, log)
    if active_state == "failed":
        return _failed(properties, service, file_state, log)
    if file_state not in ENABLED_STATES:
        return _not_enabled_not_running(service, file_state)
    if properties.get("SubState", "") == "auto-restart":
        return _restart_loop(properties, service, log)
    return _enabled_but_stopped(properties, service, active_state, log)


def _result(status, service, message, suggestions, log=""):
    """One decided result with the standard look-yourself command."""
    return DaemonCheckResult(
        status=status,
        service=service,
        message=message,
        log=log,
        command=f"systemctl status {service}",
        suggestions=suggestions,
    )


def _unknown(service, message="Can't ask systemd", log=""):
    """The UNKNOWN result: the check itself could not ask systemd."""
    return _result(UNKNOWN, service, message, (), log=log)


def _not_installed(service):
    """The NOT_INSTALLED result: systemd knows no such unit."""
    return _result(
        NOT_INSTALLED,
        service,
        f"{service} is not installed. Install the vt-tunnel package.",
        (),
    )


def _masked(service, log):
    """The NOT_ENABLED result for a masked unit."""
    return _result(
        NOT_ENABLED,
        service,
        (
            f"{service} is masked: it can't be started or enabled "
            "until it is unmasked."
        ),
        (
            _suggestion(
                "Unmask it, so it can be enabled and started:", "unmask", service
            ),
            _suggestion("Then enable it, so it starts at boot:", "enable", service),
            _suggestion("Then start it:", "start", service),
        ),
        log=log,
    )


def _broken(properties, service, log):
    """The FAILED result for a unit systemd cannot load."""
    detail = properties.get("LoadError", "")
    if detail and detail != "0":
        message = f"{service} can't be loaded: {detail}"
    else:
        message = f"{service} can't be loaded."
    return _result(
        FAILED,
        service,
        message,
        (
            Suggestion(
                text=(
                    "The unit file is broken — reinstall the vt-tunnel "
                    "package (or fix the file), then make systemd read "
                    "it again:"
                ),
                command="sudo systemctl daemon-reload",
            ),
        ),
        log=log,
    )


def _working(properties, service, file_state, log):
    """The WORKING result: the service's process is running."""
    timestamp = properties.get("ActiveEnterTimestamp", "")
    if timestamp:
        message = f"{service} is running since {timestamp}."
    else:
        message = f"{service} is running."
    if file_state not in ENABLED_STATES:
        message += (
            f" It is not enabled ({file_state}), so it won't start at boot."
        )
        suggestions = (_enable_suggestion(service),)
    else:
        suggestions = ()
    return _result(WORKING, service, message, suggestions, log=log)


def _failed(properties, service, file_state, log):
    """The FAILED result: the service's process failed."""
    reason = _failure_reason(properties)
    message = f"{service} failed ({reason})."
    suggestions = [_check_ssh_suggestion(), _restart_suggestion(service)]
    if file_state not in ENABLED_STATES:
        message += (
            f" It is not enabled ({file_state}), so it won't start at boot."
        )
        suggestions.append(_enable_suggestion(service))
    return _result(FAILED, service, message, tuple(suggestions), log=log)


def _restart_loop(properties, service, log):
    """The FAILED result for a service systemd keeps restarting."""
    restarts = properties.get("NRestarts", "0") or "0"
    return _result(
        FAILED,
        service,
        (
            f"{service} keeps stopping: systemd will restart it soon "
            f"(restarts so far: {restarts})."
        ),
        # systemd retries by itself — nothing to start.
        (_check_ssh_suggestion(),),
        log=log,
    )


def _enabled_but_stopped(properties, service, active_state, log):
    """The FAILED result for an enabled service that is not running."""
    sub_state = properties.get("SubState", "")
    return _result(
        FAILED,
        service,
        f"enabled but not running ({active_state}/{sub_state})",
        (_suggestion("Start it:", "start", service),),
        log=log,
    )


def _failure_reason(properties):
    """The failure reason from the Result property, rendered for people.

    An ``exit-code`` result with a nonzero main status reads as
    "exit code <N>"; anything else is shown as systemd reported it.
    """
    result = properties.get("Result", "")
    if result == "exit-code":
        status = properties.get("ExecMainStatus", "")
        if status and status != "0":
            return f"exit code {status}"
    return result


def _check_ssh_suggestion():
    """The check-ssh advice: a failing ssh login is a common cause."""
    return Suggestion(
        text=(
            "The tunnel logs in with an SSH key, without a password — "
            "a failing login is a common cause. To test it, click "
            '"Edit" on the connection, then "Check connection".'
        ),
    )


def _restart_suggestion(service):
    """The restart suggestion: run the service again once fixed."""
    return Suggestion(
        text="Once the cause is fixed, start it again:",
        command=f"sudo systemctl restart {service}",
    )


def _not_enabled_not_running(service, file_state):
    """The NOT_ENABLED result: installed, but not enabled and not running."""
    return _result(
        NOT_ENABLED,
        service,
        f"installed, but not enabled ({file_state}) and not running",
        (
            _enable_suggestion(service),
            _suggestion("Then start it:", "start", service),
        ),
    )


def _enable_suggestion(service):
    """The enable suggestion: make the service start at boot."""
    return Suggestion(
        text="Enable it, so it starts at boot:",
        command=f"sudo systemctl enable {service}",
    )


def _suggestion(text, verb, service):
    """One systemctl suggestion: advice text plus the pasteable command."""
    return Suggestion(text=text, command=f"sudo systemctl {verb} {service}")


def _joined(stdout, stderr):
    """Both captured streams as one text, empty pieces dropped."""
    return "\n".join(part for part in (stdout, stderr) if part)
