"""Tests for the Teamtailor RSS source plugin."""

import unittest
from unittest.mock import MagicMock, patch

from radar.models import CompanyTarget
from radar.sources import get_source
from radar.sources.teamtailor import feed_url, parse_feed

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel>
    <title>Example Ltd</title>
    <item>
      <title>Release Manager</title>
      <description>&lt;p&gt;Own &lt;strong&gt;Linux&lt;/strong&gt; releases &amp;amp; packaging.&lt;/p&gt;</description>
      <pubDate>Wed, 04 Nov 2026 11:24:41 +0200</pubDate>
      <link>https://example.teamtailor.com/jobs/123-release-manager</link>
      <remoteStatus>hybrid</remoteStatus>
      <guid>abc-123</guid>
      <tt:locations>
        <tt:location>
          <tt:name>Cambridge</tt:name>
          <tt:city>Cambridge</tt:city>
          <tt:country>United Kingdom</tt:country>
        </tt:location>
        <tt:location>
          <tt:name>Berlin</tt:name>
          <tt:city>Berlin</tt:city>
          <tt:country>Germany</tt:country>
        </tt:location>
      </tt:locations>
      <tt:department>Platform</tt:department>
    </item>
    <item>
      <title>Remote Engineer</title>
      <description></description>
      <link>https://example.teamtailor.com/jobs/456-remote-engineer</link>
      <remoteStatus>fully</remoteStatus>
      <guid>def-456</guid>
    </item>
  </channel>
</rss>
"""


class TestTeamtailorSource(unittest.TestCase):
    def setUp(self):
        self.target = CompanyTarget(id="example", name="Example Ltd", ats="teamtailor", board="example")

    def test_feed_url_from_slug_or_host(self):
        self.assertEqual(feed_url("acme"), "https://acme.teamtailor.com/jobs.rss")
        self.assertEqual(feed_url("careers.example.com"), "https://careers.example.com/jobs.rss")
        self.assertEqual(feed_url("https://jobs.example.org/jobs.rss"), "https://jobs.example.org/jobs.rss")

    def test_parse_feed(self):
        jobs = parse_feed(FEED, self.target)
        self.assertEqual(len(jobs), 2)
        first = jobs[0]
        self.assertEqual(first.id, "tt_example_abc-123")
        self.assertEqual(first.company_id, "example")
        self.assertEqual(first.title, "Release Manager")
        self.assertEqual(first.location, "Cambridge, United Kingdom; Berlin, Germany (hybrid)")
        self.assertEqual(first.url, "https://example.teamtailor.com/jobs/123-release-manager")
        self.assertEqual(first.posted_date, "2026-11-04 11:24:41")
        self.assertIn("Department: Platform", first.content)
        self.assertIn("Own Linux releases & packaging.", first.content)
        self.assertNotIn("<", first.content)

        second = jobs[1]
        self.assertEqual(second.location, "fully")
        self.assertIsNone(second.posted_date)

    def test_registered_and_fetch_handles_errors(self):
        source = get_source("teamtailor")
        self.assertIsNotNone(source)
        with patch("radar.sources.teamtailor.urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertEqual(source.fetch(self.target), [])

        resp = MagicMock()
        resp.read.return_value = FEED.encode("utf-8")
        resp.__enter__.return_value = resp
        with patch("radar.sources.teamtailor.urllib.request.urlopen", return_value=resp) as mock_open:
            jobs = source.fetch(self.target)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(mock_open.call_args[0][0].full_url, "https://example.teamtailor.com/jobs.rss")


if __name__ == "__main__":
    unittest.main()
