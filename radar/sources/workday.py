"""Workday ATS source plugin."""

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import List

from radar.models import CompanyTarget, RawJob
from radar.sources.base import BaseSource


class WorkdaySource(BaseSource):
    ats_name = "workday"

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        tenant = target.board or target.id
        site = target.site or "jobs"
        sub_domain = target.sub_domain or "wd5"
        base_host = "myworkdayjobs.com"
        search_text = target.search_text or target.extra.get("search_text", "")

        url = f"https://{tenant}.{sub_domain}.{base_host}/wday/cxs/{tenant}/{site}/jobs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
        ssl_ctx = ssl.create_default_context()
        try:
            ssl_ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20")
        except Exception:
            pass

        jobs = []
        limit = 20
        offset = 0
        max_jobs = int((target.extra or {}).get("max_jobs", 100))
        max_pages = max(1, -(-max_jobs // limit))
        total = None

        for _ in range(max_pages):
            payload = json.dumps({
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": search_text,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=headers)
            data = None
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=20) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt == 0:
                        time.sleep(1.5)
                        continue
                    print(f"[-] Error fetching Workday ({tenant}): {e}", file=sys.stderr)
                    break
                except Exception as e:
                    print(f"[-] Error fetching Workday ({tenant}): {e}", file=sys.stderr)
                    break

            if not data:
                break

            postings = data.get("jobPostings", [])
            if not postings:
                break
            for item in postings:
                ext_path = item.get("externalPath", "")
                title = item.get("title", "")
                if not title or not ext_path:
                    continue

                loc = item.get("locationsText", "")
                remote_type = item.get("remoteType", "")
                path_loc = ext_path.split("/job/")[1].split("/")[0] if "/job/" in ext_path else ""
                combined_loc = f"{loc} - {path_loc}" if path_loc and path_loc != loc else loc
                full_loc = f"{combined_loc} ({remote_type})" if remote_type else combined_loc
                job_id = ext_path.split("_")[-1] if "_" in ext_path else ext_path
                job_prefix = target.id if target.id != tenant else tenant

                jobs.append(
                    RawJob(
                        id=f"wd_{job_prefix}_{job_id}",
                        company_id=target.id,
                        title=title,
                        location=full_loc,
                        url=f"https://{tenant}.{sub_domain}.{base_host}/en-US/{site}{ext_path}",
                        content="",
                    )
                )
            offset += limit
            # Workday only reports the real total on the first page; later pages say 0.
            if total is None:
                total = data.get("total") or 0
            if offset >= total:
                break
        return jobs
