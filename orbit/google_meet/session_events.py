# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *


async def maybe_await(result):
    if inspect.isawaitable(result):
        return await result
    return result


async def emit_status(callbacks, state, status, detail=None):
    state.status = status
    state.status_detail = detail
    if callbacks and callbacks.on_status:
        await maybe_await(callbacks.on_status(state, status, detail))


async def emit_chat_message(callbacks, state, message, source):
    if callbacks and callbacks.on_chat_message:
        await maybe_await(callbacks.on_chat_message(state, message, source))


async def emit_captions(callbacks, state, captions):
    if callbacks and callbacks.on_captions:
        await maybe_await(callbacks.on_captions(state, captions))


async def emit_orbit_mention(callbacks, state, message):
    if callbacks and callbacks.on_orbit_mention:
        return await maybe_await(callbacks.on_orbit_mention(state, message))
    return None


async def emit_finished(callbacks, state):
    if callbacks and callbacks.on_finished:
        await maybe_await(callbacks.on_finished(state))


def finalize_meeting_status(state):
    if state.last_error:
        state.status = "failed"
    elif state.stop_requested:
        state.status = "stopped"
    elif state.joined_at:
        state.status = "completed"
