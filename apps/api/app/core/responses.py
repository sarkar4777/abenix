from typing import Any

from fastapi.responses import JSONResponse


def success(data: Any, meta: dict | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": data, "error": None, "meta": meta},
    )


def error(message: str, code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"data": None, "error": {"message": message, "code": code}},
    )
