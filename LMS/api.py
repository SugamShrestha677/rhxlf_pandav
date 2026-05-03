from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def api_success(*, data=None, message="Success", status_code=200, **extra):
    payload = {
        "success": True,
        "message": message,
        "data": data,
    }
    payload.update(extra)
    return Response(payload, status=status_code)


def api_error(*, message="Request failed", errors=None, status_code=400, **extra):
    payload = {
        "success": False,
        "message": message,
        "errors": errors,
    }
    payload.update(extra)
    return Response(payload, status=status_code)


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is None:
        return response

    detail = response.data
    message = "Request failed"
    errors = detail

    if isinstance(detail, dict):
        message = detail.get("detail") or detail.get("message") or "Request failed"
        errors = {key: value for key, value in detail.items() if key not in {"detail", "message"}}
        if not errors:
            errors = None
    else:
        message = str(detail)

    response.data = {
        "success": False,
        "message": message,
        "errors": errors,
        "status_code": response.status_code,
    }
    return response