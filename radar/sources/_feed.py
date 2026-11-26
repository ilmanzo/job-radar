"""Shared helpers for feed-based source plugins (RSS/XML/HTML job feeds)."""

import email.utils
import html
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from radar.http import FetchError
from radar.models import CompanyTarget, RawJob
from radar.sources.base import parse_job_date

# Some career sites answer bot user agents with an empty page or a block.
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}


def strip_html(text: Optional[str]) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def rfc822_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return parse_job_date(value)


def parse_xml(text: str, url: str) -> ET.Element:
    try:
        # Parse the decoded str: re-encoding to UTF-8 would clash with a non-UTF-8 XML declaration.
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise FetchError(f"{url}: invalid XML: {e}") from e


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rss(root: ET.Element, target: CompanyTarget, prefix: str, default_location: str = "") -> List[RawJob]:
    """RSS 2.0 items. Teamtailor tt:city / tt:country location tags are understood."""
    jobs = []
    for item in root.iter("item"):
        fields: Dict[str, str] = {}
        cities, countries = [], []
        for el in item.iter():
            name, text = _local(el.tag), (el.text or "").strip()
            if name == "city" and text:
                cities.append(text)
            elif name == "country" and text:
                countries.append(text)
            elif text and name not in fields:
                fields[name] = text
        title, link = fields.get("title", ""), fields.get("link", "")
        if not title or not link:
            continue
        places = [f"{c}, {countries[i]}" if i < len(countries) else c for i, c in enumerate(dict.fromkeys(cities))]
        location = "; ".join(places) or fields.get("location", "") or (countries[0] if countries else "") or default_location
        remote = fields.get("remoteStatus")
        if remote and remote.lower() not in ("none", "false"):
            location = f"{location} ({remote})" if location else remote
        guid = fields.get("guid") or link
        jobs.append(RawJob(
            id=f"{prefix}_{target.id}_{re.sub(r'[^A-Za-z0-9]+', '', guid)[-40:]}",
            company_id=target.id,
            title=title,
            location=location,
            url=link,
            content=strip_html(fields.get("description", "")),
            posted_date=rfc822_date(fields.get("pubDate")),
        ))
    return jobs
