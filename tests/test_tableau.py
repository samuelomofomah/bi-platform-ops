import tempfile
import unittest
from pathlib import Path

from biops.tableau import TableauClient
from tests.fakes import FakeResponse, FakeSession

INFO = FakeResponse({"serverInfo": {"productVersion": {"value": "2025.1.4"}, "restApiVersion": "3.25"}})
SIGNIN = FakeResponse({"credentials": {"site": {"id": "site-1"}, "token": "tok"}})


def workbooks_page(kwargs):
    page = kwargs["params"]["pageNumber"]
    ids = range(100) if page == 1 else range(100, 130)
    books = [{"id": f"wb-{i:04d}-xxxx", "name": f"Book {i}", "project": {"name": "Finance"}} for i in ids]
    return FakeResponse({"pagination": {"totalAvailable": "130"}, "workbooks": {"workbook": books}})


class TableauClientTest(unittest.TestCase):
    def client(self, extra=None):
        routes = {("GET", "/api/2.4/serverinfo"): INFO, ("POST", "/auth/signin"): SIGNIN,
                  ("POST", "/auth/signout"): FakeResponse()}
        session = FakeSession({**routes, **(extra or {})})
        return TableauClient("https://tab.example.com/", "", "name", "secret", session=session), session

    def test_sign_in_uses_server_api_version_and_sets_token(self):
        client, session = self.client()
        client.connect()
        self.assertEqual(client.api_version, "3.25")
        self.assertEqual(session.headers["X-Tableau-Auth"], "tok")
        self.assertTrue(any(u.endswith("/api/3.25/auth/signin") for _, u, _ in session.calls))

    def test_health_reports_failure_instead_of_raising(self):
        client, _ = self.client({("POST", "/auth/signin"): FakeResponse(status=401)})
        checks = {c["check_name"]: c["status"] for c in client.health()}
        self.assertEqual(checks, {"server_reachable": "ok", "pat_sign_in": "fail"})

    def test_inventory_follows_pagination(self):
        client, _ = self.client({
            ("GET", "/sites/site-1/workbooks"): workbooks_page,
            ("GET", "/sites/site-1/datasources"): FakeResponse({"pagination": {"totalAvailable": "0"}, "datasources": {}}),
        })
        client.connect()
        rows = client.inventory()
        self.assertEqual(len(rows), 130)
        self.assertEqual(rows[0]["project"], "Finance")

    def test_usage_maps_view_counts_to_parent_workbook(self):
        views = {"pagination": {"totalAvailable": "1"}, "views": {"view": [
            {"id": "v1", "name": "Overview", "workbook": {"id": "wb1"}, "usage": {"totalViewCount": "250"}}]}}
        client, _ = self.client({("GET", "/sites/site-1/views"): FakeResponse(views)})
        client.connect()
        self.assertEqual(client.usage(), [
            {"platform": "tableau", "object_id": "v1", "name": "Overview", "parent_id": "wb1", "total_views": 250}])

    def test_backup_keeps_going_when_one_download_fails(self):
        books = {"pagination": {"totalAvailable": "2"}, "workbooks": {"workbook": [
            {"id": "good0000", "name": "Good One", "project": {"name": "Finance"}},
            {"id": "bad00000", "name": "Bad One", "project": {"name": "Finance"}}]}}
        good = FakeResponse(headers={"Content-Disposition": 'name="tableau_workbook"; filename="Good.twbx"'}, content=b"zipbytes")
        client, _ = self.client({
            ("GET", "/sites/site-1/workbooks"): FakeResponse(books),
            ("GET", "/workbooks/good0000/content"): good,
            ("GET", "/workbooks/bad00000/content"): FakeResponse(status=500),
        })
        client.connect()
        with tempfile.TemporaryDirectory() as tmp:
            rows = client.backup(Path(tmp))
            self.assertEqual([r["status"] for r in rows], ["ok", "fail"])
            self.assertEqual(Path(rows[0]["path"]).read_bytes(), b"zipbytes")
            self.assertTrue(rows[0]["path"].endswith(".twbx"))


if __name__ == "__main__":
    unittest.main()
