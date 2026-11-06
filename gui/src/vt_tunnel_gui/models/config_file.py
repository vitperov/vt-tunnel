"""Reading of the daemon config file (systemd ``EnvironmentFile=`` format).

Format, as specified in ``doc/config.md``:

- one ``KEY=VALUE`` pair per line
- everything after ``#`` is a comment
- no quoting and no variable expansion: the value is the rest of the
  line, verbatim (only surrounding whitespace is stripped)
- empty lines are ignored

Lines without ``=`` are ignored; if a key repeats, the last one wins.
"""

from pathlib import Path

COMMENT_CHAR = "#"


def parse(text: str) -> dict[str, str]:
    """Parse config text into a ``{KEY: VALUE}`` dict (all keys kept)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split(COMMENT_CHAR, 1)[0]
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        values[key] = value.strip()
    return values


def read(path: Path) -> dict[str, str]:
    """Read and parse the config file; ``OSError`` propagates to the caller."""
    return parse(path.read_text(encoding="utf-8", errors="replace"))
