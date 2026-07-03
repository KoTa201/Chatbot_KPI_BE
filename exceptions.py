"""
Domain exceptions + controller translation.

Services raise these framework-agnostic errors; controllers translate them
into HTTPException via `translate_app_errors` so every HTTP response is
produced at the controller boundary.
"""

from functools import wraps

from fastapi import HTTPException


class AppError(Exception):
    """Base domain error. Carries an HTTP status for controllers to translate."""

    status_code = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class BadRequestError(AppError):
    status_code = 400


class ValidationError(AppError):
    status_code = 422


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class InternalError(AppError):
    status_code = 500


def translate_app_errors(fn):
    """Translate AppError raised by the service layer into HTTPException."""

    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except AppError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)

    return wrapper
