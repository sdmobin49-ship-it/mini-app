"""
Stub هایی برای اجرای تست‌ها در محیطی که aiohttp/aiosqlite/aiogram نصب نیستند.
- aiosqlite: روی sqlite3 واقعی، با اجرای هر عملیات در thread (مثل aiosqlite واقعی)
- aiohttp(.web): یک روتر/middleware-runner حداقلی برای تست منطق server.py (نه خود aiohttp)
در محیط واقعی (requirements نصب‌شده) اگر کتابخانه‌ها موجود باشند stub نصب نمی‌شود.
"""
import asyncio
import json
import re
import sqlite3
import sys
import types


def install():
    try:
        import aiosqlite  # noqa
        import aiohttp    # noqa
        return False
    except ImportError:
        pass

    # ───── aiosqlite ─────
    m = types.ModuleType("aiosqlite")
    m.Row, m.IntegrityError, m.OperationalError = sqlite3.Row, sqlite3.IntegrityError, sqlite3.OperationalError

    from concurrent.futures import ThreadPoolExecutor

    async def _run(pool, fn, *a):
        return await asyncio.get_running_loop().run_in_executor(pool, lambda: fn(*a))

    class Cursor:
        def __init__(self, cur, pool):
            self._c, self._pool = cur, pool
        rowcount = property(lambda s: s._c.rowcount)
        lastrowid = property(lambda s: s._c.lastrowid)
        async def fetchone(self):
            return await _run(self._pool, self._c.fetchone)
        async def fetchall(self):
            return await _run(self._pool, self._c.fetchall)

    class _Exec:
        def __init__(self, coro):
            self._coro = coro
        def __await__(self):
            return self._coro.__await__()
        async def __aenter__(self):
            self._cur = await self._coro
            return self._cur
        async def __aexit__(self, *a):
            return False

    class Conn:
        def __init__(self, path, **kw):
            self._path, self._kw, self._db = path, kw, None
            self._pool = ThreadPoolExecutor(max_workers=1)
            self.row_factory = None
        def __await__(self):
            return self._open().__await__()
        async def _open(self):
            self._db = await _run(self._pool, lambda: sqlite3.connect(self._path, check_same_thread=False, **{'timeout': 5, **self._kw}))
            return self
        async def __aenter__(self):
            await self._open()
            return self
        async def __aexit__(self, *a):
            await _run(self._pool, self._db.close)
            self._pool.shutdown(wait=False)
        def __setattr__(self, k, v):
            object.__setattr__(self, k, v)
            if k == "row_factory" and getattr(self, "_db", None) is not None:
                self._db.row_factory = v
        async def _ex(self, sql, args=()):
            if self.row_factory is not None:
                self._db.row_factory = self.row_factory
            cur = await _run(self._pool, self._db.execute, sql, args)
            return Cursor(cur, self._pool)
        def execute(self, sql, args=()):
            return _Exec(self._ex(sql, args))
        async def executescript(self, s):
            await _run(self._pool, self._db.executescript, s)
        async def commit(self):
            await _run(self._pool, self._db.commit)

    m.connect = lambda path, **kw: Conn(path, **kw)
    sys.modules["aiosqlite"] = m

    # ───── aiohttp + aiohttp.web (حداقلی) ─────
    ah = types.ModuleType("aiohttp")
    ah.ClientSession = object
    web = types.ModuleType("aiohttp.web")

    class HTTPException(Exception):
        status, reason = 500, None
    class HTTPRequestEntityTooLarge(HTTPException):
        status = 413
    class Response:
        def __init__(self, body=None, status=200, headers=None):
            self.body, self.status, self.headers = body, status, dict(headers or {})
    class FileResponse(Response):
        def __init__(self, path, headers=None):
            super().__init__(None, 200, headers)
    class Request(dict):
        def __init__(self, app, method, path, headers=None, query=None, body=None, form=None):
            super().__init__()
            self.app, self.method, self.path = app, method, path
            self.headers, self.query, self.match_info = headers or {}, query or {}, {}
            self._body, self._form, self.remote = body, form, "1.2.3.4"
            self.content_type = "multipart/form-data" if form is not None else "application/json"
        async def json(self):
            if self._body is None:
                raise ValueError("no body")
            return self._body
        async def post(self):
            return self._form
    class Application(dict):
        def __init__(self, middlewares=(), client_max_size=0):
            super().__init__()
            self.middlewares, self.routes = list(middlewares), []
        def add_routes(self, r):
            self.routes += r
    class RouteDef:
        def __init__(self, method, path, handler):
            self.method, self.path, self.handler = method, path, handler
            self.rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$")
    def json_response(data, status=200, headers=None):
        return Response(json.dumps(data), status, headers)

    web.HTTPException, web.HTTPRequestEntityTooLarge = HTTPException, HTTPRequestEntityTooLarge
    web.Response, web.FileResponse, web.Request, web.Application = Response, FileResponse, Request, Application
    web.json_response = json_response
    web.AppRunner = web.TCPSite = type('Unused', (), {})
    web.middleware = lambda f: f
    web.get = lambda p, h: RouteDef("GET", p, h)
    web.post = lambda p, h: RouteDef("POST", p, h)
    web.static = lambda prefix, path, **kw: RouteDef("GET", prefix + "/{f}", None)
    ah.web = web
    sys.modules["aiohttp"], sys.modules["aiohttp.web"] = ah, web


async def http_call(app, method, path, headers=None, json_body=None, form=None, query=None):
    """اجرای درخواست از میان middlewareهای واقعی server.py و handler مسیر؛ خروجی (status, json)."""
    from aiohttp import web
    req = web.Request(app, method, path, headers, query, json_body, form)
    route = next((r for r in app.routes if r.method == method and r.rx.match(path)), None)
    if route is None or route.handler is None:
        return 404, {}
    req.match_info = route.rx.match(path).groupdict()
    h = route.handler
    for mw in reversed(app.middlewares):
        h = (lambda mw, nxt: (lambda r: mw(r, nxt)))(mw, h)
    resp = await h(req)
    return resp.status, (json.loads(resp.body) if resp.body else None)
