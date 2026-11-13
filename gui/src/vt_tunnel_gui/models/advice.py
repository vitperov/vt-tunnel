"""Suggestion record: the shared currency of the check side.

One suggestion is a frozen piece of advice the check-result dialog
renders: a wrapped paragraph of text plus an optional pasteable
command shown in a copyable command field. Both the ssh login check
and the daemon check produce these.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Suggestion:
    """A frozen suggestion: advice text plus an optional command.

    ``text`` is the advice shown to the user; ``command``, when not
    None, is a shell command the user can paste into a terminal.
    """

    text: str
    command: str | None = None
