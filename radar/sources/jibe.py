"""iCIMS Jibe career sites (served on <host>/api/jobs).

Target fields: url (career site host), search_text (location filter).
"""

import time
import urllib.parse
from typing import List

from radar.http import FetchError, http_get_json
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import strip_html
from radar.sources.base import BaseSource, parse_job_date

MAX_PAGES = 40


def parse_jibe(data: dict, host: str, target: CompanyTarget) -> List[RawJob]:
    jobs = []
    for j in data.get("jobs", []):
        d = j.get("data", j)
        jid = d.get("req_id") or d.get("slug")
        if not jid:
            continue
        jobs.append(RawJob(
            id=f"jibe_{target.id}_{jid}",
            company_id=target.id,
            title=d.get("title", ""),
            location=d.get("full_location") or d.get("location_name", ""),
            url=d.get("canonical_url") or f"{host}/careers-home/jobs/{d.get('slug')}",
            content=strip_html(d.get("description", "")),
            posted_date=parse_job_date((d.get("posted_date") or "").replace("+0000", "+00:00")),
        ))
    return jobs


class JibeSource(BaseSource):
    ats_name = "jibe"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        host = target.extra.get("url", "").rstrip("/")
        if not host:
            raise FetchError(f"{target.id}: ats jibe needs a url")
        loc = urllib.parse.quote(target.search_text or "")
        jobs = []
        for page in range(1, MAX_PAGES + 1):
            url = f"{host}/api/jobs?location={loc}&page={page}&limit=100"
            data = http_get_json(url)
            if not isinstance(data, dict) or "jobs" not in data:
                raise FetchError(f"{url}: unexpected Jibe response")
            batch = parse_jibe(data, host, target)
            if not batch:
                break
            jobs.extend(batch)
            if len(jobs) >= int(data.get("totalCount") or 0):
                break
            time.sleep(0.5)
        return jobs
