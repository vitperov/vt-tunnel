"""Tests of the app's startup: --config-dir and the directory check."""

import os
import subprocess
import sys
import textwrap

import pytest

from vt_tunnel_gui import app, config_schema
from vt_tunnel_gui.models.connections_dir import ConnectionsDir


class Dialogs:
    """Records the startup dialogs; ``answer`` is the user's reply."""

    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.asked = []
        self.reported = []

    def ask(self, path):
        self.asked.append(path)
        return self.answer

    def report(self, text):
        self.reported.append(text)


def ensure(path, answer=True):
    dialogs = Dialogs(answer)
    ok = app.ensure_config_dir(ConnectionsDir(path), dialogs.ask,
                               dialogs.report)
    return ok, dialogs


class TestEnsureConfigDir:
    def test_existing_directory(self, config_dir):
        ok, dialogs = ensure(config_dir)
        assert ok
        assert dialogs.asked == [] and dialogs.reported == []

    def test_missing_asks_and_creates(self, tmp_path):
        path = tmp_path / "etc" / "vt-tunnel" / "connections.d"
        ok, dialogs = ensure(path, answer=True)
        assert ok
        assert dialogs.asked == [path]
        assert path.is_dir()

    def test_missing_and_declined(self, tmp_path):
        path = tmp_path / "connections.d"
        ok, dialogs = ensure(path, answer=False)
        assert not ok
        assert dialogs.reported == []  # the user said no: nothing to add
        assert not path.exists()

    def test_not_a_directory(self, tmp_path):
        path = tmp_path / "connections.d"
        path.write_text("")
        ok, dialogs = ensure(path)
        assert not ok
        assert dialogs.asked == []
        [text] = dialogs.reported
        assert "not a directory" in text

    def test_symlink_to_a_directory(self, tmp_path, config_dir):
        link = tmp_path / "link"
        link.symlink_to(config_dir)
        assert ensure(link)[0]

    def test_broken_symlink_cannot_be_created(self, tmp_path):
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "nowhere")
        ok, dialogs = ensure(link)
        assert not ok
        [text] = dialogs.reported
        assert f"Can't create {link}" in text

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_creation_fails(self, tmp_path):
        parent = tmp_path / "etc"
        parent.mkdir(mode=0o555)
        path = parent / "vt-tunnel" / "connections.d"
        try:
            ok, dialogs = ensure(path)
        finally:
            parent.chmod(0o755)
        assert not ok
        [text] = dialogs.reported
        assert "Permission denied" in text
        assert f"sudo mkdir -p {path}" in text


class TestOptions:
    def test_default_is_the_system_directory(self):
        args = app.build_parser().parse_args([])
        assert str(args.config_dir) == config_schema.DEFAULT_CONFIG_DIR
        assert config_schema.DEFAULT_CONFIG_DIR == (
            "/etc/vt-tunnel/connections.d"
        )

    def test_config_dir(self):
        args = app.build_parser().parse_args(["--config-dir", "some/dir"])
        assert str(args.config_dir) == "some/dir"

    def test_old_config_option_is_gone(self):
        with pytest.raises(SystemExit):
            app.build_parser().parse_args(["--config", "x.cfg"])


# --------------------------------------------------------------------------
# main(), in a subprocess: the question is answered by a stub
# --------------------------------------------------------------------------

RUN_MAIN = textwrap.dedent("""\
    import sys
    from PyQt6.QtWidgets import QApplication
    from vt_tunnel_gui.views import startup_view

    answer = sys.argv.pop(1) == "yes"
    def ask(path):
        print("ASKED", path, flush=True)
        return answer
    startup_view.ask_create_config_dir = ask
    startup_view.show_startup_error = lambda text: print("ERROR", text)
    # Don't run the event loop: report that the main window was built.
    def exec_():
        print("RUNNING", flush=True)
        return 0
    QApplication.exec = staticmethod(exec_)

    from vt_tunnel_gui.app import main
    sys.exit(main())
""")


def run_main(answer, *args, cwd=None):
    env = os.environ | {"QT_QPA_PLATFORM": "offscreen"}
    return subprocess.run(
        [sys.executable, "-c", RUN_MAIN, answer, *args],
        capture_output=True, text=True, timeout=60, env=env, cwd=cwd,
    )


class TestMain:
    def test_declined_exits_without_creating(self, tmp_path):
        path = tmp_path / "connections.d"
        done = run_main("no", "--config-dir", str(path))
        assert done.returncode == 1
        assert f"ASKED {path}" in done.stdout
        assert "RUNNING" not in done.stdout
        assert not path.exists()

    def test_accepted_creates_and_runs(self, tmp_path):
        path = tmp_path / "connections.d"
        done = run_main("yes", "--config-dir", str(path))
        assert done.returncode == 0, done.stderr
        assert "RUNNING" in done.stdout
        assert path.is_dir()

    def test_existing_directory_runs_without_asking(self, config_dir):
        done = run_main("no", "--config-dir", str(config_dir))
        assert done.returncode == 0, done.stderr
        assert "ASKED" not in done.stdout
        assert "RUNNING" in done.stdout

    def test_relative_path_is_from_the_working_directory(self, tmp_path):
        done = run_main("yes", "--config-dir", "rel/dir", cwd=tmp_path)
        assert done.returncode == 0, done.stderr
        assert f"ASKED {tmp_path / 'rel' / 'dir'}" in done.stdout
        assert (tmp_path / "rel" / "dir").is_dir()

    def test_not_a_directory_reports_and_exits(self, tmp_path):
        path = tmp_path / "file"
        path.write_text("")
        done = run_main("yes", "--config-dir", str(path))
        assert done.returncode == 1
        assert "ERROR" in done.stdout and "not a directory" in done.stdout

    def test_help_needs_no_display(self):
        done = subprocess.run(
            [sys.executable, "-m", "vt_tunnel_gui", "--help"],
            capture_output=True, text=True, timeout=60,
            env=os.environ | {"QT_QPA_PLATFORM": "no-such-platform"},
        )
        assert done.returncode == 0
        assert "--config-dir" in done.stdout
        assert "--config " not in done.stdout
