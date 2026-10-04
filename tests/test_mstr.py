import unittest

from biops.mstr import MstrClient
from tests.fakes import FakeResponse, FakeSession

LOGIN = FakeResponse(status=204, headers={"X-MSTR-AuthToken": "abc"})
NODES = FakeResponse({"nodes": [{"name": "node1", "status": "running", "projects": [
    {"id": "p1", "name": "Enterprise", "status": "loaded"},
    {"id": "p2", "name": "Marketing", "status": "unloaded"}]}]})


def search(kwargs):
    project, type_code = kwargs["headers"]["X-MSTR-ProjectID"], kwargs["params"]["type"]
    if project == "p1" and type_code == 3:
        return FakeResponse({"totalItems": 1, "result": [
            {"id": "r1", "name": "Daily GMV", "owner": {"name": "Admin"}, "dateModified": "2026-09-01T00:00:00.000+0000"}]})
    return FakeResponse({"totalItems": 0, "result": []})


class MstrClientTest(unittest.TestCase):
    def client(self, extra=None):
        routes = {("GET", "/api/status"): FakeResponse({"upTimeText": "184 Hours 48 Minutes", "isIServerConfigured": True}),
                  ("POST", "/api/auth/login"): LOGIN, ("POST", "/api/auth/logout"): FakeResponse(status=204)}
        session = FakeSession({**routes, **(extra or {})})
        return MstrClient("https://mstr.example.com/MicroStrategyLibrary", "svc", "pw", session=session), session

    def test_health_flags_an_unloaded_project(self):
        client, session = self.client({("GET", "/api/monitors/iServer/nodes"): NODES})
        checks = {c["check_name"]: c["status"] for c in client.health()}
        self.assertEqual(session.headers["X-MSTR-AuthToken"], "abc")
        self.assertEqual(checks["node:node1"], "ok")
        self.assertEqual(checks["project:Enterprise@node1"], "ok")
        self.assertEqual(checks["project:Marketing@node1"], "fail")

    def test_health_reports_uptime_and_guest_login(self):
        client, _ = self.client({("GET", "/api/monitors/iServer/nodes"): NODES})
        client.user = ""
        details = {c["check_name"]: c["detail"] for c in client.health()}
        self.assertEqual(details["library_reachable"], "up 184 Hours 48 Minutes")
        self.assertEqual(details["login"], "logged in as guest")

    def test_health_fails_when_no_intelligence_server_is_configured(self):
        client, _ = self.client({("GET", "/api/status"): FakeResponse({"isIServerConfigured": False})})
        self.assertEqual(client.health()[0]["status"], "fail")

    def test_health_stops_after_failed_login(self):
        client, _ = self.client({("POST", "/api/auth/login"): FakeResponse(status=401)})
        self.assertEqual([c["status"] for c in client.health()], ["ok", "fail"])

    def test_inventory_searches_each_project_with_its_header(self):
        client, _ = self.client({
            ("GET", "/api/projects"): FakeResponse([{"id": "p1", "name": "Enterprise"}, {"id": "p2", "name": "Marketing"}]),
            ("GET", "/api/searches/results"): search})
        client.connect()
        rows = client.inventory()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["object_type"], rows[0]["project"], rows[0]["owner"]), ("report", "Enterprise", "Admin"))

    def test_refresh_posts_cube_publish_with_project_header(self):
        client, session = self.client({("POST", "/api/v2/cubes/cube9"): FakeResponse(status=202)})
        client.connect()
        rows = client.refresh(["p1:cube9", "malformed"])
        self.assertEqual([r["status"] for r in rows], ["ok", "fail"])
        _, _, kwargs = next(c for c in session.calls if c[1].endswith("/api/v2/cubes/cube9"))
        self.assertEqual(kwargs["headers"], {"X-MSTR-ProjectID": "p1"})


if __name__ == "__main__":
    unittest.main()
