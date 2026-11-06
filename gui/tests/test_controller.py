"""Tests of editing connections through the GUI: one file per connection.

Real widgets (offscreen) and real files in a temporary directory; only
the modal dialogs (errors, delete confirmation) are replaced by
recorders.
"""

import os

import pytest

from conftest import OTHER_VALUES, VALID_VALUES, App, conf_text, write_conf


@pytest.fixture
def app(qapp, config_dir, monkeypatch):
    application = App(config_dir)
    view = application.connection_view
    application.errors = []
    application.statuses = []
    application.confirm = True
    monkeypatch.setattr(
        view, "show_error",
        lambda title, text: application.errors.append((title, text)),
    )
    monkeypatch.setattr(view, "show_status", application.statuses.append)
    monkeypatch.setattr(
        view, "confirm_delete", lambda name, path: application.confirm
    )
    application.controller.show()
    yield application
    application.close()


def files(directory):
    return sorted(p.name for p in directory.iterdir())


def names(app):
    return [row.name_label.text() for row in app.main_view.rows]


def set_field(app, key, value):
    app.connection_view._line_edits[key].setText(value)


def open_row(app, row):
    app.main_view.rows[row].edit_button.click()
    assert app.connection_view.isVisible()


@pytest.fixture
def two(config_dir, app):
    write_conf(config_dir, VALID_VALUES)
    write_conf(config_dir, OTHER_VALUES)
    app.controller.reload()
    return app


class TestList:
    def test_rows_are_the_files_by_name(self, two):
        assert names(two) == ["home", "office"]

    def test_opens_the_clicked_connection(self, two):
        open_row(two, 1)
        assert two.connection_view.values()["REMOTE_SERVER"] == (
            "office.example.com"
        )

    def test_opens_by_name_when_files_changed_meanwhile(
        self, two, config_dir
    ):
        # A file sorting before "office" appeared after the list was shown:
        # row 1 still means "office".
        write_conf(config_dir, VALID_VALUES | {"NAME": "aaa"})
        open_row(two, 1)
        assert two.connection_view.values()["NAME"] == "office"

    def test_clicked_file_gone_meanwhile(self, two, config_dir):
        (config_dir / "office.conf").unlink()
        two.main_view.rows[1].edit_button.click()
        assert not two.connection_view.isVisible()
        assert names(two) == ["home"]


class TestNew:
    def test_save_creates_the_file(self, app, config_dir):
        app.main_view.add_button.click()
        app.connection_view.set_values(dict(VALID_VALUES))
        app.connection_view.save_button.click()
        assert files(config_dir) == ["home.conf"]
        assert (config_dir / "home.conf").read_text().endswith(
            conf_text(VALID_VALUES)
        )
        assert names(app) == ["home"]
        assert app.statuses == [f"Saved {config_dir / 'home.conf'}"]

    def test_after_save_it_is_edited_in_place(self, app, config_dir):
        app.main_view.add_button.click()
        app.connection_view.set_values(dict(VALID_VALUES))
        app.connection_view.save_button.click()
        assert app.connection_view.delete_button.isVisibleTo(
            app.connection_view
        )
        set_field(app, "REMOTE_USER", "petya")
        app.connection_view.save_button.click()
        assert files(config_dir) == ["home.conf"]
        assert "REMOTE_USER=petya\n" in (config_dir / "home.conf").read_text()

    def test_taken_name_is_refused(self, two, config_dir):
        before = (config_dir / "home.conf").read_text()
        two.main_view.add_button.click()
        two.connection_view.set_values(VALID_VALUES | {"REMOTE_USER": "x"})
        two.connection_view.save_button.click()
        [(title, text)] = two.errors
        assert "already exists" in text
        assert (config_dir / "home.conf").read_text() == before

    def test_invalid_values_are_refused(self, app, config_dir):
        app.main_view.add_button.click()
        app.connection_view.set_values(VALID_VALUES | {"NAME": "../evil"})
        app.connection_view.save_button.click()
        assert app.errors and files(config_dir) == []


class TestEdit:
    def test_save_updates_only_its_file(self, two, config_dir):
        office = (config_dir / "office.conf").read_text()
        open_row(two, 0)
        set_field(two, "LOCAL_PORT", "2222")
        two.connection_view.save_button.click()
        assert "LOCAL_PORT=2222\n" in (config_dir / "home.conf").read_text()
        assert (config_dir / "office.conf").read_text() == office

    def test_rename_moves_the_file(self, two, config_dir):
        open_row(two, 0)
        set_field(two, "NAME", "nas")
        two.connection_view.save_button.click()
        assert two.errors == []
        assert files(config_dir) == ["nas.conf", "office.conf"]
        assert names(two) == ["nas", "office"]
        # further Saves edit the renamed file
        set_field(two, "REMOTE_USER", "petya")
        two.connection_view.save_button.click()
        assert files(config_dir) == ["nas.conf", "office.conf"]
        assert "REMOTE_USER=petya\n" in (config_dir / "nas.conf").read_text()

    def test_rename_to_a_taken_name_is_refused(self, two, config_dir):
        open_row(two, 0)
        set_field(two, "NAME", "office")
        two.connection_view.save_button.click()
        [(_, text)] = two.errors
        assert "already exists" in text
        assert files(config_dir) == ["home.conf", "office.conf"]

    def test_reset_rereads_the_file(self, two, config_dir):
        open_row(two, 0)
        set_field(two, "REMOTE_USER", "unsaved")
        (config_dir / "home.conf").write_text(
            conf_text(VALID_VALUES | {"REMOTE_USER": "edited-outside"})
        )
        two.connection_view.reset_button.click()
        assert two.connection_view.values()["REMOTE_USER"] == (
            "edited-outside"
        )

    def test_reset_after_file_deleted_outside_gives_new(
        self, two, config_dir
    ):
        open_row(two, 0)
        (config_dir / "home.conf").unlink()
        two.connection_view.reset_button.click()
        assert not two.connection_view.delete_button.isVisibleTo(
            two.connection_view
        )

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_save_without_permission_reports_the_file(self, two, config_dir):
        open_row(two, 0)
        set_field(two, "REMOTE_USER", "petya")
        config_dir.chmod(0o555)
        try:
            two.connection_view.save_button.click()
        finally:
            config_dir.chmod(0o755)
        [(title, text)] = two.errors
        assert title == "Save failed"
        assert str(config_dir) in text
        assert "Permission denied" in text


class TestDelete:
    def test_delete_removes_the_file(self, two, config_dir):
        open_row(two, 0)
        two.connection_view.delete_button.click()
        assert files(config_dir) == ["office.conf"]
        assert names(two) == ["office"]
        assert not two.connection_view.isVisible()

    def test_declined(self, two, config_dir):
        two.confirm = False
        open_row(two, 0)
        two.connection_view.delete_button.click()
        assert files(config_dir) == ["home.conf", "office.conf"]
        assert two.connection_view.isVisible()

    def test_asks_with_the_file(self, two, config_dir, monkeypatch):
        asked = []
        monkeypatch.setattr(
            two.connection_view, "confirm_delete",
            lambda name, path: asked.append((name, path)) or False,
        )
        open_row(two, 1)
        two.connection_view.delete_button.click()
        assert asked == [("office", config_dir / "office.conf")]

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
    def test_without_permission(self, two, config_dir):
        open_row(two, 0)
        config_dir.chmod(0o555)
        try:
            two.connection_view.delete_button.click()
        finally:
            config_dir.chmod(0o755)
        [(title, _)] = two.errors
        assert title == "Delete failed"
        assert files(config_dir) == ["home.conf", "office.conf"]
        assert two.connection_view.isVisible()
