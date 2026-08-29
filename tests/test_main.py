import asyncio

from fastapi import Request


def test_unhandled_exception_handler_returns_500_json():
    from app.main import unhandled_exception_handler

    request = Request(scope={"type": "http", "headers": []})
    response = asyncio.run(unhandled_exception_handler(request, RuntimeError("boom")))
    assert response.status_code == 500
