import unittest

from api_adapter import fetch_all_pages, post_json
from coding_feature import normalize_job_config

class QueueTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def __call__(self, method, url, payload, headers, timeout):
        self.calls.append((method, url, payload, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)

class CodingFixtureTests(unittest.TestCase):
    def test_valid_config_is_deterministic(self):
        raw = {"project_id":" P-42 ","timeout_s":45,"retries":1,
               "tags":["API","api"," QA "]}
        self.assertEqual(
            normalize_job_config(raw),
            {"project_id":"P-42","timeout_s":45,"retries":1,"tags":["api","qa"]}
        )
        self.assertEqual(raw["project_id"], " P-42 ")

    def test_unknown_key_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            normalize_job_config({"project_id":"P-42","shell":"rm -rf /"})

    def test_invalid_ranges_fail(self):
        with self.assertRaises(ValueError):
            normalize_job_config({"project_id":"P-42","timeout_s":0})
        with self.assertRaises(ValueError):
            normalize_job_config({"project_id":"P-42","retries":99})

class ApiFixtureTests(unittest.TestCase):
    def test_pagination_and_429_retry(self):
        t = QueueTransport([
            (429, {"error":"rate"}),
            (200, {"items":[{"id":"a"}],"next":"p2"}),
            (200, {"items":[{"id":"b"}],"next":None}),
        ])
        out = fetch_all_pages(t, "https://example.invalid/items", max_retries=2)
        self.assertEqual([x["id"] for x in out["items"]], ["a","b"])
        self.assertEqual(out["calls"], 3)

    def test_cursor_loop_fails_closed(self):
        t = QueueTransport([
            (200, {"items":[],"next":"same"}),
            (200, {"items":[],"next":"same"}),
        ])
        with self.assertRaisesRegex(RuntimeError, "cursor loop"):
            fetch_all_pages(t, "https://example.invalid/items")

    def test_schema_error_fails_closed(self):
        t = QueueTransport([(200, {"items":"not-a-list","next":None})])
        with self.assertRaisesRegex(ValueError, "items must be a list"):
            fetch_all_pages(t, "https://example.invalid/items")

    def test_post_reuses_idempotency_key_across_retry(self):
        t = QueueTransport([
            (503, {"error":"temporary"}),
            (201, {"id":"crm-123"}),
        ])
        out = post_json(
            t, "https://example.invalid/crm", {"name":"Ada"},
            idempotency_key="job-42", max_retries=2
        )
        self.assertEqual(out, {"id":"crm-123","calls":2})
        self.assertEqual(t.calls[0][3]["Idempotency-Key"], "job-42")
        self.assertEqual(t.calls[1][3]["Idempotency-Key"], "job-42")

    def test_post_without_idempotency_key_fails_before_transport(self):
        t = QueueTransport([])
        with self.assertRaisesRegex(ValueError, "idempotency_key required"):
            post_json(t, "https://example.invalid/crm", {}, idempotency_key="")
        self.assertEqual(t.calls, [])

    def test_non_https_fails(self):
        t = QueueTransport([])
        with self.assertRaisesRegex(ValueError, "https endpoint required"):
            fetch_all_pages(t, "http://example.invalid/items")

if __name__ == "__main__":
    unittest.main()
