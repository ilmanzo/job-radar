"""SAP SuccessFactors Career Site Builder (served on <career site>/search/).

Target fields: url (career site root), search_text (optional keyword filter).
"""

import re
import time
import urllib.parse
from typing import List

from radar.http import FetchError, http_get_text
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import BROWSER_HEADERS, strip_html
from radar.sources.base import BaseSource

MAX_PAGES = 40
TOTAL_RE = re.compile(r"of\s*<b>\s*([0-9,]+)\s*</b>")


def parse_successfactors(page: str, base_url: str, target: CompanyTarget) -> List[RawJob]:
    """Search results as table rows or job tiles."""
    jobs, seen = [], set()
    for block in re.split(r'<tr class="data-row|<li class="job-tile', page)[1:]:
        m = re.search(r'href="([^"]*/job/[^"]+)"[^>]*class="jobTitle-link[^"]*"[^>]*>(.*?)</a>', block, re.S) or \
            re.search(r'class="jobTitle-link[^"]*"[^>]*href="([^"]*/job/[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        path, title = m.group(1), strip_html(m.group(2))
        jid = re.search(r"/(\d+)/?$", path)
        key = jid.group(1) if jid else path
        if key in seen:
            continue
        seen.add(key)
        loc = re.search(r'class="jobLocation[^"]*"[^>]*>(.*?)</span>', block, re.S) or \
            re.search(r'section-location-value">(.*?)</div>', block, re.S)
        jobs.append(RawJob(
            id=f"sf_{target.id}_{key}",
            company_id=target.id,
            title=title,
            location=strip_html(loc.group(1)) if loc else "",
            url=urllib.parse.urljoin(base_url, path),
            content="",
        ))
    return jobs


class SuccessFactorsSource(BaseSource):
    ats_name = "successfactors"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        base = target.extra.get("url", "").rstrip("/")
        if not base:
            raise FetchError(f"{target.id}: ats successfactors needs a url")
        query = urllib.parse.quote(target.search_text or "")
        jobs, seen, start = [], set(), 0
        for page_no in range(MAX_PAGES):
            page = http_get_text(f"{base}/search/?q={query}&startrow={start}", headers=BROWSER_HEADERS)
            total_m = TOTAL_RE.search(page)
            batch = [j for j in parse_successfactors(page, base + "/", target) if j.id not in seen]
            if not batch:
                total = int(total_m.group(1).replace(",", "")) if total_m else None
                if page_no == 0 and total != 0:
                    raise FetchError(f"{base}: no SuccessFactors job rows parsed (layout changed?)")
                break
            seen.update(j.id for j in batch)
            jobs.extend(batch)
            start += len(batch)
            if total_m and start >= int(total_m.group(1).replace(",", "")):
                break
            time.sleep(0.5)
        return jobs
