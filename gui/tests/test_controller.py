"""Tests for the controller wiring: the editor dialog widget and the
editing flows through the GUI."""

import os

import pytest
from PyQt6.QtWidgets import QCheckBox, QLabel

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.controller import Controller
from vt_tunnel_gui.models.model import Model
from vt_tunnel_gui.views.connection_view import ConnectionEditor
from vt_tunnel_gui.views.view import ConnectionRow, MainWindow


def _editor():
    """A standalone editor dialog, constructed but not shown."""
    return ConnectionEditor()


# --- The connection editor dialog ---------------------------------------


class TestSchemaForm:
    """The form is generated from the config schema."""

    def test_one_row_per_field_in_schema_order(self, qapp):
        """Every schema field gets exactly one labelled row, in order."""
        editor = _editor()

        assert editor.form_layout.rowCount() == len(config_schema.FIELDS)
        assert list(editor.field_labels) == [
            field.key for field in config_schema.FIELDS
        ]
        for field in config_schema.FIELDS:
            label = editor.field_labels[field.key]
            assert isinstance(label, QLabel)
            assert label.text() == field.key

    def test_placeholders_are_the_schema_examples(self, qapp):
        """Every line edit's placeholder is its field's example value."""
        editor = _editor()

        for field in config_schema.FIELDS:
            if field.key == "ENABLED":
                continue
            assert editor.field_edits[field.key].placeholderText() == (
                field.example
            )

    def test_tooltips_are_the_schema_descriptions(self, qapp):
        """Every input's tooltip is its field's schema description."""
        editor = _editor()

        for field in config_schema.FIELDS:
            if field.key == "ENABLED":
                assert editor.enabled_checkbox.toolTip() == field.description
            else:
                assert editor.field_edits[field.key].toolTip() == (
                    field.description
                )


class TestEnabledCheckbox:
    """ENABLED renders as a checkbox and round-trips true/false."""

    def test_true_round_trips(self, qapp):
        """A "true" value checks the box; the box reads back "true"."""
        editor = _editor()

        editor.set_values({"ENABLED": "true"})

        assert isinstance(editor.enabled_checkbox, QCheckBox)
        assert editor.enabled_checkbox.isChecked()
        assert editor.values()["ENABLED"] == "true"

    def test_false_round_trips(self, qapp):
        """A "false" value leaves the box unchecked; it reads back "false"."""
        editor = _editor()

        editor.set_values({"ENABLED": "false"})

        assert not editor.enabled_checkbox.isChecked()
        assert editor.values()["ENABLED"] == "false"


class TestValuesExchange:
    """Values cross the boundary as raw-string dicts."""

    def test_values_cover_every_schema_key(self, qapp, valid_values):
        """values() returns every schema key with the raw string set."""
        editor = _editor()

        editor.edit_connection(valid_values)

        assert editor.values() == valid_values


class TestTitles:
    """The title switches between new and edit modes."""

    def test_new_mode_title(self, qapp):
        """A new connection is titled "New connection"."""
        editor = _editor()

        editor.edit_new({})

        assert editor.windowTitle() == "New connection"

    def test_edit_mode_title(self, qapp):
        """An unnamed edit is titled "Edit connection"."""
        editor = _editor()

        editor.edit_connection({"NAME": ""})

        assert editor.windowTitle() == "Edit connection"

    def test_edit_mode_title_appends_the_name(self, qapp, valid_values):
        """A named edit is titled "Edit connection: NAME"."""
        editor = _editor()

        editor.edit_connection(valid_values)

        assert editor.windowTitle() == (
            f"Edit connection: {valid_values['NAME']}"
        )

    def test_title_updates_while_typing(self, qapp):
        """Typing a name into a new edit renames the title live."""
        editor = _editor()
        editor.edit_new({})

        editor.field_edits["NAME"].setText("home")

        assert editor.windowTitle() == "New connection"

        editor.edit_connection({"NAME": ""})
        editor.field_edits["NAME"].setText("home")

        assert editor.windowTitle() == "Edit connection: home"


class TestButtons:
    """The button row: Delete far left, Save the only default."""

    def test_delete_hidden_for_new_connection(self, qapp):
        """A new connection has no Delete button."""
        editor = _editor()

        editor.edit_new({})
        editor.show()
        assert not editor.delete_button.isVisible()
        editor.close()

    def test_delete_visible_in_edit_mode(self, qapp):
        """An existing connection can be deleted."""
        editor = _editor()

        editor.edit_connection({"NAME": "home"})
        editor.show()
        assert editor.delete_button.isVisible()
        editor.close()

    def test_save_is_the_default_button(self, qapp):
        """Save takes Enter: it is the dialog's default button."""
        editor = _editor()

        assert editor.save_button.isDefault()
        assert editor.save_button.autoDefault()

    def test_reset_delete_check_never_take_enter(self, qapp):
        """Reset, Delete and Check opt out of auto-default."""
        editor = _editor()

        assert not editor.reset_button.autoDefault()
        assert not editor.delete_button.autoDefault()
        assert not editor.check_button.autoDefault()

    def test_save_emits_and_stays_open(self, qapp):
        """Save emits its request upward and never closes the dialog."""
        editor = _editor()
        editor.show()
        hits = []
        editor.save_requested.connect(lambda: hits.append(1))

        editor.save_button.click()

        assert hits == [1]
        assert editor.isVisible()
        editor.close()


# --- The controller: the editing flows through the GUI -------------------


class EditorSpy:
    """Records the editor's modal feedback calls, standing in for them.

    The controller drives the editor's error boxes and delete
    confirmation; the spy replaces those methods so a test can assert
    on what the controller asked the editor to show without a modal
    box blocking the run. ``delete_answer`` scripts what the
    confirmation replies.
    """

    def __init__(self, editor, monkeypatch):
        self.invalid = []
        self.save_failed = []
        self.delete_asked = []
        self.delete_answer = True
        monkeypatch.setattr(editor, "show_invalid", self._invalid)
        monkeypatch.setattr(editor, "show_save_failed", self._save_failed)
        monkeypatch.setattr(editor, "confirm_delete", self._confirm)

    def _invalid(self, errors):
        self.invalid.append(list(errors))

    def _save_failed(self, path, error):
        self.save_failed.append((path, error))

    def _confirm(self, name, path):
        self.delete_asked.append((name, path))
        return self.delete_answer


def _rows(window):
    """The window's connection rows, in list order."""
    return window.findChildren(ConnectionRow)


def _row_names(window):
    """The names the window's rows currently show."""
    return [row.name_label.text() for row in _rows(window)]


class TestList:
    """The connection list mirrors the directory and opens editors."""

    def test_rows_are_the_files_by_name(
        self, connections_dir, qapp, write_connection_file, valid_values,
        other_valid_values,
    ):
        """Every connection file becomes one row, in list order.

        The composition is built after the files exist, so this is the
        constructor's initial reload filling the list.
        """
        write_connection_file(valid_values)
        write_connection_file(other_valid_values)
        model = Model(str(connections_dir))
        window = MainWindow()
        editor = ConnectionEditor(window)
        Controller(model, window, editor)

        assert _row_names(window) == [
            other_valid_values["NAME"], valid_values["NAME"],
        ]

    def test_opens_the_clicked_connection(
        self, app_composition, write_connection_file, valid_values,
    ):
        """Clicking a row opens that connection's file in the editor."""
        write_connection_file(valid_values)
        composition = app_composition
        composition.controller.reload()

        composition.window.edit_requested.emit(0)

        assert composition.editor.isVisible()
        assert composition.editor.values() == valid_values
        assert composition.editor.delete_button.isVisible()

    def test_opens_by_name_when_files_changed_meanwhile(
        self, app_composition, write_connection_file, valid_values,
    ):
        """The editor shows the file as it is on disk right now."""
        write_connection_file(valid_values)
        composition = app_composition
        changed = dict(valid_values, REMOTE_USER="changed_user")
        write_connection_file(changed)
        composition.controller.reload()

        composition.window.edit_requested.emit(0)

        assert composition.editor.values()["REMOTE_USER"] == "changed_user"

    def test_clicked_file_gone_meanwhile(
        self, app_composition, write_connection_file, valid_values,
    ):
        """A row whose file vanished opens nothing; the list refreshes."""
        path = write_connection_file(valid_values)
        composition = app_composition
        composition.controller.reload()
        path.unlink()

        composition.window.edit_requested.emit(0)

        assert not composition.editor.isVisible()
        assert _rows(composition.window) == []


class TestNewConnection:
    """Add connection: a fresh editor on the schema defaults."""

    def test_save_creates_the_file(
        self, app_composition, write_connection_file, valid_values,
    ):
        """Saving a new connection writes its file."""
        composition = app_composition
        composition.window.add_requested.emit()
        composition.editor.set_values(valid_values)

        composition.editor.save_requested.emit()

        path = composition.directory / f"{valid_values['NAME']}.conf"
        assert path.exists()
        assert "REMOTE_USER=example_user" in path.read_text(encoding="utf-8")
        assert composition.model.find(valid_values["NAME"]) is not None

    def test_after_save_it_is_edited_in_place(
        self, app_composition, valid_values,
    ):
        """A saved connection keeps being edited as itself, not as new."""
        composition = app_composition
        composition.window.add_requested.emit()
        composition.editor.set_values(valid_values)
        composition.editor.save_requested.emit()

        assert composition.editor.windowTitle() == (
            f"Edit connection: {valid_values['NAME']}"
        )
        composition.editor.field_edits["LOCAL_PORT"].setText("8080")
        composition.editor.save_requested.emit()

        files = sorted(p.name for p in composition.directory.iterdir())
        assert files == [f"{valid_values['NAME']}.conf"]
        assert "LOCAL_PORT=8080" in (
            composition.directory / f"{valid_values['NAME']}.conf"
        ).read_text(encoding="utf-8")

    def test_a_taken_name_is_refused(
        self, app_composition, write_connection_file, valid_values,
        other_valid_values, monkeypatch,
    ):
        """Saving under a name that is already a file shows the error."""
        path = write_connection_file(valid_values)
        before = path.read_text(encoding="utf-8")
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.window.add_requested.emit()
        composition.editor.set_values(dict(other_valid_values,
                                           NAME=valid_values["NAME"]))

        composition.editor.save_requested.emit()

        assert len(spy.invalid) == 1
        assert any(
            "already exists" in message for message in spy.invalid[0]
        )
        assert path.read_text(encoding="utf-8") == before

    def test_invalid_values_are_refused(
        self, app_composition, valid_values, monkeypatch,
    ):
        """Values failing validation are shown, nothing is written."""
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.window.add_requested.emit()
        composition.editor.set_values(
            dict(valid_values, REMOTE_USER="-evil")
        )

        composition.editor.save_requested.emit()

        assert len(spy.invalid) == 1
        assert spy.invalid[0][0].startswith("REMOTE_USER:")
        assert not list(composition.directory.iterdir())


class TestEditConnection:
    """Editing an existing connection: save, rename, reset."""

    def test_save_updates_only_its_file(
        self, app_composition, write_connection_file, valid_values,
        other_valid_values,
    ):
        """Saving one connection leaves the other files untouched."""
        write_connection_file(valid_values)
        other_path = write_connection_file(other_valid_values)
        other_before = other_path.read_text(encoding="utf-8")
        composition = app_composition
        composition.controller.reload()
        composition.window.edit_requested.emit(1)
        composition.editor.field_edits["LOCAL_PORT"].setText("8080")

        composition.editor.save_requested.emit()

        home_path = composition.directory / (
            f"{valid_values['NAME']}.conf"
        )
        assert "LOCAL_PORT=8080" in home_path.read_text(encoding="utf-8")
        assert other_path.read_text(encoding="utf-8") == other_before

    def test_rename_moves_the_file(
        self, app_composition, write_connection_file, valid_values,
    ):
        """Saving under a new name moves the connection's file."""
        write_connection_file(valid_values)
        composition = app_composition
        composition.controller.reload()
        composition.window.edit_requested.emit(0)
        composition.editor.field_edits["NAME"].setText("away")

        composition.editor.save_requested.emit()

        assert not (
            composition.directory / f"{valid_values['NAME']}.conf"
        ).exists()
        assert (
            composition.directory / "away.conf"
        ).exists()
        assert composition.editor.windowTitle() == "Edit connection: away"
        assert _row_names(composition.window) == ["away"]

    def test_rename_to_a_taken_name_is_refused(
        self, app_composition, write_connection_file, valid_values,
        other_valid_values, monkeypatch,
    ):
        """A rename onto an existing file shows the error and writes nothing."""
        write_connection_file(valid_values)
        write_connection_file(other_valid_values)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.controller.reload()
        composition.window.edit_requested.emit(1)
        composition.editor.field_edits["NAME"].setText(
            other_valid_values["NAME"]
        )

        composition.editor.save_requested.emit()

        assert len(spy.invalid) == 1
        assert any(
            "already exists" in message for message in spy.invalid[0]
        )
        assert (composition.directory / (
            f"{valid_values['NAME']}.conf"
        )).exists()
        assert (composition.directory / (
            f"{other_valid_values['NAME']}.conf"
        )).exists()

    def test_reset_rereads_the_file(
        self, app_composition, write_connection_file, valid_values,
    ):
        """Reset discards the open edits and refills from the file."""
        write_connection_file(valid_values)
        composition = app_composition
        composition.controller.reload()
        composition.window.edit_requested.emit(0)
        composition.editor.field_edits["REMOTE_USER"].setText("half-typed")

        composition.editor.reset_requested.emit()

        assert composition.editor.values() == valid_values

    def test_reset_after_an_outside_delete_gives_new_connection_defaults(
        self, app_composition, write_connection_file, valid_values,
    ):
        """With the file gone, reset falls back to the schema defaults."""
        path = write_connection_file(valid_values)
        composition = app_composition
        composition.controller.reload()
        composition.window.edit_requested.emit(0)
        path.unlink()

        composition.editor.reset_requested.emit()

        assert composition.editor.windowTitle() == "New connection"
        assert not composition.editor.delete_button.isVisible()
        values = composition.editor.values()
        assert values["REMOTE_SERVER_SSH_PORT"] == "22"
        assert values["REMOTE_USER"] == ""
        assert values["NAME"] == ""

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
    def test_save_without_permission_reports_the_file(
        self, app_composition, write_connection_file, valid_values,
        monkeypatch,
    ):
        """A failed write is reported with the file's path."""
        write_connection_file(valid_values)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.controller.reload()
        composition.window.edit_requested.emit(0)
        composition.directory.chmod(0o500)
        try:
            composition.editor.save_requested.emit()
        finally:
            composition.directory.chmod(0o700)

        assert len(spy.save_failed) == 1
        path, error = spy.save_failed[0]
        assert path.endswith(f"{valid_values['NAME']}.conf")
        assert isinstance(error, PermissionError)


class TestDelete:
    """Deleting an edited connection removes its file."""

    def test_removes_the_file(
        self, app_composition, write_connection_file, valid_values,
        monkeypatch,
    ):
        """A confirmed delete removes the file, closes and reloads."""
        write_connection_file(valid_values)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.controller.reload()
        composition.window.edit_requested.emit(0)

        composition.editor.delete_requested.emit()

        assert not (
            composition.directory / f"{valid_values['NAME']}.conf"
        ).exists()
        assert not composition.editor.isVisible()
        assert _rows(composition.window) == []

    def test_declined(
        self, app_composition, write_connection_file, valid_values,
        monkeypatch,
    ):
        """Answering no to the confirmation deletes nothing."""
        write_connection_file(valid_values)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        spy.delete_answer = False
        composition.controller.reload()
        composition.window.edit_requested.emit(0)

        composition.editor.delete_requested.emit()

        assert (
            composition.directory / f"{valid_values['NAME']}.conf"
        ).exists()
        assert composition.editor.isVisible()

    def test_asks_with_the_file(
        self, app_composition, write_connection_file, valid_values,
        monkeypatch,
    ):
        """The confirmation names the connection and its file."""
        write_connection_file(valid_values)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.controller.reload()
        composition.window.edit_requested.emit(0)

        composition.editor.delete_requested.emit()

        assert len(spy.delete_asked) == 1
        name, path = spy.delete_asked[0]
        assert name == valid_values["NAME"]
        assert path == str(
            composition.directory / f"{valid_values['NAME']}.conf"
        )

    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
    def test_without_permission(
        self, app_composition, write_connection_file, valid_values,
        monkeypatch, controller_boxes,
    ):
        """A delete that cannot remove the file reports it and stays open."""
        write_connection_file(valid_values)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.controller.reload()
        composition.window.edit_requested.emit(0)
        composition.directory.chmod(0o500)
        try:
            composition.editor.delete_requested.emit()
        finally:
            composition.directory.chmod(0o700)

        assert len(controller_boxes.criticals) == 1
        title, text = controller_boxes.criticals[0]
        assert title == "Delete failed"
        assert f"{valid_values['NAME']}.conf" in text
        assert (
            composition.directory / f"{valid_values['NAME']}.conf"
        ).exists()
        assert composition.editor.isVisible()


class TestSshPort:
    """The ssh port flows through the editor and the list."""

    def test_a_new_connection_starts_with_port_22(self, app_composition):
        """The schema default pre-fills a new connection's ssh port."""
        composition = app_composition

        composition.window.add_requested.emit()

        assert (
            composition.editor.values()["REMOTE_SERVER_SSH_PORT"] == "22"
        )

    def test_reset_of_a_new_connection_keeps_the_default(
        self, app_composition,
    ):
        """Resetting an unsaved connection returns to the default port."""
        composition = app_composition
        composition.window.add_requested.emit()
        composition.editor.field_edits["REMOTE_SERVER_SSH_PORT"].setText(
            "2222"
        )

        composition.editor.reset_requested.emit()

        assert (
            composition.editor.values()["REMOTE_SERVER_SSH_PORT"] == "22"
        )

    def test_a_custom_port_is_saved(
        self, app_composition, valid_values,
    ):
        """A changed ssh port reaches the saved file."""
        composition = app_composition
        composition.window.add_requested.emit()
        composition.editor.set_values(
            dict(valid_values, REMOTE_SERVER_SSH_PORT="2222")
        )

        composition.editor.save_requested.emit()

        content = (
            composition.directory / f"{valid_values['NAME']}.conf"
        ).read_text(encoding="utf-8")
        assert "REMOTE_SERVER_SSH_PORT=2222" in content

    def test_a_file_without_the_key_must_get_a_value(
        self, app_composition, write_connection_file, valid_values,
        monkeypatch,
    ):
        """An old file without the ssh port shows it empty and demands it."""
        without_port = {
            key: value for key, value in valid_values.items()
            if key != "REMOTE_SERVER_SSH_PORT"
        }
        write_connection_file(without_port)
        composition = app_composition
        spy = EditorSpy(composition.editor, monkeypatch)
        composition.controller.reload()

        composition.window.edit_requested.emit(0)

        assert composition.editor.values()["REMOTE_SERVER_SSH_PORT"] == ""

        composition.editor.save_requested.emit()

        assert len(spy.invalid) == 1
        assert any(
            message.startswith("REMOTE_SERVER_SSH_PORT:")
            for message in spy.invalid[0]
        )

    def test_the_list_shows_a_non_standard_port(
        self, app_composition, write_connection_file, valid_values,
    ):
        """A row's summary names the ssh port when it is not the default."""
        write_connection_file(
            dict(valid_values, REMOTE_SERVER_SSH_PORT="2222")
        )
        composition = app_composition
        composition.controller.reload()

        summary = _rows(composition.window)[0].summary_label.text()

        assert ":2222" in summary
