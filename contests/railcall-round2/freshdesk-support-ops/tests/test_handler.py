import base64, importlib.util, json, pathlib, unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("freshdesk_handler",ROOT/"handlers"/"handler.py")
handler=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(handler)

class FakeResponse:
    def __init__(self,data,status=200,headers=None):
        self._data=json.dumps(data).encode(); self.status=status; self.headers=headers or {}
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self._data

class FreshdeskModuleTests(unittest.TestCase):
    def setUp(self):
        handler.__rc_helpers__={"vault_get":lambda provider:{"api_key":"sekret","domain":"acme"}}

    def test_manifest_has_eight_commands_and_airlocks_writes(self):
        m=json.loads((ROOT/"module.json").read_text())
        self.assertEqual(8,len(m["commands"]))
        e=[c["side_effects"] for c in m["commands"]]
        self.assertEqual(4,e.count("none")); self.assertEqual(4,e.count("external"))
        self.assertEqual(["*.freshdesk.com"],m["requires"]["network"])
        self.assertFalse(m["requires"]["subprocess"]); self.assertEqual([],m["requires"]["filesystem_writes"])

    @patch.object(handler,"urlopen")
    def test_list_uses_basic_auth_and_rate_metadata(self,mock_open):
        mock_open.return_value=FakeResponse([],headers={"X-RateLimit-Remaining":"88"})
        out=handler.freshdesk_list_tickets({"page":2,"per_page":25},{})
        req=mock_open.call_args.args[0]
        token=base64.b64encode(b"sekret:X").decode()
        self.assertEqual(f"Basic {token}",req.get_header("Authorization"))
        self.assertTrue(req.full_url.startswith("https://acme.freshdesk.com/api/v2/tickets?"))
        self.assertEqual(88,out["rate_limit"]["remaining"]); self.assertNotIn("sekret",json.dumps(out))

    def test_rejects_arbitrary_domain(self):
        handler.__rc_helpers__={"vault_get":lambda provider:{"api_key":"k","domain":"evil.example.com"}}
        with self.assertRaises(handler.FreshdeskError): handler.freshdesk_get_ticket({"ticket_id":1},{})

    def test_caps_per_page(self):
        with self.assertRaises(handler.FreshdeskError): handler.freshdesk_list_tickets({"per_page":101},{})

    @patch.object(handler,"urlopen")
    def test_create_ticket_payload(self,mock_open):
        mock_open.return_value=FakeResponse({"id":42},status=201)
        out=handler.freshdesk_create_ticket({"email":"user@example.com","subject":"Help","description":"Broken","priority":2,"status":2},{})
        req=mock_open.call_args.args[0]; payload=json.loads(req.data)
        self.assertEqual("POST",req.method); self.assertEqual("user@example.com",payload["email"]); self.assertEqual(42,out["data"]["id"])

    def test_update_requires_delta(self):
        with self.assertRaises(handler.FreshdeskError): handler.freshdesk_update_ticket({"ticket_id":9},{})

    @patch.object(handler,"urlopen")
    def test_rate_limit_retry_after_no_secret(self,mock_open):
        headers=Message(); headers["Retry-After"]="17"
        mock_open.side_effect=HTTPError("https://acme.freshdesk.com/api/v2/tickets",429,"rate",headers,None)
        with self.assertRaises(handler.FreshdeskRateLimitError) as ctx: handler.freshdesk_get_ticket({"ticket_id":1},{})
        self.assertIn("17",str(ctx.exception)); self.assertNotIn("sekret",str(ctx.exception))

    def test_handler_functions_match_command_ids(self):
        m=json.loads((ROOT/"module.json").read_text())
        for c in m["commands"]:
            fn=c["id"].replace(".","_").replace("-","_")
            self.assertTrue(callable(getattr(handler,fn,None)),fn)

if __name__=="__main__": unittest.main(verbosity=2)
