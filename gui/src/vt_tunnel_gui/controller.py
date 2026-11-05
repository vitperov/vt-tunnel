"""Controller wiring the model and the view."""


class Controller:
    """Coordinates the model and the view."""

    def __init__(self, model, view) -> None:
        self.model = model
        self.view = view

        self.view.update_requested.connect(self.on_update)
        self.view.reset_requested.connect(self.on_reset)

        self.reload()

    def show(self) -> None:
        """Show the main window."""
        self.view.show()

    def reload(self) -> None:
        """Re-read the config file and fill the form with its values."""
        self.model.load()
        self.view.set_values(self.model.values())

    def on_update(self) -> None:
        """Validate the form and save it to the config file."""
        values = self.view.values()
        path = self.model.config_path

        errors = self.model.validate(values)
        if errors:
            self.view.show_error("Invalid values", "\n".join(errors))
            return
        if not self.model.config_exists() and not self.view.confirm_create(
            path
        ):
            return
        try:
            self.model.save(values)
        except OSError as err:
            self.view.show_error(
                "Save failed", f"Can't save {path}:\n{err.strerror or err}"
            )
            return
        self.reload()
        self.view.show_status(f"Saved {path}")

    def on_reset(self) -> None:
        """Discard edits: refill the form from the config file."""
        self.reload()
