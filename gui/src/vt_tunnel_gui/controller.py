"""Controller wiring the model and the views."""

from collections.abc import Sequence

from vt_tunnel_gui.models.connection import Connection


class Controller:
    """Coordinates the model, the connection list and the editor window.

    Remembers which list row the editor shows (``None`` for a connection
    that isn't saved yet). Every change saves the whole list, so the
    numbering in the file always follows the list order.
    """

    def __init__(self, model, main_view, connection_view) -> None:
        self.model = model
        self.main_view = main_view
        self.connection_view = connection_view
        self._editing: int | None = None

        self.main_view.connection_activated.connect(
            self.on_connection_activated
        )
        self.main_view.add_requested.connect(self.on_add_requested)
        self.connection_view.update_requested.connect(self.on_update)
        self.connection_view.reset_requested.connect(self.on_reset)
        self.connection_view.delete_requested.connect(self.on_delete)

        self.reload()

    def show(self) -> None:
        """Show the main window."""
        self.main_view.show()

    def reload(self) -> None:
        """Re-read the config file and refresh the connection list."""
        self.model.load()
        self.main_view.set_connections(
            [c.values() for c in self.model.connections()]
        )

    # ------------------------------------------------------------ opening

    def on_connection_activated(self, row: int) -> None:
        """Open the clicked connection, fresh from the file."""
        if self.connection_view.isVisible():
            self.connection_view.open_editor()  # don't clobber open edits
            return
        self.reload()
        connections = self.model.connections()
        if 0 <= row < len(connections):
            self._edit(row, connections[row])

    def on_add_requested(self) -> None:
        """Open the editor for a new, empty connection (saved on Update)."""
        if self.connection_view.isVisible():
            self.connection_view.open_editor()
            return
        self.reload()
        self._edit(None, Connection())

    def _edit(self, row: int | None, connection: Connection) -> None:
        self._editing = row
        self.connection_view.set_values(connection.values())
        self.connection_view.set_new(row is None)
        self.connection_view.open_editor()

    # ------------------------------------------------------------ actions

    def on_update(self) -> None:
        """Save the edited (or new) connection together with the others."""
        connections = self.model.connections()
        edited = Connection(self.connection_view.values())
        if self._editing is None:
            connections.append(edited)
            row = len(connections) - 1
        else:
            row = self._editing
            connections[row] = edited
        if not self._save(connections):
            return
        self.reload()
        # A new connection is saved now: further Updates edit it in place.
        self._edit(row, self.model.connections()[row])
        self.connection_view.show_status(f"Saved {self.model.config_path}")

    def on_reset(self) -> None:
        """Discard edits: refill the editor from the file."""
        self.reload()
        connections = self.model.connections()
        if self._editing is not None and self._editing < len(connections):
            self._edit(self._editing, connections[self._editing])
        else:
            self._edit(None, Connection())  # new, or gone from the file

    def on_delete(self) -> None:
        """After confirmation, remove the edited connection and save."""
        if self._editing is None:
            return
        connections = self.model.connections()
        connection = connections[self._editing]
        if not self.connection_view.confirm_delete(
            connection.name or "(unnamed)", self.model.config_path
        ):
            return
        del connections[self._editing]
        if not self._save(connections):
            return
        self._editing = None
        self.connection_view.close_editor()
        self.reload()

    def _save(self, connections: Sequence[Connection]) -> bool:
        """Validate and write; report problems in the editor. True if saved."""
        view = self.connection_view
        path = self.model.config_path
        errors = self.model.validate(connections)
        if errors:
            view.show_error("Invalid values", "\n".join(errors))
            return False
        if not self.model.config_exists() and not view.confirm_create(path):
            return False
        try:
            self.model.save(connections)
        except OSError as err:
            view.show_error(
                "Save failed", f"Can't save {path}:\n{err.strerror or err}"
            )
            return False
        return True
