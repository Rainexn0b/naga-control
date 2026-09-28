"""Domain validation errors."""


class ConfigValidationError(ValueError):
    """A configuration value failed validation at a specific field path."""

    def __init__(self, field_path: str, message: str) -> None:
        self.field_path = field_path
        self.message = message
        super().__init__(f"{field_path}: {message}" if field_path else message)
