# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *
from .dom import evaluate_json
from .session_events import maybe_await


async def get_meeting_status(page):
    return await evaluate_json(
        page,
        """() => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
            const lowerText = normalize(document.body?.innerText || '').toLowerCase();
            const buttonNodes = Array.from(document.querySelectorAll('button, [role="button"]'));
            const labels = buttonNodes
                .map((node) => normalize(node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || ''))
                .filter(Boolean)
                .map((label) => label.toLowerCase());

            return JSON.stringify({
                has_joined_control: labels.some((label) => label.includes('leave call')),
                waiting_for_host:
                    lowerText.includes('asking to be let in') ||
                    lowerText.includes('you\\'ll join the call when someone lets you in') ||
                    lowerText.includes('please wait until a meeting host brings you into the call'),
                denied:
                    lowerText.includes('request to join was denied') ||
                    lowerText.includes('denied your request to join'),
                blocked:
                    lowerText.includes('can\\'t join this video call') ||
                    lowerText.includes('no one can join a meeting unless invited or admitted by the host'),
                page_title: document.title || '',
            });
        }""",
    )


def classify_join_failure(status):
    if not status:
        return "join_unconfirmed", "Orbit could not confirm whether Meet admitted it."
    if status["waiting_for_host"]:
        return "waiting_for_host", "Orbit is waiting for a meeting host to admit it."
    if status["denied"]:
        return "join_denied", "Google Meet denied the join request."
    if status["blocked"]:
        return "join_blocked", "Google Meet blocked entry to this meeting."
    return "join_unconfirmed", "Orbit could not confirm whether Meet admitted it."


async def ensure_joined(page, timeout_ms=20000, on_waiting=None):
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    last_status = None
    waiting_reported = False

    while asyncio.get_running_loop().time() < deadline:
        status = await get_meeting_status(page)
        if status:
            last_status = status
            if status["waiting_for_host"] and on_waiting and not waiting_reported:
                waiting_reported = True
                await maybe_await(on_waiting(status))
            if status["denied"] or status["blocked"]:
                return False, status
        if status and status["has_joined_control"]:
            return True, status
        await asyncio.sleep(2)

    return False, last_status


async def get_participant_count(page):
    result = await evaluate_json(
        page,
        """() => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
            const counts = [];

            for (const node of candidates) {
                const label = normalize([
                    node.getAttribute('aria-label'),
                    node.getAttribute('title'),
                    node.textContent,
                ].filter(Boolean).join(' '));
                if (
                    !label.includes('show everyone') &&
                    !label.includes('participants') &&
                    !label.includes('people')
                ) {
                    continue;
                }

                const matches = label.match(/\\d+/g) || [];
                for (const match of matches) counts.push(Number(match));
            }

            return JSON.stringify({ count: counts.length ? Math.max(...counts) : null });
        }""",
    )
    if not result or result.get("count") is None:
        return None
    return int(result["count"])


def should_leave_when_only_orbit_remains(state, participant_count):
    if participant_count is None:
        state.solo_participant_polls = 0
        return False
    if participant_count > 1:
        state.observed_other_participants = True
        state.solo_participant_polls = 0
        return False
    if participant_count != 1:
        state.solo_participant_polls = 0
        return False

    state.solo_participant_polls += 1
    if not state.observed_other_participants:
        return state.solo_participant_polls >= (SOLO_PARTICIPANT_POLLS_BEFORE_LEAVE + 1)
    return state.solo_participant_polls >= SOLO_PARTICIPANT_POLLS_BEFORE_LEAVE
