# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .dependencies import *


def clean_meet_link(raw_url):
    return raw_url.rstrip(").,!?:;]>\"'")


def extract_meet_links(text):
    urls = []
    for match in MEET_LINK_PATTERN.findall(text or ""):
        clean_url = clean_meet_link(match)
        if clean_url not in urls:
            urls.append(clean_url)
    return urls


def is_qna_message(text):
    return bool(QNA_TRIGGER_PATTERN.match(text or ""))


def strip_qna_trigger(text):
    return QNA_TRIGGER_PATTERN.sub("", text or "", count=1).strip()


def extract_meeting_codes(text):
    return [match.lower() for match in MEETING_CODE_PATTERN.findall(text or "")]


def format_twiml(message_text):
    response = MessagingResponse()
    if message_text:
        response.message(message_text)
    return str(response)
