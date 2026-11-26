"""Generic RSS 2.0 job feed source (job portals, smaller ATSs and WordPress careers feeds that publish RSS).

Target fields: url (feed URL), location (optional default for feeds without locations).
"""

from typing import List

from radar.http import FetchError, http_get_text
from radar.models import CompanyTarget, RawJob
from radar.sources._feed import BROWSER_HEADERS, parse_rss, parse_xml
from radar.sources.base import BaseSource


class RssSource(BaseSource):
    ats_name = "rss"

    def feed_url(self, target: CompanyTarget) -> str:
        url = target.extra.get("url", "")
        if not url:
            raise FetchError(f"{target.id}: ats {self.ats_name} needs a url")
        return url

    def fetch(self, target: CompanyTarget) -> List[RawJob]:
        url = self.feed_url(target)
        root = parse_xml(http_get_text(url, headers=BROWSER_HEADERS), url)
        if root.find("channel") is None:
            raise FetchError(f"{url}: not an RSS feed")
        return parse_rss(root, target, self.ats_name, target.extra.get("location", ""))
