# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *
from .dom import evaluate_json
from .session_events import maybe_await


def _join_poll_interval_ms() -> int:
    return max(150, env_int("GMEET_JOIN_POLL_INTERVAL_MS", 250))


async def attempt_fast_guest_join(page, meet_url, display_name, session_id=None, timeout_ms=12000):
    log(f"evt=join.fast_open meet_url={meet_url}", session_id, level="important")
    await page.goto(meet_url)

    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    last_action = None
    while asyncio.get_running_loop().time() < deadline:
        status = await get_meeting_status(page)
        if status and (status["has_joined_control"] or status["waiting_for_host"]):
            log("evt=join.fast_done state=already_submitted_or_joined", session_id, level="important")
            return True

        result = await evaluate_json(
            page,
            """(displayName) => {
                const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
                const lower = (text) => normalize(text).toLowerCase();
                const visible = (node) => {
                    if (!node || !(node instanceof HTMLElement)) return false;
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                };
                const labelFor = (node) => lower([
                    node.getAttribute('aria-label'),
                    node.getAttribute('title'),
                    node.textContent,
                ].filter(Boolean).join(' '));
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(visible);
                const clickMatchingButton = (patterns) => {
                    for (const pattern of patterns) {
                        const button = buttons.find((node) => labelFor(node).includes(pattern));
                        if (button) {
                            button.click();
                            return pattern;
                        }
                    }
                    return null;
                };
                const setInputValue = (input, value) => {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(input, value);
                    else input.value = value;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                };

                const closed = clickMatchingButton(['close dialog', 'close']);
                if (closed) return JSON.stringify({ action: 'closed_modal', matched: closed });

                const continued = clickMatchingButton(['continue without microphone and camera']);
                if (continued) return JSON.stringify({ action: 'continued_without_media', matched: continued });

                const mediaOff = clickMatchingButton(['turn off microphone', 'turn off camera']);
                if (mediaOff) return JSON.stringify({ action: 'disabled_media', matched: mediaOff });

                const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
                const nameInput = inputs.find((input) => {
                    const type = lower(input.getAttribute('type'));
                    const label = lower([
                        input.getAttribute('aria-label'),
                        input.getAttribute('placeholder'),
                        input.name,
                        input.id,
                    ].filter(Boolean).join(' '));
                    return type !== 'hidden' && type !== 'password' && (
                        label.includes('name') ||
                        label.includes('your name') ||
                        inputs.length === 1
                    );
                });
                if (nameInput && normalize(nameInput.value) !== displayName) {
                    nameInput.focus();
                    setInputValue(nameInput, displayName);
                    return JSON.stringify({ action: 'name_filled' });
                }

                const joined = clickMatchingButton(['ask to join', 'join now', 'request to join']);
                if (joined) return JSON.stringify({ action: 'join_clicked', matched: joined });

                return JSON.stringify({
                    action: 'waiting',
                    title: document.title || '',
                    url: location.href,
                });
            }""",
            display_name,
        )
        action = (result or {}).get("action")
        if action and action != "waiting" and action != last_action:
            log(
                f"evt=join.fast_action action={action} matched={(result or {}).get('matched')}",
                session_id,
                level="important",
            )
            last_action = action
        if action == "join_clicked":
            log("evt=join.fast_done state=join_clicked", session_id, level="important")
            return True
        await asyncio.sleep(_join_poll_interval_ms() / 1000)

    log("evt=join.fast_fallback reason=timeout", session_id, level="important")
    return False


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


async def ensure_joined(page, timeout_ms=20000, on_waiting=None, poll_interval_ms=None):
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    last_status = None
    waiting_reported = False
    poll_interval = max(0.1, (poll_interval_ms or _join_poll_interval_ms()) / 1000)

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
        await asyncio.sleep(poll_interval)

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
