"""Adapt the owning services' signatures to the internal job context."""

from collections.abc import Callable
from inspect import isasyncgenfunction, iscoroutinefunction, isgeneratorfunction, signature
from types import ModuleType

from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy.orm import Session

from app.documents import service as documents_service
from app.jobs import service as jobs_service
from app.jobs.schemas import JobContext, JobHandler
from app.jobs.service.exports import generate_if_current
from app.storage import service as storage_service

HANDLER_EXPORTS = (
    (storage_service, "expire_uploads_and_reservations", "as_of"),
    (documents_service, "purge_trash", "older_than"),
    (documents_service, "prune_versions", None),
    (storage_service, "delete_unused_objects", "older_than"),
    (storage_service, "reconcile_storage_quotas", None),
    (jobs_service, "expire_exports", "job"),
    (jobs_service, "generate_export", "job"),
)
DATETIME = TypeAdapter(AwareDatetime)


def _adapt(name: str, handler: Callable[..., None], parameter: str | None) -> JobHandler:
    def call(db: Session, job: JobContext) -> None:
        if name == "generate_export":
            generate_if_current(db, job, handler)
        elif parameter is None:
            handler(db)
        elif parameter == "job":
            handler(db, job)
        else:
            handler(db, **{parameter: DATETIME.validate_python(job.payload[parameter])})

    return call


def _check_signature(
    module: ModuleType, name: str, handler: Callable[..., None], parameter: str | None
) -> None:
    args = (object(), object()) if parameter == "job" else (object(),)
    kwargs: dict[str, object] = (
        {parameter: object()} if parameter is not None and parameter != "job" else {}
    )
    try:
        signature(handler).bind(*args, **kwargs)
    except (TypeError, ValueError) as error:
        expected = "db" if parameter is None else f"db, {parameter}"
        raise RuntimeError(f"{module.__name__}.{name} must accept ({expected})") from error


def installed_handlers() -> dict[str, JobHandler]:
    handlers = {}
    for module, name, parameter in HANDLER_EXPORTS:
        handler = getattr(module, name, None)
        if handler is None:
            continue
        if (
            not callable(handler)
            or iscoroutinefunction(handler)
            or isasyncgenfunction(handler)
            or isgeneratorfunction(handler)
        ):
            raise RuntimeError(f"{module.__name__}.{name} must be a synchronous function")
        _check_signature(module, name, handler, parameter)
        handlers[name] = _adapt(name, handler, parameter)
    return handlers
