"""Custom career site source plugins for Amazon, Dynatrace, Proxmox, and Sidero."""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List
from urllib.parse import quote_plus

from radar.config import get_location_config
from radar.http import FetchError, http_get_json, http_get_text
from radar.models import CompanyTarget, RawJob
from radar.sources.base import BaseSource, parse_job_date

AMAZON_COUNTRY_CODES: Dict[str, str] = {
    "italy": "ITA",
    "germany": "DEU",
    "france": "FRA",
    "spain": "ESP",
    "united kingdom": "GBR",
    "uk": "GBR",
    "austria": "AUT",
    "ireland": "IRL",
    "poland": "POL",
    "netherlands": "NLD",
    "canada": "CAN",
    "united states": "USA",
    "us": "USA",
}


class AmazonSource(BaseSource):
    ats_name = "amazon"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        loc_cfg = get_location_config()
        home_country = loc_cfg["home_country"].lower()
        country_code = AMAZON_COUNTRY_CODES.get(home_country)

        # Search terms come from the target (`queries`: global; `country_queries`: home country only).
        base = "https://www.amazon.jobs/en/search.json?result_limit=50"
        queries = [f"{base}&base_query={quote_plus(t)}" for t in target.extra.get("queries") or []]
        if country_code:  # unknown country: skip country-scoped queries
            queries.append(f"{base}&country={country_code}&category[]=software-development")
            queries += [
                f"{base}&country={country_code}&base_query={quote_plus(t)}"
                for t in target.extra.get("country_queries") or []
            ]
        jobs_by_id = {}
        for q_url in queries:  # any failing query raises: a partial result would deactivate the rest
            data = http_get_json(q_url, timeout=15)
            for item in data.get("jobs", []):
                icims_id = item.get("id_icims")
                if not icims_id:
                    continue
                jid = f"amazon_{icims_id}"
                if jid in jobs_by_id:
                    continue
                loc = item.get("location", "")
                norm_loc = item.get("normalized_location", "")
                country = item.get("country_code", "")
                if country == country_code or home_country in norm_loc.lower():
                    full_loc = f"{loc}, {home_country.capitalize()}"
                else:
                    full_loc = f"{loc} ({norm_loc})" if norm_loc and norm_loc != loc else loc

                desc = item.get("description", "") or ""
                basic = item.get("basic_qualifications", "") or ""
                pref = item.get("preferred_qualifications", "") or ""

                jobs_by_id[jid] = RawJob(
                    id=jid,
                    company_id=target.id,
                    title=item.get("title", ""),
                    location=full_loc,
                    url=f"https://www.amazon.jobs{item.get('job_path', '')}",
                    content=f"{desc}\n{basic}\n{pref}",
                    posted_date=parse_job_date(item.get("posted_date")),
                )

        return list(jobs_by_id.values())


class DynatraceSource(BaseSource):
    ats_name = "dynatrace"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        url_base = "https://apply.careers.dynatrace.com/search/"
        jobs = []
        startrow = 0
        per_page = 25
        max_pages = 40  # safety stop (1000 postings)

        for _ in range(max_pages):
            html_text = http_get_text(f"{url_base}?q=&startrow={startrow}")
            tiles = re.findall(
                r'<li class="job-tile job-id-(\d+)[^"]*" data-url="([^"]+)".*?'
                r'<a class="jobTitle-link[^"]*"[^>]*>(.*?)</a>.*?'
                r'<div id="job-\d+-desktop-section-location-value">(.*?)</div>',
                html_text,
                re.DOTALL,
            )
            if not tiles:
                break
            for jid, url_path, title, loc in tiles:
                jobs.append(
                    RawJob(
                        id=f"dynatrace_{jid}",
                        company_id=target.id,
                        title=html.unescape(title).strip(),
                        location=html.unescape(loc).strip(),
                        url=f"https://apply.careers.dynatrace.com{url_path}",
                        content="",
                    )
                )
            startrow += per_page
        if not jobs:
            # shortcut: zero parsed tiles is treated as a layout change, not "no openings"
            raise FetchError("Dynatrace: no postings parsed; page layout changed?")
        return jobs


class SideroSource(BaseSource):
    ats_name = "sidero"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        page = http_get_text("https://www.siderolabs.com/careers/")
        cards = re.findall(
            r'<a class="careers-positions__row" href="(/careers/[^"/]+/?)"[^>]*>'
            r'<span class="careers-positions__job">'
            r'<span class="careers-positions__job-title">(.*?)</span>'
            r'<span class="careers-positions__job-meta[^"]*">(.*?)</span>',
            page,
            re.DOTALL,
        )
        if cards:
            parsed = []
            for path, title, meta in cards:
                clean_title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
                clean_meta = html.unescape(re.sub(r"<!--.*?-->|<[^>]+>", "", meta)).strip()
                parsed.append((path, clean_title, clean_meta))
        else:
            legacy_cards = re.findall(
                r'href="(/careers/[^"/]+/)"[^>]*class="[^"]*rd-vacancy-card[^"]*"[^>]*>(.*?)</a>',
                page,
                re.DOTALL,
            )
            if not legacy_cards:
                raise FetchError("Sidero Labs: no vacancy cards parsed; page layout changed?")
            parsed = []
            for path, inner in legacy_cards:
                title_m = re.search(r'<h3[^>]*>(.*?)</h3>', inner)
                meta_tags = re.findall(r'<span class="rd-vacancy-card__tag">(.*?)</span>', inner)
                title = html.unescape(title_m.group(1)).strip() if title_m else ""
                loc = html.unescape(meta_tags[1]).strip() if len(meta_tags) > 1 else (meta_tags[0].strip() if meta_tags else "")
                parsed.append((path, title, loc))

        def detail_text(job_url: str) -> str:  # best-effort job text
            try:
                sub_page = http_get_text(job_url, timeout=10)
            except FetchError:
                return ""
            clean = re.sub(r"<style[^>]*>.*?</style>", "", sub_page, flags=re.DOTALL)
            clean = re.sub(r"<script[^>]*>.*?</script>", "", clean, flags=re.DOTALL)
            return " ".join(re.sub(r"<[^>]+>", " ", clean).split())

        urls = [f"https://www.siderolabs.com{path}" for path, _, _ in parsed]
        with ThreadPoolExecutor(max_workers=8) as pool:
            contents = list(pool.map(detail_text, urls))

        jobs = []
        for (path, title, loc), job_url, content in zip(parsed, urls, contents):
            jobs.append(
                RawJob(
                    id=f"sidero_{path.strip('/').split('/')[-1]}",
                    company_id=target.id,
                    title=title,
                    location=loc,
                    url=job_url,
                    content=content,
                )
            )
        return jobs


class ProxmoxSource(BaseSource):
    ats_name = "proxmox"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        page = http_get_text("https://www.proxmox.com/en/about/careers")
        jobs = []
        sections = re.split(r"(<h2[^>]*>.*?</h2>)", page)
        for i in range(1, len(sections), 2):
            h2_tag = sections[i]
            chunk = sections[i + 1] if i + 1 < len(sections) else ""
            title = re.sub(r"<[^>]+>", "", h2_tag).strip()
            if not any(k in title for k in ["(m/f/d)", "(Canada)", "Developer", "Engineer", "Manager", "Specialist", "Representative"]):
                continue

            loc = "Vienna, Austria"
            if "Canada" in title or "Kingston" in chunk[:500]:
                loc = "Kingston, Ontario, Canada"
            elif "Remote" in chunk[:500]:
                loc = "Remote / Vienna, Austria"

            clean = re.sub(r"<style[^>]*>.*?</style>", "", chunk, flags=re.DOTALL)
            clean = re.sub(r"<script[^>]*>.*?</script>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean_content = " ".join(clean.split())

            slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
            jobs.append(
                RawJob(
                    id=f"proxmox_{slug}",
                    company_id=target.id,
                    title=title,
                    location=loc,
                    url="https://www.proxmox.com/en/about/careers",
                    content=f"{title}\n{clean_content[:2000]}",
                )
            )
        if not jobs:
            # shortcut: zero parsed postings is treated as a layout change, not "no openings"
            raise FetchError("Proxmox: no postings parsed; page layout changed?")
        return jobs

