from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(
    data: Any = None,
    message: str = "OK",
    status_code: int = 200,
    headers: Optional[dict] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content=jsonable_encoder({"success": True, "message": message, "data": data, "error": None}),
    )


def error_response(
    code: str,
    message: str,
    status_code: int,
    details: Any = None,
    headers: Optional[dict] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content=jsonable_encoder(
            {
                "success": False,
                "message": message,
                "data": None,
                "error": {"code": code, "details": details},
            }
        ),
    )
