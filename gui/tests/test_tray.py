"""Tests of the tray icon and the show/hide/exit wiring in the controller.

Real widgets on Qt's "offscreen" platform (see conftest): no display.
"""

import pytest
from PyQt6.QtWidgets import QSystemTrayIcon

from conftest import App
from vt_tunnel_gui.views import tray_view
from vt_tunnel_gui.views.tray_view import TrayView

Reason = QSystemTrayIcon.ActivationReason


@pytest.fixture(autouse=True)
def _qapp(qapp):
    """Every test here needs the QApplication."""


@pytest.fixture
def tray(qapp) -> TrayView:
    return TrayView()


@pytest.fixture
def app(qapp, config_dir):
    application = App(config_dir)
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
