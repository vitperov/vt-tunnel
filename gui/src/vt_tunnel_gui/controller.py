"""Controller wiring the model and the views."""

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.models import daemon_check, ssh_check, ssh_keys
from vt_tunnel_gui.models.connection import Connection
from vt_tunnel_gui.models.model import ValidationError

# The form fields the connection check uses.
CHECK_KEYS = (
    config_schema.REMOTE_USER.key,
    config_schema.REMOTE_SERVER.key,
    config_schema.REMOTE_SERVER_SSH_PORT.key,
)


def new_connection() -> Connection:
    """A connection not saved yet: the schema's defaults (e.g. port 22)."""
    return Connection(config_schema.DEFAULT_VALUES)


class Controller:
    """Coordinates the model, the connection list, the editor window and
    the tray icon.

    Remembers the name the edited connection is saved under (``None`` for
    a connection that isn't saved yet): each connection is its own file,
    so Save writes (or renames) just that one, Delete removes it.

    Hiding the main window (from the tray, or by closing it) hides an open
    editor with it; showing the main window brings the editor back, with
    its edits intact.
    """

    def __init__(
        self, model, main_view, connection_view, tray_view, quit_app
    ) -> None:
        self.model = model
        self.main_view = main_view
        self.connection_view = connection_view
        self.tray_view = tray_view
        self._quit_app = quit_app
        self._editing: str | None = None  # saved name of the edited one
        # The editor was open when the main window got hidden.
        self._editor_hidden = False

        self.main_view.connection_activated.connect(
            self.on_connection_activated
        )
        self.main_view.add_requested.connect(self.on_add_requested)
        self.main_view.daemon_check_requested.connect(self.on_daemon_check)
        self.main_view.visibility_changed.connect(
            self.on_main_visibility_changed
        )
        self.connection_view.save_requested.connect(self.on_save)
        self.connection_view.reset_requested.connect(self.on_reset)
        self.connection_view.delete_requested.connect(self.on_delete)
        self.connection_view.check_requested.connect(self.on_check)
        self.tray_view.show_hide_requested.connect(self.on_show_hide_requested)
        self.tray_view.exit_requested.connect(self.on_exit_requested)

        self.reload()

    def show(self) -> None:
        """Show the tray icon and the main window."""
        self.tray_view.show()
        self.show_main_window()

    def show_main_window(self) -> None:
        """Bring the main window (and an editor hidden with it) to front."""
        self.main_view.bring_to_front()
        if self._editor_hidden:
            self._editor_hidden = False
            self.connection_view.open_editor()

    def hide_main_window(self) -> None:
        self.main_view.hide()

    # ------------------------------------------------------------ tray

    def on_show_hide_requested(self) -> None:
        if self.main_view.isVisible():
            self.hide_main_window()
        else:
            self.show_main_window()

    def on_exit_requested(self) -> None:
        self.tray_view.hide()
        self._quit_app()

    def on_main_visibility_changed(self, visible: bool) -> None:
        """Keep the tray label in sync; hide the editor with the window."""
        self.tray_view.set_window_visible(visible)
        if not visible and self.connection_view.isVisible():
            self._editor_hidden = True
            self.connection_view.hide()  # hide(), not close: keep the edits

    def reload(self) -> None:
        """Re-read the config file and refresh the connection list."""
        self.model.load()
        self.main_view.set_connections(
            [c.values() for c in self.model.connections()]
        )

    # ------------------------------------------------------------ opening

    def on_connection_activated(self, row: int) -> None:
        """Open the clicked connection, fresh from its file."""
        if self.connection_view.isVisible():
            self.connection_view.open_editor()  # don't clobber open edits
            return
        clicked = self._connection_at(row)
        self.reload()
        if clicked is None:
            return
        # Reloaded by name: the list may have changed on disk meanwhile.
        connection = self.model.find(clicked.name)
        if connection is not None:
            self._edit(connection.name, connection)

    def on_add_requested(self) -> None:
        """Open the editor for a new, empty connection (saved on Save)."""
        if self.connection_view.isVisible():
            self.connection_view.open_editor()
            return
        self.reload()
        self._edit(None, new_connection())

    def _connection_at(self, row: int) -> Connection | None:
        """The connection shown in list ``row`` (as last loaded)."""
        connections = self.model.connections()
        return connections[row] if 0 <= row < len(connections) else None

    def _edit(self, name: str | None, connection: Connection) -> None:
        self._editing = name
        self.connection_view.set_values(connection.values())
        self.connection_view.set_new(name is None)
        self.connection_view.open_editor()

    # ------------------------------------------------------------ actions

    def on_save(self) -> None:
        """Save the edited (or new) connection to its file."""
        edited = Connection(self.connection_view.values())
        if not self._save(edited):
            return
        self.reload()
        # Saved now (maybe under a new name): further Saves edit that file.
        self._edit(edited.name, self.model.find(edited.name) or edited)
        self.connection_view.show_status(
            f"Saved {self.model.path_of(edited.name)}"
        )

    def on_reset(self) -> None:
        """Discard edits: refill the editor from the file."""
        self.reload()
        saved = (
            self.model.find(self._editing)
            if self._editing is not None else None
        )
        if saved is not None:
            self._edit(saved.name, saved)
        else:
            self._edit(None, new_connection())  # new, or its file is gone

    def on_delete(self) -> None:
        """After confirmation, delete the edited connection's file."""
        if self._editing is None:
            return
        name = self._editing
        if not self.connection_view.confirm_delete(
            name or "(unnamed)", self.model.path_of(name)
        ):
            return
        try:
            self.model.delete(name)
        except OSError as err:
            self.connection_view.show_error(
                "Delete failed",
                f"Can't delete {self.model.path_of(name)}:\n"
                f"{err.strerror or err}",
            )
            return
        self._editing = None
        self.connection_view.close_editor()
        self.reload()

    def on_check(self) -> None:
        """Check the SSH login with the values in the form (even unsaved).

        Blocks the GUI for up to ssh_check.CHECK_TIMEOUT_S seconds.
        """
        view = self.connection_view
        connection = Connection(view.values())
        # The values go to ssh as arguments: never run it with invalid ones
        # (e.g. a REMOTE_USER starting with "-" would be an ssh option).
        errors = connection.validate(CHECK_KEYS)
        if errors:
            view.show_error("Can't check the connection", "\n".join(errors))
            return
        view.set_busy(
            True,
            f"Checking connection (up to {ssh_check.CHECK_TIMEOUT_S} s)...",
        )
        try:
            result = ssh_check.check(
                connection[config_schema.REMOTE_USER.key],
                connection[config_schema.REMOTE_SERVER.key],
                connection[config_schema.REMOTE_SERVER_SSH_PORT.key],
            )
        finally:
            view.set_busy(False)
        view.show_check_result(
            result,
            ssh_keys.local_user_note(
                connection[config_schema.RUN_DAEMON_USER.key]
            ),
        )

    def on_daemon_check(self, row: int) -> None:
        """Check the systemd service running the connection in ``row``."""
        connection = self._connection_at(row)
        if connection is None:
            return
        service = daemon_check.service_for(connection.name)
        self.main_view.set_busy(row, True)
        try:
            result = daemon_check.run_check(service)
        finally:
            self.main_view.set_busy(row, False)
        self.main_view.show_daemon_result(
            result, daemon_check.coverage_note(connection.name)
        )

    def _save(self, connection: Connection) -> bool:
        """Validate and write; report problems in the editor. True if saved."""
        view = self.connection_view
        errors = self.model.validate(connection, self._editing)
        if errors:
            view.show_error("Invalid values", "\n".join(errors))
            return False
        try:
            self.model.save(connection, self._editing)
        except ValidationError as err:  # e.g. the name got taken meanwhile
            view.show_error("Invalid values", "\n".join(err.errors))
            return False
        except OSError as err:
            path = err.filename or self.model.path_of(connection.name)
            view.show_error(
                "Save failed", f"Can't save {path}:\n{err.strerror or err}"
            )
            return False
        return True
