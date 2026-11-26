"""Personio job pages, read from the public XML feed (<board>.jobs.personio.de/xml).

Target fields: board (Personio subdomain).
"""

from typing import List

from radar.http import FetchError, http_get_text
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import parse_xml, strip_html
from radar.sources.base import BaseSource, parse_job_date


def parse_personio(root, target: CompanyTarget) -> List[RawJob]:
    jobs = []
    for pos in root.iter("position"):
        def get(tag):
            return (pos.findtext(tag) or "").strip()
        # Main office first, then additionalOffices, whatever their order in the XML.
        offices = [get("office")] + [(o.text or "").strip() for o in pos.iter("office")]
        jid = get("id")
        jobs.append(RawJob(
            id=f"personio_{target.id}_{jid}",
            company_id=target.id,
            title=get("name"),
            location="; ".join(dict.fromkeys(o for o in offices if o)),
            url=f"https://{target.board or target.id}.jobs.personio.de/job/{jid}",
            content=" ".join(strip_html(v.findtext("value") or "") for v in pos.iter("jobDescription")),
            posted_date=parse_job_date(get("createdAt")),
        ))
    return jobs


class PersonioSource(BaseSource):
    ats_name = "personio"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        url = f"https://{target.board or target.id}.jobs.personio.de/xml"
        root = parse_xml(http_get_text(url), url)
        if root.tag != "workzag-jobs":
            raise FetchError(f"{url}: not a Personio feed")
        return parse_personio(root, target)
