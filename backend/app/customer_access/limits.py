from starlette.responses import JSONResponse


class AccessBodyLimit:
    """Bound anonymous access JSON bodies before FastAPI parses/validates them."""
    def __init__(self, app, limit=32768):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not scope['path'].startswith('/api/v1/access/'):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event['type'] == 'http.disconnect':
                return
            chunk = event.get('body', b'')
            if len(body) + len(chunk) > self.limit:
                return await JSONResponse({'code': 'ACCESS_BODY_TOO_LARGE', 'detail': '요청 내용이 너무 큽니다.'}, status_code=413,
                    headers={'Cache-Control': 'no-store'})(scope, receive, send)
            body.extend(chunk)
            if not event.get('more_body'):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)
