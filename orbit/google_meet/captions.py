# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *
from .dom import evaluate_json


async def enable_captions(page, session_id=None):
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
            const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
            const captionsButton = buttons.find((node) => {
                if (!isVisible(node)) return false;
                const label = normalize(node.getAttribute('aria-label') || node.getAttribute('title') || node.textContent || '');
                return (
                    label.includes('turn on captions') ||
                    label.includes('show captions') ||
                    label === 'captions' ||
                    label.includes('captions off')
                );
            });
            if (!captionsButton) return JSON.stringify({ clicked: false, label: '' });
            captionsButton.click();
            return JSON.stringify({
                clicked: true,
                label: captionsButton.getAttribute('aria-label') || captionsButton.getAttribute('title') || captionsButton.textContent || ''
            });
        }""",
    )
    if result and result.get("clicked"):
        log(
            f"Requested Meet captions with selector match: {result.get('label')}",
            session_id,
            level="debug",
        )
        return True

    log(
        "Could not find a visible Meet captions control. Caption attribution will remain disabled.",
        session_id,
        level="debug",
    )
    return False


async def collect_visible_captions(page):
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
            const roots = Array.from(document.querySelectorAll(
                '[aria-live="polite"], [aria-live="assertive"], [role="region"], [data-self-name]'
            )).filter(isVisible);
            const snippets = [];
            const seen = new Set();

            for (const root of roots) {
                const rawText = normalize(root.innerText || root.textContent || '');
                if (!rawText || rawText.length < 4) continue;
                const lines = rawText.split('\\n').map(normalize).filter(Boolean);
                if (!lines.length) continue;

                let speakerName = '';
                let text = '';
                const speakerNode = root.querySelector('[data-self-name], [data-participant-name], [aria-label*="speaker" i]');
                if (speakerNode) {
                    speakerName = normalize(speakerNode.textContent || speakerNode.getAttribute('aria-label') || '');
                    text = normalize(lines.filter((line) => line !== speakerName).join(' '));
                } else if (lines.length >= 2 && lines[0].length <= 60) {
                    speakerName = lines[0];
                    text = normalize(lines.slice(1).join(' '));
                }

                if (!speakerName || !text || text.length < 4) continue;
                const key = `${speakerName}|${text}`.toLowerCase();
                if (seen.has(key)) continue;
                seen.add(key);
                snippets.push({ speaker_name: speakerName, text });
            }

            return JSON.stringify(snippets.slice(-10));
        }""",
    )

    return [
        CaptionSnippet(
            speaker_name=item["speaker_name"],
            text=item["text"],
        )
        for item in payload or []
        if item.get("speaker_name") and item.get("text")
    ]
