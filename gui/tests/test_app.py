"""Tests for the app startup: the CLI options, the directory gate and
the composition in main()."""

import os
import shlex

import pytest

import vt_tunnel_gui.app as app_module
import vt_tunnel_gui.views.startup_view as startup_view
from vt_tunnel_gui import config_schema
from vt_tunnel_gui.views.view import MainWindow


class _FakeQtApp:
    """Stands in for the app module's QApplication.

    Records the argv it was constructed with (arguments() reads it
    back) and scripts exec() to return immediately, so a main() run
    never enters a real event loop.
    """

    last = None

    def __init__(self, argv):
        self.argv = list(argv)
        self.exec_called = False
        self.exec_result = 0
        _FakeQtApp.last = self

    def arguments(self):
        return list(self.argv)

    def exec(self):
        self.exec_called = True
        return self.exec_result


@pytest.fixture
def fake_qt_app(monkeypatch):
    """Replace the app module's QApplication with the recording fake."""
    _FakeQtApp.last = None
    monkeypatch.setattr(app_module, "QApplication", _FakeQtApp)
    return _FakeQtApp


@pytest.fixture
def startup_dialogs(monkeypatch):
    """Record the gate's dialogs instead of showing them.

    ``criticals`` collects every critical-dialog message;
    ``questions`` collects every yes/no question; ``answer`` scripts
    the yes/no reply (default True = yes).
    """
    recorded = type(
        "StartupDialogs", (), {"criticals": [], "questions": [], "answer": True}
    )()
    monkeypatch.setattr(startup_view, "show_critical", recorded.criticals.append)

    def ask(message):
        recorded.questions.append(message)
        return recorded.answer

    monkeypatch.setattr(startup_view, "ask_create", ask)
    return recorded


# --- The gate -------------------------------------------------------------


class TestGate:
    """The startup gate over the connections directory."""

    def test_existing_directory_proceeds(self, connections_dir, startup_dialogs):
        """A directory is passed without any dialog."""
        assert app_module.ensure_directory(str(connections_dir)) is True
        assert startup_dialogs.criticals == []
        assert startup_dialogs.questions == []

    def test_missing_asks_and_creates(self, tmp_path, startup_dialogs):
        """A missing directory is offered, created with parents on yes."""
        directory = tmp_path / "deep" / "connections.d"

        assert app_module.ensure_directory(str(directory)) is True

        assert directory.is_dir()
        assert len(startup_dialogs.questions) == 1
        assert startup_dialogs.criticals == []

    def test_missing_and_declined(self, tmp_path, startup_dialogs):
        """Declining the offer creates nothing."""
        startup_dialogs.answer = False
        directory = tmp_path / "connections.d"

        assert app_module.ensure_directory(str(directory)) is False

        assert not directory.exists()
        assert len(startup_dialogs.questions) == 1
        assert startup_dialogs.criticals == []

    def test_not_a_directory(self, tmp_path, startup_dialogs):
        """A path that exists but is a file is refused with a critical."""
        path = tmp_path / "afile"
        path.write_text("x")

        assert app_module.ensure_directory(str(path)) is False

        assert len(startup_dialogs.criticals) == 1
        assert startup_dialogs.questions == []

    def test_symlink_to_a_directory_proceeds(self, tmp_path, startup_dialogs):
        """A symlink pointing at a directory counts as a directory."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        assert app_module.ensure_directory(str(link)) is True

        assert startup_dialogs.questions == []
        assert startup_dialogs.criticals == []

    def test_broken_symlink_cannot_be_created(self, tmp_path, startup_dialogs):
        """A broken symlink is missing, and creating over it fails."""
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "gone")  # target never exists: broken

        assert app_module.ensure_directory(str(link)) is False

        # It asked (missing), the creation failed, and the critical
        # dialog suggests the shell-quoted sudo mkdir command.
        assert len(startup_dialogs.questions) == 1
        assert len(startup_dialogs.criticals) == 1
        assert f"sudo mkdir -p {shlex.quote(str(link))}" in (
            startup_dialogs.criticals[0]
        )
        assert link.is_symlink() and not link.is_dir()

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
    def test_creation_fails(self, tmp_path, startup_dialogs):
        """A failed creation (no permission) is refused with the hint."""
        parent = tmp_path / "locked"
        parent.mkdir()
        parent.chmod(0o555)
        directory = parent / "connections.d"
        try:
            assert app_module.ensure_directory(str(directory)) is False

            assert not directory.exists()
            assert len(startup_dialogs.criticals) == 1
            assert f"sudo mkdir -p {shlex.quote(str(directory))}" in (
                startup_dialogs.criticals[0]
            )
        finally:
            parent.chmod(0o755)


# --- The options -----------------------------------------------------------


class TestOptions:
    """The single config-directory option."""

    def test_default_is_the_system_directory(self):
        """Without the option, the system connections directory is used."""
        options, leftovers = app_module._build_parser().parse_known_args([])

        assert options.config_dir == config_schema.DEFAULT_CONFIG_DIR
        assert leftovers == []

    def test_the_config_dir_override(self):
        """--config-dir DIR overrides the directory."""
        options, leftovers = app_module._build_parser().parse_known_args(
            ["--config-dir", "/tmp/other"]
        )

        assert options.config_dir == "/tmp/other"
        assert leftovers == []

    def test_the_old_config_option_is_gone(self, fake_qt_app):
        """--config FILE is not accepted: abbreviation is disabled, so it
        falls through to Qt, which does not recognize it either — a
        parser error."""
        with pytest.raises(SystemExit) as excinfo:
            app_module.main(["vt-tunnel-gui", "--config", "/etc/vt-tunnel.cfg"])

        assert excinfo.value.code == 2
        assert "--config" in fake_qt_app.last.argv


# --- main -------------------------------------------------------------------


class TestMain:
    """The startup flow through main()."""

    def test_declined_exits_without_creating(
        self, tmp_path, startup_dialogs, fake_qt_app, monkeypatch
    ):
        """A declined gate exits 1: nothing created, no window, no loop."""

        class NoWindow:
            def __init__(self, *args):
                raise AssertionError("main window built despite a declined gate")

        monkeypatch.setattr(app_module, "MainWindow", NoWindow)
        directory = tmp_path / "connections.d"
        startup_dialogs.answer = False

        assert app_module.main(["vt-tunnel-gui", "--config-dir", str(directory)]) == 1

        assert not directory.exists()
        assert fake_qt_app.last.exec_called is False

    def test_accepted_creates_and_runs(
        self, tmp_path, startup_dialogs, fake_qt_app, monkeypatch, qapp
    ):
        """An accepted gate creates the directory, shows and runs."""
        shown = []

        class SpyMainWindow(MainWindow):
            def show(self):
                shown.append(self)
                super().show()

        monkeypatch.setattr(app_module, "MainWindow", SpyMainWindow)
        directory = tmp_path / "connections.d"

        assert app_module.main(["vt-tunnel-gui", "--config-dir", str(directory)]) == 0

        assert directory.is_dir()
        assert len(shown) == 1
        assert fake_qt_app.last.exec_called is True

    def test_existing_directory_runs_without_asking(
        self, connections_dir, startup_dialogs, fake_qt_app, qapp
    ):
        """An existing directory runs the loop without any question."""
        assert (
            app_module.main(["vt-tunnel-gui", "--config-dir", str(connections_dir)])
            == 0
        )

        assert startup_dialogs.questions == []
        assert startup_dialogs.criticals == []
        assert fake_qt_app.last.exec_called is True

    def test_a_relative_path_is_taken_from_the_working_directory(
        self, tmp_path, startup_dialogs, fake_qt_app, monkeypatch, qapp
    ):
        """A relative --config-dir resolves against the startup cwd."""
        base = tmp_path / "startup-cwd"
        base.mkdir()
        monkeypatch.chdir(base)

        assert app_module.main(["vt-tunnel-gui", "--config-dir", "conns"]) == 0

        assert (base / "conns").is_dir()

    def test_not_a_directory_reports_and_exits(
        self, tmp_path, startup_dialogs, fake_qt_app, qapp
    ):
        """A file where the directory should be: critical, exit 1, no loop."""
        path = tmp_path / "afile"
        path.write_text("not a directory")

        assert app_module.main(["vt-tunnel-gui", "--config-dir", str(path)]) == 1

        assert len(startup_dialogs.criticals) == 1
        assert fake_qt_app.last.exec_called is False

    def test_help_needs_no_display(self, fake_qt_app, capsys):
        """--help prints the usage and exits 0 before any Qt object."""
        with pytest.raises(SystemExit) as excinfo:
            app_module.main(["vt-tunnel-gui", "--help"])

        assert excinfo.value.code == 0
        assert fake_qt_app.last is None
        assert "--config-dir" in capsys.readouterr().out
