import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.controller import Controller
from vt_tunnel_gui.models.model import Model
from vt_tunnel_gui.models.tunnel_config import TunnelConfig
from vt_tunnel_gui.views.connection_view import ConnectionView
from vt_tunnel_gui.views.tray_view import TrayView
from vt_tunnel_gui.views.view import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vt-tunnel-gui",
        description="GUI manager for vt-tunnel settings.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        type=Path,
        default=Path(config_schema.DEFAULT_CONFIG_PATH),
        help="config file to edit, absolute or relative to the current "
        "directory (default: %(default)s)",
    )
    return parser


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
    config_path = args.config.absolute()

    # With a tray, closing the main window only hides it to the tray; the
    # app quits via the tray's Exit. Without one (no tray host running),
    # that would leave an unreachable process, so closing still quits.
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)

    model = Model(TunnelConfig(config_path))
    main_view = MainWindow()
    connection_view = ConnectionView(main_view)
    tray_view = TrayView()
    controller = Controller(
        model, main_view, connection_view, tray_view, app.quit
    )
    controller.show()
    return app.exec()
