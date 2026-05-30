import json

from starlette.responses import Response


def json_response(status_code: int, detail: str) -> Response:
    body = json.dumps({"detail": detail}, ensure_ascii=False)
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
    )
