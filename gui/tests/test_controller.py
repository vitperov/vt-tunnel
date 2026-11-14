"""Tests for the controller wiring: the editor dialog widget and the
editing flows through the GUI."""

from PyQt6.QtWidgets import QCheckBox, QLabel

from vt_tunnel_gui import config_schema
from vt_tunnel_gui.views.connection_view import ConnectionEditor


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
