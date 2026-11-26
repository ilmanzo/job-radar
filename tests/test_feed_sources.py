"""Feed-based sources: parsers against synthetic fixtures shaped like the real feeds, plus the FetchError contract."""

import io
import json
import os
import unittest
from unittest.mock import patch

from radar.http import FetchError
from radar.models import CompanyTarget
from radar.sources import get_source
from radar.sources._feed import parse_rss, parse_xml
from radar.sources.eightfold import parse_eightfold
from radar.sources.jibe import parse_jibe
from radar.sources.oracle_orc import parse_oracle_orc
from radar.sources.personio import parse_personio
from radar.sources.successfactors import parse_successfactors
from radar.sources.talentadore import parse_talentadore

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
URLOPEN = "radar.http.urllib.request.urlopen"


def fixture(name, binary=False):
    with open(os.path.join(FIX, name), "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as f:
        return f.read()


def target(ats="rss", board="acme", **extra):
    return CompanyTarget(id="acme", name="Acme", ats=ats, board=board, extra=extra)


class FakeResp(io.BytesIO):
    def __init__(self, body, charset="utf-8"):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())
        self.headers = type("H", (), {"get_content_charset": lambda _self: charset})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def serve(body, charset="utf-8"):
    """A fresh response per call, so paging loops see a readable body every time."""
    return patch(URLOPEN, side_effect=lambda *a, **k: FakeResp(body, charset))


class TestParsers(unittest.TestCase):
    def test_teamtailor_rss(self):
        jobs = parse_rss(parse_xml(fixture("teamtailor.rss"), "x"), target(), "teamtailor")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].location, "Berlin, Germany; Munich, Germany (hybrid)")
        self.assertEqual(jobs[0].content, "Lead the & platform team")
        self.assertRegex(jobs[0].posted_date, r"^2026-11-19 ")

    def test_rss_default_location(self):
        jobs = parse_rss(parse_xml(fixture("plain.rss"), "x"), target(), "rss", default_location="Berlin, Germany")
        self.assertEqual([j.location for j in jobs], ["Berlin, Germany"])

    def test_non_utf8_feed_keeps_characters(self):
        raw = fixture("latin1.rss", binary=True)
        with serve(raw, charset="iso-8859-1"):
            jobs = get_source("rss").fetch(target(url="https://jobs.acme.example/feed"))
        self.assertEqual(jobs[0].title, "Stellenangebot Göttingen Ü")

    def test_successfactors(self):
        jobs = parse_successfactors(fixture("successfactors.html"), "https://careers.acme.example/", target())
        self.assertEqual([j.location for j in jobs], ["Berlin, DE", "Munich, DE", "Remote, DE"])
        self.assertTrue(all(j.url.startswith("https://careers.acme.example/job/") for j in jobs))

    def test_eightfold(self):
        jobs = parse_eightfold(json.loads(fixture("eightfold.json")), "https://jobs.acme.example", target())
        self.assertEqual(jobs[0].location, "Berlin, Berlin, Germany (hybrid)")
        self.assertEqual(jobs[1].location, "Munich, DE")
        self.assertEqual(jobs[0].url, "https://jobs.acme.example/careers/job/563121777429415")
        self.assertRegex(jobs[0].posted_date, r"^2026-")

    def test_oracle_orc(self):
        jobs = parse_oracle_orc(json.loads(fixture("oracle_orc.json")), "https://site.acme.example", target())
        self.assertEqual([j.location for j in jobs], ["Berlin, Germany (Hybrid)", "Munich, Germany"])
        self.assertEqual(jobs[0].content, "Lead R&D")

    def test_jibe(self):
        jobs = parse_jibe(json.loads(fixture("jibe.json")), "https://careers.acme.example", target())
        self.assertEqual([j.location for j in jobs], ["Berlin, Germany", "DE,Munich"])
        self.assertEqual(jobs[1].url, "https://careers.acme.example/careers-home/jobs/92469")
        self.assertRegex(jobs[0].posted_date, r"^2026-10-22 ")

    def test_personio_main_office_first_regardless_of_order(self):
        jobs = parse_personio(parse_xml(fixture("personio.xml"), "x"), target(board="acme"))
        self.assertEqual(jobs[0].location, "Berlin (hybrid); Remote (Deutschland)")
        self.assertEqual(jobs[0].content, "Lead the team")

    def test_talentadore_skips_records_without_id(self):
        jobs = parse_talentadore(json.loads(fixture("talentadore.json")), target())
        self.assertEqual([j.location for j in jobs], ["Berlin, Germany"])


class TestFetchContract(unittest.TestCase):
    """Broken or unexpected responses raise FetchError instead of returning a silent []."""

    def test_teamtailor_url(self):
        with serve(fixture("teamtailor.rss").encode()) as m:
            self.assertEqual(len(get_source("teamtailor").fetch(target("teamtailor", board="acme"))), 2)
        self.assertEqual(m.call_args[0][0].full_url, "https://acme.teamtailor.com/jobs.rss")

    def test_html_instead_of_rss_raises(self):
        with serve(b"<html><body>blocked</body></html>"), self.assertRaises(FetchError):
            get_source("rss").fetch(target(url="https://jobs.acme.example/feed"))

    def test_missing_required_fields_raise(self):
        for ats in ("rss", "successfactors", "jibe", "oracle_orc", "eightfold", "talentadore"):
            with self.assertRaises(FetchError, msg=ats):
                get_source(ats).fetch(target(ats, board=""))

    def test_unexpected_json_shapes_raise(self):
        cases = {
            "jibe": ({"error": "x"}, target("jibe", url="https://careers.acme.example")),
            "oracle_orc": ({"items": []}, target("oracle_orc", board="CX_1", url="https://orc.acme.example")),
            "eightfold": ({"status": 403, "data": None}, target("eightfold", board="acme.example", url="https://jobs.acme.example")),
            "talentadore": ({"unexpected": 1}, target("talentadore", board="key")),
        }
        for ats, (body, t) in cases.items():
            with serve(body), self.assertRaises(FetchError, msg=ats):
                get_source(ats).fetch(t)

    def test_successfactors_rows_unparsable_but_total_present_raises(self):
        page = b'<html>Results <b>1 - 25</b> of <b>140</b><table><tr class="data-row"><td>changed</td></tr></table></html>'
        with serve(page), self.assertRaises(FetchError):
            get_source("successfactors").fetch(target("successfactors", url="https://careers.acme.example"))

    def test_successfactors_unknown_layout_raises(self):
        with serve(b"<html>maintenance</html>"), self.assertRaises(FetchError):
            get_source("successfactors").fetch(target("successfactors", url="https://careers.acme.example"))

    def test_successfactors_real_zero_results(self):
        with serve(b"<html>Results <b>0 - 0</b> of <b>0</b></html>"):
            self.assertEqual(get_source("successfactors").fetch(target("successfactors", url="https://careers.acme.example")), [])

    def test_successfactors_stops_when_total_reached(self):
        with serve(fixture("successfactors.html").encode()) as m, patch("radar.sources.successfactors.time.sleep"):
            jobs = get_source("successfactors").fetch(target("successfactors", url="https://careers.acme.example"))
        self.assertEqual(len(jobs), 3)
        self.assertEqual(m.call_count, 1)

    def test_eightfold_reuses_cookie_opener(self):
        calls = []

        class Opener:
            def open(self, req, timeout=None):
                calls.append(req.full_url)
                return FakeResp(json.loads(fixture("eightfold.json")) if "/api/" in req.full_url else b"<html/>")

        with patch("radar.sources.eightfold.urllib.request.build_opener", return_value=Opener()), \
                patch("radar.sources.eightfold.time.sleep"):
            jobs = get_source("eightfold").fetch(target("eightfold", board="acme.example", url="https://jobs.acme.example"))
        self.assertEqual(len(jobs), 2)
        self.assertIn("/careers?domain=acme.example", calls[0])
        self.assertIn("/api/pcsx/search", calls[1])


if __name__ == "__main__":
    unittest.main()
