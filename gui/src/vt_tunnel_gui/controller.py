"""Controller wiring the model and the views."""


class Controller:
    """Coordinates the model, the connection list and the editor window.

    The config file holds a single connection for now; it is row 0 of
    the connection list.
    """

    def __init__(self, model, main_view, connection_view) -> None:
        self.model = model
        self.main_view = main_view
        self.connection_view = connection_view

        self.main_view.connection_activated.connect(
            self.on_connection_activated
        )
        self.connection_view.update_requested.connect(self.on_update)
        self.connection_view.reset_requested.connect(self.on_reset)

        self.reload()

    def show(self) -> None:
        """Show the main window."""
        self.main_view.show()

    def reload(self) -> None:
        """Re-read the config file and refresh the list and the editor."""
        self.model.load()
        values = self.model.values()
        self.main_view.set_connections([values])
        self.connection_view.set_values(values)

    def on_connection_activated(self, row: int) -> None:
        """Open the editor for the clicked connection, fresh from the file."""
        if row != 0:
            return  # only one connection exists for now
        if not self.connection_view.isVisible():
            self.reload()  # don't clobber edits in an already open editor
        self.connection_view.open_editor()

    def on_update(self) -> None:
        """Validate the form and save it to the config file."""
        view = self.connection_view
        values = view.values()
        path = self.model.config_path

        errors = self.model.validate(values)
        if errors:
            view.show_error("Invalid values", "\n".join(errors))
            return
        if not self.model.config_exists() and not view.confirm_create(path):
            return
        try:
            self.model.save(values)
        except OSError as err:
            view.show_error(
                "Save failed", f"Can't save {path}:\n{err.strerror or err}"
            )
            return
        self.reload()
        view.show_status(f"Saved {path}")

    def on_reset(self) -> None:
        """Discard edits: refill the editor (and list) from the file."""
        self.reload()
