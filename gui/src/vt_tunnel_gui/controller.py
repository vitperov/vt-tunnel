"""The controller: the only decision-maker in the GUI.

Connects every view signal to a model operation and a view update,
enforces the reload discipline — the connection list is re-read from
disk at startup, before any editor opens, and after every save, delete
and reset, so the list always reflects disk just before any editing
decision — and runs the two blocking checks synchronously with busy
indicators. It holds no model state beyond the saved name of the
connection being edited (nothing for a new connection) and never
touches files directly, only through the model.
"""

from PyQt6.QtWidgets import QMessageBox

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models import daemon_check
from vt_tunnel_gui.models import ssh_check
from vt_tunnel_gui.models import ssh_keys
from vt_tunnel_gui.models.model import Connection, ValidationError
from vt_tunnel_gui.views import check_result_view

# The only fields the ssh login check consumes: they become ssh
# arguments, so a value starting with a dash would be read as an
# option — they are validated (and only they) before the check runs.
_SSH_CHECK_FIELDS = ("REMOTE_USER", "REMOTE_SERVER", "REMOTE_SERVER_SSH_PORT")


def _default_values():
    """Raw values for a fresh connection: the schema defaults."""
    return {field.key: field.default for field in config_schema.FIELDS}


class Controller:
    """Wires the model, the main window and the editor together."""

    def __init__(self, model, main_window, editor) -> None:
        self._model = model
        self._window = main_window
        self._editor = editor
        # The name the edited connection is saved under; None = new.
        self._saved_name = None

        self._window.edit_requested.connect(self._row_activated)
        self._window.check_requested.connect(self._check_daemon)
        self._window.add_requested.connect(self._add_connection)
        self._editor.save_requested.connect(self._save)
        self._editor.reset_requested.connect(self._reset)
        self._editor.delete_requested.connect(self._delete)
        self._editor.check_requested.connect(self._check_connection)

        self.reload()

    # --- reload discipline ---------------------------------------------

    def reload(self):
        """Re-read the directory and rebuild the main window's rows.

        The single refresh method: it runs at startup, before any
        editor opens, and after every save, delete and reset, so the
        list always reflects disk just before any editing decision.
        """
        self._model.load()
        self._window.set_connections(
            [connection.values() for connection in self._model.connections]
        )

    # --- opening the editor ---------------------------------------------

    def _row_activated(self, row):
        """A row was clicked (or its Edit button pressed)."""
        if self._editor.isVisible():
            # Already open: bring it to front, keep its open edits.
            self._editor.open_editor()
            return
        loaded = self._model.connections
        if not 0 <= row < len(loaded):
            return
        name = loaded[row].name
        self.reload()
        connection = self._model.find(name)
        if connection is None:
            # The clicked file is gone meanwhile; the reload above has
            # already dropped its row.
            return
        self._saved_name = connection.name
        self._editor.edit_connection(connection.values())
        self._editor.open_editor()

    def _add_connection(self):
        """The Add connection button was pressed."""
        if self._editor.isVisible():
            self._editor.open_editor()
            return
        self.reload()
        self._saved_name = None
        self._editor.edit_new(_default_values())
        self._editor.open_editor()

    # --- editor flows -----------------------------------------------------

    def _save(self):
        """The editor's Save button: validate, write, re-enter edit mode."""
        connection = Connection(self._editor.values())
        try:
            self._model.save(connection, saved_name=self._saved_name)
        except ValidationError as error:
            self._editor.show_invalid(error.errors)
            return
        except OSError as error:
            self._editor.show_save_failed(
                self._model.connection_path(connection.name), error
            )
            return
        # Subsequent saves target the new file: a changed NAME field and
        # another save performs a rename because the model is told the
        # previously saved name.
        self._saved_name = connection.name
        self.reload()
        self._editor.edit_connection(self._editor.values())
        self._editor.show_saved(self._model.connection_path(connection.name))

    def _reset(self):
        """The editor's Reset button: refill from disk, or from defaults."""
        self.reload()
        connection = None
        if self._saved_name is not None:
            connection = self._model.find(self._saved_name)
        if connection is None:
            # The file is gone (or the connection was never saved):
            # start over as a new connection on the schema defaults.
            self._saved_name = None
            self._editor.edit_new(_default_values())
        else:
            self._editor.edit_connection(connection.values())

    def _delete(self):
        """The editor's Delete button: confirm, delete, close, reload."""
        if self._saved_name is None:
            return
        name = self._saved_name
        path = self._model.connection_path(name)
        if not self._editor.confirm_delete(name, path):
            return
        try:
            self._model.delete(name)
        except OSError as error:
            QMessageBox.critical(
                self._window,
                "Delete failed",
                f"Could not delete {path}:\n{error}",
            )
            return
        self._editor.close()
        self._saved_name = None
        self.reload()

    # --- the blocking checks ---------------------------------------------

    def _check_daemon(self, row):
        """A row's Check daemon button: check that connection's service."""
        loaded = self._model.connections
        if not 0 <= row < len(loaded):
            return
        name = loaded[row].name
        self._window.set_checking(row, True)
        try:
            result = daemon_check.check(name)
        finally:
            self._window.set_checking(row, False)
        check_result_view.show_daemon_result(result, parent=self._window)

    def _check_connection(self):
        """The editor's Check connection button: try the ssh login."""
        values = self._editor.values()
        connection = Connection(values)
        errors = connection.validate(keys=_SSH_CHECK_FIELDS)
        if errors:
            # Those values become ssh arguments; a value starting with
            # a dash would be read as an option, so the check refuses.
            QMessageBox.critical(
                self._editor,
                "Can't check the connection",
                "\n".join(errors),
            )
            return
        note = ssh_keys.mismatch_warning(values["RUN_DAEMON_USER"])
        self._editor.set_busy(ssh_check.DEFAULT_TIMEOUT)
        try:
            result = ssh_check.check_login(
                values["REMOTE_USER"],
                values["REMOTE_SERVER"],
                values["REMOTE_SERVER_SSH_PORT"],
            )
        finally:
            self._editor.set_idle()
        check_result_view.show_ssh_result(result, note=note, parent=self._editor)
