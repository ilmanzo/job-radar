"""Teamtailor ATS source plugin (public jobs.rss feed)."""

import email.utils
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from radar.models import CompanyTarget, RawJob
from radar.sources.base import BaseSource

TT_NS = "{https://teamtailor.com/locations}"


def feed_url(board: str) -> str:
    """Build the RSS URL from a slug ('acme') or a custom careers host ('careers.example.com')."""
    board = board.strip().rstrip("/")
    board = re.sub(r"^https?://", "", board)
    if board.endswith("/jobs.rss"):
        board = board[: -len("/jobs.rss")]
    host = board if "." in board else f"{board}.teamtailor.com"
    return f"https://{host}/jobs.rss"


def _rfc822_to_str(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _html_to_text(value: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _location(item: ET.Element) -> str:
    parts: List[str] = []
    for loc in item.iter(f"{TT_NS}location"):
        name = (loc.findtext(f"{TT_NS}name") or "").strip()
        city = (loc.findtext(f"{TT_NS}city") or "").strip()
        country = (loc.findtext(f"{TT_NS}country") or "").strip()
        bits = [b for b in (name, city if city != name else "", country) if b]
        label = ", ".join(dict.fromkeys(bits))
        if label and label not in parts:
            parts.append(label)
    remote = (item.findtext("remoteStatus") or "").strip()
    loc_text = "; ".join(parts)
    if remote and remote.lower() != "none":
        loc_text = f"{loc_text} ({remote})" if loc_text else remote
    return loc_text


def parse_feed(xml_text: str, target: CompanyTarget) -> List[RawJob]:
    root = ET.fromstring(xml_text)
    jobs = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        department = (item.findtext(f"{TT_NS}department") or "").strip()
        content = _html_to_text(item.findtext("description") or "")
        if department:
            content = f"Department: {department}\n{content}"
        jobs.append(
            RawJob(
                id=f"tt_{target.board or target.id}_{guid}",
                company_id=target.id,
                title=(item.findtext("title") or "").strip(),
                location=_location(item),
                url=link,
                content=content,
                posted_date=_rfc822_to_str(item.findtext("pubDate")),
            )
        )
    return jobs


class TeamtailorSource(BaseSource):
    ats_name = "teamtailor"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        url = feed_url(target.board or target.id)
        req = urllib.request.Request(url, headers={"User-Agent": "JobRadar/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return parse_feed(resp.read().decode("utf-8"), target)
        except Exception as e:
            print(f"[-] Error fetching Teamtailor ({url}): {e}", file=sys.stderr)
            return []
