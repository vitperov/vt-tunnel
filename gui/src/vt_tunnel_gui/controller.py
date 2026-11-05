"""Controller wiring the model and the view."""


class Controller:
    """Coordinates the model and the view."""

    def __init__(self, model, view) -> None:
        self.model = model
        self.view = view

        self.view.update_requested.connect(self.on_update)
        self.view.reset_requested.connect(self.on_reset)

        self.view.set_values(self.model.values())

    def show(self) -> None:
        """Show the main window."""
        self.view.show()

    def on_update(self) -> None:
        """Push the values entered in the form to the model."""
        self.model.update(self.view.values())

    def on_reset(self) -> None:
        """Discard edits: refill the form with the model's values."""
        self.view.set_values(self.model.values())
