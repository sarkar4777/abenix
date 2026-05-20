from typing import Any

from fastapi.responses import JSONResponse


def success(
    data: Any, meta: dict | None = None, status_code: int = 200
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": data, "error": None, "meta": meta},
    )


def error(
    message: str,
    code: int = 400,
    error_code: str | None = None,
    details: dict | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {"message": message, "code": code}
    if error_code:
        payload["error_code"] = error_code
    if details:
        payload["details"] = details
    return JSONResponse(
        status_code=code,
        content={"data": None, "error": payload},
    )
