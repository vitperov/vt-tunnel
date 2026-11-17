"""Composition root: the command line, the directory gate, the wiring.

The command line is parsed before Qt exists, so ``--help`` and usage
errors work without a display. The gate then makes sure the connections
directory is usable — asking before creating a missing one, refusing a
path that is not a directory — before the model, the two windows and
the controller are built and the event loop starts. There is no splash
screen: the gate's dialogs are the parentless helpers of
``startup_view``, shown and dismissed while the gate runs, and a fatal
answer exits before anything else is built.
"""

import argparse
import os
import shlex
import sys

from PyQt6.QtWidgets import QApplication

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.controller import Controller
from vt_tunnel_gui.models.connections_dir import ConnectionsDir
from vt_tunnel_gui.models.model import Model
from vt_tunnel_gui.views import startup_view
from vt_tunnel_gui.views.connection_view import ConnectionEditor
from vt_tunnel_gui.views.view import MainWindow


def _build_parser():
    """The command-line parser: one option, the config-directory override.

    Abbreviations are disabled, so a legacy-looking ``--config FILE``
    cannot be mistyped as accepted — it is simply an unknown argument.
    """
    parser = argparse.ArgumentParser(
        prog="vt-tunnel-gui",
        description="GUI manager for vt-tunnel connections.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--config-dir",
        metavar="DIR",
        default=config_schema.DEFAULT_CONFIG_DIR,
        help="Connections directory to manage (default: %(default)s).",
    )
    return parser


def ensure_directory(directory):
    """The startup gate: make sure the connections directory is usable.

    A directory — a symlink to one included — proceeds. A path that
    exists but is not a directory is refused. A missing path (a broken
    symlink counts as missing: it cannot be followed) is offered for
    creation, and on yes it is created with parents; a failed creation
    is refused with a ``sudo mkdir -p`` hint. Every refusal shows a
    critical dialog and returns False; the caller then exits with
    status 1, before any model, view or controller exists.
    """
    store = ConnectionsDir(directory)
    if store.is_directory():
        return True
    if store.exists():
        startup_view.show_critical(
            f"{directory} exists but is not a directory.\n\n"
            "vt-tunnel manages one directory of per-connection files; "
            "choose another directory with --config-dir."
        )
        return False
    if not startup_view.ask_create(
        f"The connections directory {directory} does not exist.\n\n"
        "Create it?"
    ):
        return False
    try:
        store.create()
    except OSError as error:
        startup_view.show_critical(
            f"Could not create {directory}:\n{error}\n\n"
            "Create it as root, e.g. with:\n"
            f"    sudo mkdir -p {shlex.quote(directory)}"
        )
        return False
    return True


def main(argv=None) -> int:
    """Run the GUI: parse the command line, gate the directory, wire up.

    Returns the exit status: 1 when the gate refuses, otherwise the
    event loop's exit code. ``--help`` and usage errors exit through
    the parser (before any Qt object exists).
    """
    if argv is None:
        argv = sys.argv
    parser = _build_parser()
    options, leftovers = parser.parse_known_args(argv[1:])

    # Resolved once, against the startup working directory; the gate,
    # the model and every message use this resolved path.
    directory = os.path.abspath(options.config_dir)

    app = QApplication([argv[0], *leftovers])
    unknown = app.arguments()[1:]
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    if not ensure_directory(directory):
        return 1

    model = Model(directory)
    window = MainWindow()
    editor = ConnectionEditor(window)
    # The controller is a plain Python object: PyQt holds signal
    # connections to it only while it is referenced, so this reference
    # must outlive the wiring — it lives for the event loop's lifetime.
    controller = Controller(model, window, editor)

    window.show()
    return app.exec()
