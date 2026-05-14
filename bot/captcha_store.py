"""
Captcha Session Store
Shared state between the Flask server (threaded) and the asyncio bot loop.
"""

import asyncio
import uuid

_sessions: dict = {}


def create_session(loop: asyncio.AbstractEventLoop) -> str:
    session_id = uuid.uuid4().hex
    future = loop.create_future()
    _sessions[session_id] = {"future": future, "loop": loop}
    return session_id


def resolve_session(session_id: str, token: str) -> bool:
    session = _sessions.pop(session_id, None)
    if not session:
        return False
    future: asyncio.Future = session["future"]
    loop: asyncio.AbstractEventLoop = session["loop"]
    loop.call_soon_threadsafe(
        lambda: future.set_result(token) if not future.done() else None
    )
    return True


async def wait_for_token(session_id: str, timeout: float = 300.0) -> str:
    session = _sessions.get(session_id)
    if not session:
        raise Exception("Captcha session not found.")
    try:
        return await asyncio.wait_for(asyncio.shield(session["future"]), timeout=timeout)
    except asyncio.TimeoutError:
        _sessions.pop(session_id, None)
        raise Exception("Captcha timed out. Please try again.")


def session_exists(session_id: str) -> bool:
    return session_id in _sessions
