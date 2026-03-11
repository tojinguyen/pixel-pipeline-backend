class AppError(Exception):
    """Base class for domain-level errors."""


class StorageError(AppError):
    """Raised when storage operations fail."""


class ImageProcessingError(AppError):
    """Raised when image processing fails."""
