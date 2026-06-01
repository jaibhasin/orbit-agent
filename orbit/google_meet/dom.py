# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *


async def evaluate_json(page, script, *args):
    raw_result = await page.evaluate(script, *args)
    if raw_result is None or raw_result == "":
        return None
    return json.loads(raw_result)
