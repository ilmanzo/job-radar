"""Eightfold career sites (PCSX search API, served on <host>/api/pcsx/search).

Target fields: url (career site host), board (the tenant domain, e.g. example.com),
search_text (location filter, e.g. a country name), careers_url (optional page that sets cookies).
"""

import http.cookiejar
import time
import urllib.parse
import urllib.request
from typing import List

from radar.http import FetchError, http_get_json, http_get_text
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import BROWSER_HEADERS
from radar.sources.base import BaseSource, parse_job_date

MAX_PAGES = 40


def parse_eightfold(data: dict, host: str, target: CompanyTarget) -> List[RawJob]:
    jobs = []
    for p in data["data"]["positions"]:
        if not p.get("id"):
            continue
        loc = "; ".join(dict.fromkeys(p.get("locations") or p.get("standardizedLocations") or []))
        mode = p.get("workLocationOption")
        jobs.append(RawJob(
            id=f"ef_{target.id}_{p.get('id')}",
            company_id=target.id,
            title=p.get("name", ""),
            location=f"{loc} ({mode})" if mode else loc,
            url=urllib.parse.urljoin(host, p.get("positionUrl", "")),
            content="",
            posted_date=parse_job_date(p.get("postedTs")),
        ))
    return jobs


class EightfoldSource(BaseSource):
    ats_name = "eightfold"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        host = target.extra.get("url", "").rstrip("/")
        if not host or not target.board:
            raise FetchError(f"{target.id}: ats eightfold needs url and board")
        # Some tenants answer the API with 429 until the careers page has set its cookies.
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            http_get_text(target.extra.get("careers_url") or f"{host}/careers?domain={target.board}",
                          headers=BROWSER_HEADERS, opener=opener)
        except FetchError:
            pass  # cookies are a best effort; the API call below decides
        loc = urllib.parse.quote(target.search_text or "")
        jobs, start = [], 0
        for _ in range(MAX_PAGES):
            url = f"{host}/api/pcsx/search?domain={target.board}&query=&location={loc}&start={start}"
            data = http_get_json(url, headers={**BROWSER_HEADERS, "Accept": "application/json"}, opener=opener)
            if not isinstance(data, dict) or not isinstance(data.get("data"), dict) or "positions" not in data["data"]:
                raise FetchError(f"{url}: unexpected Eightfold response")
            batch = parse_eightfold(data, host, target)
            if not batch:
                break
            jobs.extend(batch)
            start += len(batch)
            if start >= int(data["data"].get("count") or 0):
                break
            time.sleep(0.5)
        return jobs
