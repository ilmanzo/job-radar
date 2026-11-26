"""Teamtailor career sites, read from their public RSS feed.

Target fields: board (the <board>.teamtailor.com subdomain) or url (feed URL on a custom domain).
"""

from radar.models import CompanyTarget
from radar.sources.rss import RssSource


class TeamtailorSource(RssSource):
    ats_name = "teamtailor"

    def feed_url(self, target: CompanyTarget) -> str:
        return target.extra.get("url") or f"https://{target.board or target.id}.teamtailor.com/jobs.rss"
