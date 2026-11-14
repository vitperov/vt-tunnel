"""The daemon check: systemd state of one connection's service.

Every connection maps to one instance of the ``vt-tunnel@`` template
unit. The check asks systemd for that instance's state with one
machine-readable ``systemctl show`` call (no root needed), parses the
``Key=value`` answer, and reports a frozen result: a status, the
service name, a summary message, the service log (verbatim, may be
empty), a command to look yourself, and suggestions. When systemd
cannot be asked at all — the binary is missing, hangs, exits nonzero,
or cannot be started — the result is UNKNOWN. The check never raises:
every command failure becomes part of the result.
"""

import dataclasses
import subprocess

# Each command is given this long to answer by default.
DEFAULT_TIMEOUT = 5

# Status of a check that could not ask systemd at all.
UNKNOWN = "unknown"

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
    return _decide(properties, service, proc.stdout)


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


def _decide(properties, service, output):
    """Decide the result from the parsed state properties.

    ``properties`` holds the query's parsed answer; ``output`` is the
    raw dump, kept for results that must show what was asked.
    """
    # No branch classifies a parsed answer yet: report it as unknown
    # rather than guess a state.
    return _unknown(service, log=output)


def _unknown(service, message="Can't ask systemd", log=""):
    """The UNKNOWN result: the check itself could not ask systemd."""
    return DaemonCheckResult(
        status=UNKNOWN,
        service=service,
        message=message,
        log=log,
        command=f"systemctl status {service}",
        suggestions=(),
    )


def _joined(stdout, stderr):
    """Both captured streams as one text, empty pieces dropped."""
    return "\n".join(part for part in (stdout, stderr) if part)
