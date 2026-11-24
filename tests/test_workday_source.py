"""Tests for Workday pagination handling."""

import json
import unittest
from unittest.mock import MagicMock, patch

from radar.models import CompanyTarget
from radar.sources.workday import WorkdaySource


def _page(offset, total, count):
    postings = [
        {"title": f"Job {offset + i}", "locationsText": "Helsinki", "externalPath": f"/job/Helsinki/Job_{offset + i}"}
        for i in range(count)
    ]
    resp = MagicMock()
    resp.read.return_value = json.dumps({"total": total, "jobPostings": postings}).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


class TestWorkdaySource(unittest.TestCase):
    def _fetch(self, pages, extra=None):
        target = CompanyTarget(id="acme", name="Acme", ats="workday", board="acme", extra=extra or {})
        with patch("radar.sources.workday.urllib.request.urlopen", side_effect=pages) as mock_open:
            jobs = WorkdaySource().fetch(target)
        return jobs, mock_open

    def test_total_only_reported_on_first_page(self):
        # Workday returns the real total on page one and 0 on later pages.
        pages = [_page(0, 50, 20), _page(20, 0, 20), _page(40, 0, 10)]
        jobs, mock_open = self._fetch(pages)
        self.assertEqual(len(jobs), 50)
        self.assertEqual(mock_open.call_count, 3)
        self.assertEqual(jobs[-1].id, "wd_acme_49")

    def test_max_jobs_caps_pages(self):
        pages = [_page(0, 500, 20), _page(20, 0, 20), _page(40, 0, 20)]
        jobs, mock_open = self._fetch(pages, extra={"max_jobs": 40})
        self.assertEqual(len(jobs), 40)
        self.assertEqual(mock_open.call_count, 2)


if __name__ == "__main__":
    unittest.main()
