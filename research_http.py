"""Shared HTTP handlers for local development and Vercel Python Functions."""
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import research
import research_store as db


def send_json(handler, status, data, cookie=None):
    payload = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    handler.wfile.write(payload)


def identity(headers, create=False):
    secret = os.environ.get("ZEARCH_SESSION_SECRET", "")
    if len(secret) < 32:
        raise research.Unavailable("Live research is being configured. Please check back shortly.")
    jar = SimpleCookie()
    try:
        jar.load(headers.get("Cookie", ""))
        token = jar.get("zearch_session").value if jar.get("zearch_session") else ""
    except Exception:
        token = ""
    parts = token.split(".")
    valid = False
    if len(parts) == 3 and re.fullmatch(r"[a-f0-9]{48}", parts[0]) and re.fullmatch(r"[0-9]{1,12}", parts[1]):
        payload = parts[0] + "." + parts[1]
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        valid = hmac.compare_digest(sig, parts[2]) and int(parts[1]) > time.time()
    cookie = None
    if not valid:
        if not create:
            return None, None
        payload = secrets.token_hex(24) + "." + str(int(time.time()) + 30 * 86400)
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        token = payload + "." + sig
        cookie = "zearch_session=" + token + "; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000"
        if os.environ.get("VERCEL"):
            cookie += "; Secure"
    # Database never stores the bearer cookie itself.
    owner = hmac.new(secret.encode(), token.split(".")[0].encode(), hashlib.sha256).hexdigest()
    return owner, cookie


def get(handler):
    params = parse_qs(urlsplit(handler.path).query)
    rid = params.get("id", [None])[0]
    if not rid:
        missing = research.configuration()
        available = not missing
        if missing:
            # Names only. Never log credentials or connection strings.
            logging.warning('Zearch missing research settings: %s', ', '.join(sorted(set(missing))))
        if available:
            try:
                db.ensure_schema()
                with db.connection() as (conn, _):
                    conn.execute("SELECT run_id FROM research_options LIMIT 1")
            except Exception as exc:
                logging.warning('Zearch research database check failed: %s', type(exc).__name__)
                available = False
        return send_json(handler, 200, {"available": available, "tagline": "A space for discovery.",
                                      "mode": "live" if available else "setup_required"})
    try:
        if not re.fullmatch(r"[a-f0-9]{32}", rid):
            return send_json(handler, 404, {"error": "Search not found"})
        owner, _ = identity(handler.headers)
        record = db.get_run(owner, rid) if owner else None
        return send_json(handler, 200 if record else 404, record or {"error": "Search not found"})
    except Exception:
        return send_json(handler, 503, {"error": "Saved research is temporarily unavailable"})


def post(handler):
    cookie = None
    try:
        origin = handler.headers.get("Origin")
        if origin and urlsplit(origin).netloc != handler.headers.get("Host"):
            return send_json(handler, 403, {"error": "Request origin is not allowed"})
        length = int(handler.headers.get("Content-Length", "0"))
        if length < 1 or length > 12000:
            return send_json(handler, 400, {"error": "Invalid request size"})
        if not handler.headers.get("Content-Type", "").startswith("application/json"):
            return send_json(handler, 415, {"error": "Expected application/json"})
        body = json.loads(handler.rfile.read(length))
        research.validate(body)
        owner, cookie = identity(handler.headers, create=True)
        if research.ready():
            db.ensure_schema()
        record, fresh, history = research.prepare(owner, body)
        if not fresh:
            return send_json(handler, 200, {"run": record}, cookie)
    except (ValueError, TypeError):
        return send_json(handler, 400, {"error": "Invalid question or request identifier"}, cookie)
    except db.LimitReached as exc:
        return send_json(handler, 429, {"error": str(exc)}, cookie)
    except research.Unavailable as exc:
        return send_json(handler, 503, {"error": str(exc)}, cookie)
    except Exception:
        return send_json(handler, 503, {"error": "Research storage is not ready. Please try again later."}, cookie)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-transform")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Connection", "close")
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    handler.close_connection = True
    events = research.run(owner, record, history)
    try:
        for event in events:
            handler.wfile.write((json.dumps(event) + "\n").encode())
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        events.close()
