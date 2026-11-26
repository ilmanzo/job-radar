"""Talentadore positions feed (ats.talentadore.com/positions/<key>/json).

Target fields: board (company feed key, found in the career page's widget code).
"""

from typing import List

from radar.http import FetchError, http_get_json
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import strip_html
from radar.sources.base import BaseSource, parse_job_date


def parse_talentadore(data: dict, target: CompanyTarget) -> List[RawJob]:
    return [
        RawJob(
            id=f"ta_{target.id}_{j.get('id')}",
            company_id=target.id,
            title=j.get("name", ""),
            location=", ".join(x for x in (j.get("city"), j.get("country")) if x) or j.get("location", ""),
            url=j.get("link", ""),
            content=j.get("description_text") or strip_html(j.get("description_html", "")),
            posted_date=parse_job_date(j.get("start_date") or j.get("updated")),
        )
        for j in data.get("jobs", [])
        if j.get("id")
    ]


class TalentadoreSource(BaseSource):
    ats_name = "talentadore"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        if not target.board:
            raise FetchError(f"{target.id}: ats talentadore needs a board (feed key)")
        data = http_get_json(f"https://ats.talentadore.com/positions/{target.board}/json?v=2&language=fi,en,sv")
        if "jobs" not in data:
            raise FetchError(f"{target.id}: unexpected Talentadore response")
        return parse_talentadore(data, target)
