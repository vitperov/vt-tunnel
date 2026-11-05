"""Controller wiring the model and the view."""


class Controller:
    """Coordinates the model and the view."""

    def __init__(self, model, view) -> None:
        self.model = model
        self.view = view

    def show(self) -> None:
        """Show the main window."""
        self.view.show()
