"""Tests of the tray icon and the show/hide/exit wiring in the controller.

Real widgets on Qt's "offscreen" platform: no display needed.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from vt_tunnel_gui.controller import Controller  # noqa: E402
from vt_tunnel_gui.models.model import Model  # noqa: E402
from vt_tunnel_gui.models.tunnel_config import TunnelConfig  # noqa: E402
from vt_tunnel_gui.views import tray_view  # noqa: E402
from vt_tunnel_gui.views.connection_view import ConnectionView  # noqa: E402
from vt_tunnel_gui.views.tray_view import TrayView  # noqa: E402
from vt_tunnel_gui.views.view import MainWindow  # noqa: E402

Reason = QSystemTrayIcon.ActivationReason


@pytest.fixture(scope="module", autouse=True)
def qapp() -> QApplication:
    """Every test here needs one; QPixmap aborts the process without it."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(qapp) -> TrayView:
    return TrayView()


class App:
    """The composition of app.main(), with quit recorded instead of run."""

    def __init__(self, cfg_path) -> None:
        self.quit_calls = 0
        self.main_view = MainWindow()
        self.connection_view = ConnectionView(self.main_view)
        self.tray = TrayView()
        self.controller = Controller(
            Model(TunnelConfig(cfg_path)),
            self.main_view,
            self.connection_view,
            self.tray,
            self._quit,
        )

    def _quit(self) -> None:
        self.quit_calls += 1

    def close(self) -> None:
        self.tray.hide()
        self.connection_view.hide()
        self.main_view.hide()


@pytest.fixture
def app(qapp, cfg_path):
    application = App(cfg_path)
    application.controller.show()
    yield application
    application.close()


class TestTrayView:
    def test_icon_is_loaded(self):
        icon = tray_view.load_icon()
        assert not icon.isNull()

    def test_tray_has_the_icon(self, tray):
        assert not tray.icon().isNull()

    def test_menu(self, tray):
        texts = [a.text() for a in tray.contextMenu().actions()]
        assert texts == ["Show", "", "Exit"]

    def test_label_follows_window_visibility(self, tray):
        tray.set_window_visible(True)
        assert tray.show_hide_action.text() == "Hide"
        tray.set_window_visible(False)
        assert tray.show_hide_action.text() == "Show"

    def test_show_hide_action_emits(self, tray):
        calls = []
        tray.show_hide_requested.connect(lambda: calls.append(1))
        tray.show_hide_action.trigger()
        assert calls == [1]

    def test_exit_action_emits(self, tray):
        calls = []
        tray.exit_requested.connect(lambda: calls.append(1))
        tray.exit_action.trigger()
        assert calls == [1]

    def test_click_on_icon_toggles(self, tray):
        calls = []
        tray.show_hide_requested.connect(lambda: calls.append(1))
        tray.activated.emit(Reason.Trigger)
        assert calls == [1]

    @pytest.mark.parametrize("reason", [Reason.Context, Reason.MiddleClick])
    def test_other_activations_do_not_toggle(self, tray, reason):
        calls = []
        tray.show_hide_requested.connect(lambda: calls.append(1))
        tray.activated.emit(reason)
        assert calls == []


class TestShowHide:
    def test_starts_shown_with_tray(self, app):
        assert app.main_view.isVisible()
        assert app.tray.isVisible()
        assert app.tray.show_hide_action.text() == "Hide"

    def test_hide_then_show(self, app):
        app.tray.show_hide_action.trigger()
        assert not app.main_view.isVisible()
        assert app.tray.show_hide_action.text() == "Show"

        app.tray.show_hide_action.trigger()
        assert app.main_view.isVisible()
        assert app.tray.show_hide_action.text() == "Hide"

    def test_closing_the_window_updates_label(self, app):
        app.main_view.close()
        assert not app.main_view.isVisible()
        assert app.tray.show_hide_action.text() == "Show"

    def test_show_restores_minimized_window(self, app):
        app.main_view.showMinimized()
        app.main_view.hide()
        app.tray.show_hide_action.trigger()
        assert app.main_view.isVisible()
        assert not app.main_view.isMinimized()

    def test_editor_hides_and_returns_with_its_edits(self, app):
        app.main_view.add_requested.emit()
        app.connection_view._line_edits["NAME"].setText("unsaved")

        app.tray.show_hide_action.trigger()
        assert not app.connection_view.isVisible()

        app.tray.show_hide_action.trigger()
        assert app.connection_view.isVisible()
        assert app.connection_view.values()["NAME"] == "unsaved"

    def test_closing_the_window_hides_the_editor(self, app):
        app.main_view.add_requested.emit()
        app.main_view.close()
        assert not app.connection_view.isVisible()

    def test_closed_editor_stays_closed(self, app):
        app.main_view.add_requested.emit()
        app.connection_view.reject()
        app.tray.show_hide_action.trigger()
        app.tray.show_hide_action.trigger()
        assert not app.connection_view.isVisible()


class TestExit:
    def test_exit_quits(self, app):
        app.tray.exit_action.trigger()
        assert app.quit_calls == 1
        assert not app.tray.isVisible()

    def test_exit_from_hidden_window(self, app):
        app.tray.show_hide_action.trigger()
        app.tray.exit_action.trigger()
        assert app.quit_calls == 1
