"""Controller wiring the model and the view."""

from vt_tunnel_gui.models.tunnel_config import ConfigValidationError


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
        """Validate the form and save it; ask before creating a new file."""
        values = self.view.values()
        errors = self.model.validate(values)
        if errors:
            self._not_saved()
            self.view.show_validation_errors(errors)
            return

        path = str(self.model.config_path)
        create = not self.model.config_exists()
        if create and not self.view.confirm_create(path):
            self._not_saved()
            return

        try:
            self.model.save(values, create=create)
        except ConfigValidationError as err:
            self._not_saved()
            self.view.show_validation_errors(err.errors)
            return
        except FileNotFoundError:
            # Deleted between the check and the write: don't create it
            # without asking.
            self._not_saved()
            self.view.show_error(
                "Not saved", f"The config file disappeared:\n{path}"
            )
            return
        except OSError as err:
            # strerror: hide internal details such as the temp file name.
            self._not_saved()
            self.view.show_error(
                "Not saved", f"Can't save {path}:\n{err.strerror or err}"
            )
            return
        self.view.show_status(f"Saved to {path}")
        self.reload()

    def _not_saved(self) -> None:
        self.view.show_status("Not saved")

    def on_reset(self) -> None:
        """Discard edits: refill the form from the config file."""
        self.reload()
