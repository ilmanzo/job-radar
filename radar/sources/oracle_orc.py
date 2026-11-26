"""Oracle Recruiting Cloud candidate experience sites (recruitingCEJobRequisitions REST API).

Target fields: url (REST host), board (site number, e.g. CX_1), search_text (location filter),
site_url (candidate site used for job links).
"""

import time
import urllib.parse
from typing import List

from radar.http import FetchError, http_get_json
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import strip_html
from radar.sources.base import BaseSource, parse_job_date

PAGE = 25
MAX_PAGES = 40


def parse_oracle_orc(data: dict, site_url: str, target: CompanyTarget) -> List[RawJob]:
    jobs = []
    for item in data.get("items", []):
        for r in item.get("requisitionList") or []:
            if not r.get("Id"):
                continue
            mode, loc = r.get("WorkplaceType") or "", r.get("PrimaryLocation", "")
            jobs.append(RawJob(
                id=f"orc_{target.id}_{r.get('Id')}",
                company_id=target.id,
                title=r.get("Title", ""),
                location=f"{loc} ({mode})" if mode else loc,
                url=f"{site_url.rstrip('/')}/job/{r.get('Id')}",
                content=strip_html(r.get("ShortDescriptionStr") or ""),
                posted_date=parse_job_date(r.get("PostedDate")),
            ))
    return jobs


class OracleOrcSource(BaseSource):
    ats_name = "oracle_orc"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        host = target.extra.get("url", "").rstrip("/")
        if not host or not target.board:
            raise FetchError(f"{target.id}: ats oracle_orc needs url and board")
        site_url = target.extra.get("site_url", host)
        loc = f",location={urllib.parse.quote(target.search_text)}" if target.search_text else ""
        jobs, offset = [], 0
        for _ in range(MAX_PAGES):
            url = (f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                   f"&expand=requisitionList&finder=findReqs;siteNumber={target.board},limit={PAGE},offset={offset}{loc}")
            data = http_get_json(url, headers={"Accept": "application/json"})
            items = data.get("items") if isinstance(data, dict) else None
            if not items or "requisitionList" not in items[0]:
                raise FetchError(f"{url}: unexpected Oracle Recruiting response")
            batch = parse_oracle_orc(data, site_url, target)
            if not batch:
                break
            jobs.extend(batch)
            offset += PAGE
            if offset >= int(items[0].get("TotalJobsCount") or 0):
                break
            time.sleep(0.5)
        return jobs
