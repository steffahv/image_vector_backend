"""Answer for routes whose contract is published but whose logic is not written yet.

The documents and storage routes (VEC-31, VEC-42, VEC-43) are published first, so the editor
can be built against Swagger in parallel. Each route stops using this once it is implemented;
delete this file when nothing imports it.
"""

from typing import Any, NoReturn

from fastapi import HTTPException, status

NOT_IMPLEMENTED_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_501_NOT_IMPLEMENTED: {"description": "Contract published; not implemented yet."}
}


def not_implemented() -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet.")
