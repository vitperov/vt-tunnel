"""Advice shown with a check result: what the user can do next."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Suggestion:
    text: str  # what to do and why, one or two sentences
    command: str = ""  # to paste into a terminal; empty: advice only
