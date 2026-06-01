# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *
from .captions import collect_visible_captions
from .dom import evaluate_json
from .join_flow import get_participant_count, should_leave_when_only_orbit_remains
from .session_config import build_intro_message
from .session_events import emit_captions, emit_chat_message, emit_orbit_mention, emit_status


async def is_chat_panel_open(page):
    result = await evaluate_json(
        page,
        """() => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const isVisible = (node) => {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };

            const hasMessageBox = Array.from(
                document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"], [role="textbox"]')
            ).some((node) => {
                if (!isVisible(node)) return false;
                const label = normalize(
                    node.getAttribute('aria-label') ||
                    node.getAttribute('placeholder') ||
                    node.getAttribute('title') ||
                    ''
                );
                return (
                    label.includes('send a message') ||
                    label.includes('message everyone') ||
                    label.includes('in-call message') ||
                    label.includes('chat')
                );
            });

            const closeButtons = Array.from(document.querySelectorAll('button, [role="button"]')).some((node) => {
                if (!isVisible(node)) return false;
                const label = normalize(node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || '');
                return label.includes('close chat') || label.includes('close in-call messages');
            });

            return JSON.stringify({ open: hasMessageBox || closeButtons });
        }""",
    )
    return bool(result and result["open"])


async def open_chat_panel(page, session_id=None):
    if await is_chat_panel_open(page):
        log("Meet chat panel is already open.", session_id, level="debug")
        return True

    click_result = await evaluate_json(
        page,
        """() => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (node) => {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };

            const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
            const preferredPhrases = [
                'chat with everyone',
                'show everyone chat',
                'open chat',
                'in-call messages',
                'messages',
                'chat',
            ];

            for (const phrase of preferredPhrases) {
                const node = candidates.find((candidate) => {
                    if (!isVisible(candidate)) return false;
                    const label = normalize(candidate.getAttribute('aria-label') || candidate.getAttribute('title') || candidate.textContent || '').toLowerCase();
                    return label.includes(phrase);
                });
                if (node) {
                    node.click();
                    return JSON.stringify({
                        clicked: true,
                        label: normalize(node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || ''),
                    });
                }
            }

            return JSON.stringify({ clicked: false, label: '' });
        }""",
    )

    if click_result and click_result["clicked"]:
        log(
            f"Opened chat panel with selector match: {click_result['label']}",
            session_id,
            level="debug",
        )
        for _ in range(5):
            await asyncio.sleep(0.5)
            if await is_chat_panel_open(page):
                return True
    else:
        log("Chat button not found by selector. Trying keyboard shortcuts.", session_id, level="debug")
        for key_combo in ("Control+Alt+C", "Meta+Alt+C"):
            try:
                await page.press(key_combo)
                await asyncio.sleep(1)
                if await is_chat_panel_open(page):
                    log(f"Opened chat panel with keyboard shortcut: {key_combo}", session_id, level="debug")
                    return True
            except Exception as error:
                log(f"Chat shortcut {key_combo} failed: {error}", session_id, level="debug")

    await asyncio.sleep(1)
    return await is_chat_panel_open(page)


async def collect_visible_chat_messages(page):
    payload = await evaluate_json(
        page,
        """() => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
            const isVisible = (node) => {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };

            const rootSelectors = [
                '[aria-label*="in-call messages" i]',
                '[aria-label*="chat" i]',
                '[role="complementary"]',
                '[aria-live="polite"]',
                '[data-panel-container-id]',
            ];
            const messageSelectors = [
                '[role="listitem"]',
                '[data-message-id]',
                'article',
                'li',
            ];

            const roots = [];
            for (const selector of rootSelectors) {
                for (const node of document.querySelectorAll(selector)) {
                    if (!isVisible(node)) continue;
                    if (!roots.includes(node)) roots.push(node);
                }
            }

            const collectMessagesFromRoot = (root) => {
                const collected = [];
                const seen = new Set();
                const items = messageSelectors.flatMap((selector) => Array.from(root.querySelectorAll(selector)));

                for (const item of items) {
                    if (!isVisible(item)) continue;
                    const rawText = normalize(item.innerText || item.textContent || '');
                    if (!rawText) continue;

                    const lines = rawText
                        .split('\\n')
                        .map((line) => normalize(line))
                        .filter(Boolean);
                    if (!lines.length) continue;

                    const authorNode = item.querySelector('[data-sender-name], [data-participant-name], [aria-label*="from" i]');
                    const author = normalize(authorNode?.textContent || lines[0] || '');
                    const timestampNode = item.querySelector('time, [data-timestamp], [aria-label*="sent at" i]');
                    const timestampText = normalize(timestampNode?.textContent || '');
                    const normalizedText = normalize(lines.length > 1 ? lines.slice(1).join(' ') : lines[0]);
                    const fingerprint = [author, timestampText, normalizedText].join('|').toLowerCase();

                    if (!normalizedText || seen.has(fingerprint)) continue;
                    seen.add(fingerprint);
                    collected.push({
                        fingerprint,
                        raw_text: rawText,
                        normalized_text: normalizedText,
                        author,
                        timestamp_text: timestampText,
                    });
                }

                return collected;
            };

            let bestMessages = [];
            for (const root of roots) {
                const candidateMessages = collectMessagesFromRoot(root);
                if (candidateMessages.length > bestMessages.length) {
                    bestMessages = candidateMessages;
                }
            }

            return JSON.stringify(bestMessages);
        }""",
    )

    messages = []
    for item in payload or []:
        messages.append(
            ChatMessage(
                fingerprint=item["fingerprint"],
                raw_text=item["raw_text"],
                normalized_text=normalize_message_text(item["normalized_text"]),
                author=item["author"],
                timestamp_text=item["timestamp_text"],
            )
        )
    return messages


async def send_chat_message(page, message_text):
    focus_result = await evaluate_json(
        page,
        """(messageText) => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const isVisible = (node) => {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };

            const candidates = Array.from(
                document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"], [role="textbox"]')
            );

            const input = candidates.find((candidate) => {
                if (!isVisible(candidate)) return false;
                const label = normalize(
                    candidate.getAttribute('aria-label') ||
                    candidate.getAttribute('placeholder') ||
                    candidate.getAttribute('title') ||
                    ''
                );
                return (
                    label.includes('send a message') ||
                    label.includes('message everyone') ||
                    label.includes('in-call message') ||
                    label.includes('chat')
                );
            });

            if (!input) {
                return JSON.stringify({ focused: false });
            }

            input.focus();
            if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {
                input.value = messageText;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            } else {
                input.textContent = '';
                document.execCommand('insertText', false, messageText);
                if (!normalize(input.textContent).includes(normalize(messageText))) {
                    input.textContent = messageText;
                }
                input.dispatchEvent(new InputEvent('input', { bubbles: true, data: messageText, inputType: 'insertText' }));
            }

            return JSON.stringify({ focused: true });
        }""",
        message_text,
    )

    if not focus_result or not focus_result["focused"]:
        return False

    await asyncio.sleep(0.5)
    await page.press("Enter")
    await asyncio.sleep(0.5)

    send_result = await evaluate_json(
        page,
        """(messageText) => {
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const isVisible = (node) => {
                if (!node) return false;
                const style = window.getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };

            const sendButton = Array.from(document.querySelectorAll('button, [role="button"]')).find((node) => {
                if (!isVisible(node)) return false;
                const label = normalize(node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || '');
                return label.includes('send') && !node.disabled && node.getAttribute('aria-disabled') !== 'true';
            });

            if (sendButton) {
                sendButton.click();
                return JSON.stringify({ sent: true, method: 'button' });
            }

            const boxes = Array.from(
                document.querySelectorAll('textarea, input[type="text"], [contenteditable="true"], [role="textbox"]')
            );
            const messageStillInBox = boxes.some((box) => isVisible(box) && normalize(box.value || box.textContent || '').includes(normalize(messageText)));

            return JSON.stringify({ sent: !messageStillInBox, method: 'enter' });
        }""",
        message_text,
    )
    return True if send_result is None else bool(send_result.get("sent"))


async def send_introduction(page, state):
    if state.introduction_sent:
        return False

    intro_message = build_intro_message(state.display_name)
    sent = await send_chat_message(page, intro_message)
    if sent:
        state.introduction_sent = True
        log(f"Sent meeting introduction: {intro_message}", state.session_id, level="debug")
        return True

    log("Could not send the meeting introduction message.", state.session_id, level="debug")
    return False

def message_mentions_orbit(message):
    return bool(ORBIT_MENTION_PATTERN.search(message.normalized_text))


def is_orbit_authored_message(state, message):
    author = (message.author or "").strip().lower()
    raw_text = (message.raw_text or "").strip().lower()
    normalized_text = (message.normalized_text or "").strip().lower()
    display_name = (state.display_name or "").strip().lower()
    intro_text = build_intro_message(state.display_name).strip().lower()

    return (
        (display_name and display_name in author)
        or author in {"orbit", "orbit agent", "orbit (ai agent)"}
        or raw_text.startswith(intro_text)
        or normalized_text.startswith(intro_text)
    )


def grant_speak_permission(state, message):
    state.pending_speak_permissions += 1
    state.permission_events.append(
        PermissionEvent(
            granted_at=now_iso(),
            author=message.author,
            message_text=message.raw_text,
            fingerprint=message.fingerprint,
        )
    )
    log(
        "Speak permission granted by chat mention "
        f"(pending={state.pending_speak_permissions}): {message.raw_text}",
        state.session_id,
        level="debug",
    )


async def process_messages(page, state, messages, source, callbacks=None):
    new_messages = [
        message
        for message in messages
        if message.fingerprint not in state.seen_message_fingerprints
    ]
    if not new_messages:
        return

    for message in new_messages:
        state.seen_message_fingerprints.add(message.fingerprint)
        if is_orbit_authored_message(state, message):
            log(f"Ignoring Orbit-authored chat message ({source}).", state.session_id, level="debug")
            continue

        state.captured_messages.append(message)
        log(
            f"New chat message ({source}) from "
            f"{message.author or 'unknown'}: {message.raw_text}",
            state.session_id,
            level="debug",
        )
        await emit_chat_message(callbacks, state, message, source)
        if message_mentions_orbit(message):
            grant_speak_permission(state, message)
            reply = await emit_orbit_mention(callbacks, state, message)
            if reply:
                sent = await send_chat_message(page, reply)
                if sent:
                    log(f"Sent Orbit mention reply: {reply}", state.session_id, level="debug")
                else:
                    log("Could not send Orbit mention reply.", state.session_id, level="debug")


async def monitor_chat(page, state, wait_after_run_ms, callbacks=None):
    state.chat_monitor_started_at = now_iso()
    seen_caption_fingerprints = set()

    chat_open = await open_chat_panel(page, state.session_id)
    state.chat_monitor_available = chat_open
    if not chat_open:
        log(
            "Meet chat could not be opened. Monitoring disabled for this session.",
            state.session_id,
            level="important",
        )
        await emit_status(
            callbacks,
            state,
            "chat_monitor_unavailable",
            "Orbit joined, but Meet chat could not be opened.",
        )
    else:
        await send_introduction(page, state)
        initial_messages = await collect_visible_chat_messages(page)
        log(
            f"Scanned {len(initial_messages)} visible chat messages at monitor start.",
            state.session_id,
            level="debug",
        )
        await process_messages(page, state, initial_messages, "startup", callbacks)

    deadline = asyncio.get_running_loop().time() + (wait_after_run_ms / 1000)
    next_participant_check_at = 0.0
    while asyncio.get_running_loop().time() < deadline:
        if state.stop_requested:
            state.leave_reason = state.stop_reason or "Orbit was asked to stop monitoring this meeting."
            log(state.leave_reason, state.session_id, level="important")
            break
        now = asyncio.get_running_loop().time()
        if now >= next_participant_check_at:
            next_participant_check_at = now + (PARTICIPANT_CHECK_INTERVAL_MS / 1000)
            try:
                participant_count = await get_participant_count(page)
                if should_leave_when_only_orbit_remains(state, participant_count):
                    state.leave_reason = "Orbit is the only participant left in the meeting."
                    log(state.leave_reason, state.session_id, level="important")
                    break
            except Exception as error:
                log(f"Participant count check failed: {error}", state.session_id, level="debug")
        if chat_open:
            try:
                messages = await collect_visible_chat_messages(page)
                await process_messages(page, state, messages, "poll", callbacks)
            except Exception as error:
                log(f"Chat polling failed: {error}", state.session_id, level="debug")
        if state.live_stt_available:
            try:
                captions = await collect_visible_captions(page)
                new_captions = []
                for caption in captions:
                    fingerprint = f"{caption.speaker_name}|{caption.text}".lower()
                    if fingerprint in seen_caption_fingerprints:
                        continue
                    seen_caption_fingerprints.add(fingerprint)
                    new_captions.append(caption)
                if new_captions:
                    await emit_captions(callbacks, state, new_captions)
            except Exception as error:
                log(f"Caption scraping failed: {error}", state.session_id, level="debug")
        await asyncio.sleep(POLL_INTERVAL_MS / 1000)

    if state.leave_reason is None:
        state.leave_reason = "Meeting monitoring duration elapsed."
    log(
        "Chat monitor finished with "
        f"{state.pending_speak_permissions} pending speak permission(s).",
        state.session_id,
        level="info",
    )
