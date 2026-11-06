import argparse
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.controller import Controller
from vt_tunnel_gui.models.connections_dir import ConnectionsDir
from vt_tunnel_gui.models.model import Model
from vt_tunnel_gui.views import startup_view
from vt_tunnel_gui.views.connection_view import ConnectionView
from vt_tunnel_gui.views.tray_view import TrayView
from vt_tunnel_gui.views.view import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vt-tunnel-gui",
        description="GUI manager for vt-tunnel settings.",
        # No prefixes: the old "--config FILE" must not pass for
        # "--config-dir".
        allow_abbrev=False,
    )
    parser.add_argument(
        "--config-dir",
        metavar="DIR",
        type=Path,
        default=Path(config_schema.DEFAULT_CONFIG_DIR),
        help="directory of the connection files (<name>.conf) to edit, "
        "absolute or relative to the current directory "
        "(default: %(default)s)",
    )
    return parser


def ensure_config_dir(
    store: ConnectionsDir,
    ask_create: Callable[[Path], bool],
    report: Callable[[str], None],
) -> bool:
    """Make sure the config directory exists; True if the app can run.

    A missing directory is created if ``ask_create`` allows it; every
    reason not to run is given to ``report`` (except the user's "no").
    """
    path = store.path
    if store.is_dir():
        return True
    if store.exists():  # a file, or a symlink to one
        report(f"{path} is not a directory.")
        return False
    if not ask_create(path):
        return False
    try:
        store.create()
    except OSError as err:
        report(
            f"Can't create {path}:\n{err.strerror or err}\n\n"
            "Create it as root, then start vt-tunnel-gui again:\n"
            f"sudo mkdir -p {shlex.quote(str(path))}"
        )
        return False
    return True


def main() -> int:
    """Composition root: build the model, view and controller, then run."""
    # Parse our options before Qt starts, so --help and usage errors work
    # without a display. Anything we don't know goes to Qt (-platform,
    # -style, ...); whatever Qt doesn't consume either is an error.
    parser = build_parser()
    args, rest = parser.parse_known_args(sys.argv[1:])
    app = QApplication(sys.argv[:1] + rest)
    unknown = app.arguments()[1:]
    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    # Resolve a relative path once, against the startup working directory.
    store = ConnectionsDir(args.config_dir.absolute())
    if not ensure_config_dir(
        store,
        startup_view.ask_create_config_dir,
        startup_view.show_startup_error,
    ):
        return 1

    # With a tray, closing the main window only hides it to the tray; the
    # app quits via the tray's Exit. Without one (no tray host running),
    # that would leave an unreachable process, so closing still quits.
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)

    model = Model(store)
    main_view = MainWindow()
    connection_view = ConnectionView(main_view)
    tray_view = TrayView()
    controller = Controller(
        model, main_view, connection_view, tray_view, app.quit
    )
    controller.show()
    return app.exec()
