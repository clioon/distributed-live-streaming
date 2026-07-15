from collections.abc import Mapping
import logging
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, status
from fastapi.responses import PlainTextResponse

from .callbacks import ApiGateway, CallbackService, InvalidCallback
from .gateway import HttpApiGateway, UpstreamRejected, UpstreamUnavailable


MAX_CALLBACK_BODY_BYTES = 4_096
MAX_CALLBACK_FIELDS = 16
LOGGER = logging.getLogger(__name__)


async def _read_form(request: Request) -> Mapping[str, str]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_CALLBACK_BODY_BYTES:
                raise InvalidCallback("Callback body is too large")
        except ValueError as error:
            raise InvalidCallback("Callback content length is invalid") from error

    body = bytearray()
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_CALLBACK_BODY_BYTES:
                raise InvalidCallback("Callback body is too large")
        encoded_form = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidCallback("Callback body must be UTF-8") from error
    try:
        values = parse_qs(
            encoded_form,
            keep_blank_values=True,
            max_num_fields=MAX_CALLBACK_FIELDS,
        )
    except ValueError as error:
        raise InvalidCallback("Callback contains too many fields") from error
    return {key: items[-1] for key, items in values.items()}


def create_app(
    gateway: ApiGateway | None = None,
    *,
    api_base_url: str = "http://api-service:8000",
) -> FastAPI:
    if gateway is None:
        gateway = HttpApiGateway(api_base_url)
    callback_service = CallbackService(gateway)
    app = FastAPI(title="RTMP Ingest Callback", version="0.1.0")

    @app.exception_handler(InvalidCallback)
    async def invalid_callback_handler(
        _request, error: InvalidCallback
    ) -> PlainTextResponse:
        LOGGER.warning("RTMP callback rejected: %s", error)
        return PlainTextResponse(str(error), status_code=400)

    @app.exception_handler(UpstreamRejected)
    async def upstream_rejected_handler(
        _request, error: UpstreamRejected
    ) -> PlainTextResponse:
        response_status = error.status_code if 400 <= error.status_code < 500 else 502
        return PlainTextResponse(str(error), status_code=response_status)

    @app.exception_handler(UpstreamUnavailable)
    async def upstream_unavailable_handler(
        _request, error: UpstreamUnavailable
    ) -> PlainTextResponse:
        return PlainTextResponse(str(error), status_code=503)

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/callbacks/on-publish", status_code=status.HTTP_200_OK)
    async def on_publish(request: Request) -> PlainTextResponse:
        fields = await _read_form(request)
        LOGGER.info(
            "RTMP publish fields app=%r name=%r args_present=%s args_length=%d clientid=%r keys=%s",
            fields.get("app"),
            fields.get("name"),
            bool(fields.get("args")),
            len(fields.get("args", "")),
            fields.get("clientid"),
            sorted(fields),
        )
        callback_service.on_publish(fields)
        return PlainTextResponse("OK")

    @app.post("/callbacks/on-publish-done", status_code=status.HTTP_200_OK)
    async def on_publish_done(request: Request) -> PlainTextResponse:
        callback_service.on_publish_done(await _read_form(request))
        return PlainTextResponse("OK")

    return app