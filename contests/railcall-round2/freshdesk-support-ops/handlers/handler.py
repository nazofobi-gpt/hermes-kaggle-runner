"""RailCall Freshdesk support-operations module."""
from __future__ import annotations
import base64, json, re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
_MAX_ERROR_CHARS = 1200
_MAX_BODY_CHARS = 100_000

class FreshdeskError(RuntimeError): pass
class FreshdeskRateLimitError(FreshdeskError): pass

def _vault_credentials():
    helpers = globals().get("__rc_helpers__")
    if not isinstance(helpers, Mapping) or not callable(helpers.get("vault_get")):
        raise FreshdeskError("RailCall vault helper is unavailable; configure Freshdesk credentials in Studio Integrations.")
    raw = helpers["vault_get"]("freshdesk")
    if not isinstance(raw, Mapping):
        raise FreshdeskError("Freshdesk credentials are not configured in the RailCall vault.")
    api_key = str(raw.get("api_key") or raw.get("token") or "").strip()
    domain = str(raw.get("domain") or raw.get("subdomain") or "").strip().lower().removesuffix(".freshdesk.com")
    if not api_key: raise FreshdeskError("Freshdesk API key is missing from the RailCall vault.")
    if not _DOMAIN_RE.fullmatch(domain): raise FreshdeskError("Freshdesk domain must be a single valid subdomain label.")
    return api_key, domain

def _positive_int(value: Any, name: str, minimum=1, maximum=None):
    if isinstance(value, bool): raise FreshdeskError(f"{name} must be an integer.")
    try: parsed = int(value)
    except (TypeError, ValueError) as exc: raise FreshdeskError(f"{name} must be an integer.") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise FreshdeskError(f"{name} is outside the allowed range.")
    return parsed

def _nonempty(value: Any, name: str, max_chars=50_000):
    text = str(value or "").strip()
    if not text: raise FreshdeskError(f"{name} is required.")
    if len(text) > max_chars: raise FreshdeskError(f"{name} exceeds {max_chars} characters.")
    return text

def _rate_limit(headers):
    out = {}
    for header, key in (("X-RateLimit-Total","total"),("X-RateLimit-Remaining","remaining"),("X-RateLimit-Used-CurrentRequest","used_current_request"),("Retry-After","retry_after_seconds")):
        value = headers.get(header) if hasattr(headers, "get") else None
        if value is None: continue
        try: out[key] = int(value)
        except (TypeError, ValueError): out[key] = str(value)
    return out

def _decode_json(raw: bytes):
    if not raw: return None
    if len(raw) > _MAX_BODY_CHARS: raise FreshdeskError("Freshdesk response exceeded the safe receipt-size limit.")
    try: return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise FreshdeskError("Freshdesk returned a non-JSON response.") from exc

def _request(method, path, query=None, body=None):
    api_key, domain = _vault_credentials()
    url = f"https://{domain}.freshdesk.com{path}"
    if query:
        clean = {k:v for k,v in query.items() if v is not None}
        if clean: url += "?" + urlencode(clean, doseq=True)
    auth = base64.b64encode(f"{api_key}:X".encode()).decode("ascii")
    payload = None if body is None else json.dumps(body, separators=(",",":")).encode()
    headers = {"Authorization":f"Basic {auth}","Accept":"application/json","User-Agent":"RailCall-Freshdesk-Support-Ops/0.1.0"}
    if payload is not None: headers["Content-Type"]="application/json"
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return {"ok":True,"status":int(getattr(response,"status",200)),"data":_decode_json(response.read()),"rate_limit":_rate_limit(response.headers)}
    except HTTPError as exc:
        raw = exc.read(_MAX_ERROR_CHARS).decode("utf-8", errors="replace")
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if exc.code == 429:
            suffix = f" Retry after {retry_after}s." if retry_after else ""
            raise FreshdeskRateLimitError(f"Freshdesk rate limit exceeded.{suffix}") from exc
        try: detail = json.loads(raw) if raw else None
        except json.JSONDecodeError: detail = raw[:_MAX_ERROR_CHARS]
        raise FreshdeskError(f"Freshdesk HTTP {exc.code}: {detail!r}"[:_MAX_ERROR_CHARS]) from exc
    except URLError as exc:
        raise FreshdeskError(f"Freshdesk network error: {getattr(exc,'reason','unavailable')}") from exc

def freshdesk_list_tickets(inputs, context):
    page=_positive_int(inputs.get("page",1),"page"); per=_positive_int(inputs.get("per_page",30),"per_page",maximum=100)
    status=inputs.get("status")
    if status is not None: status=_positive_int(status,"status",maximum=5)
    return _request("GET","/api/v2/tickets",query={"page":page,"per_page":per,"status":status})

def freshdesk_get_ticket(inputs, context):
    return _request("GET",f"/api/v2/tickets/{_positive_int(inputs.get('ticket_id'),'ticket_id')}")

def freshdesk_search_tickets(inputs, context):
    return _request("GET","/api/v2/search/tickets",query={"query":_nonempty(inputs.get("query"),"query",500),"page":_positive_int(inputs.get("page",1),"page")})

def freshdesk_list_conversations(inputs, context):
    return _request("GET",f"/api/v2/tickets/{_positive_int(inputs.get('ticket_id'),'ticket_id')}/conversations")

def freshdesk_create_ticket(inputs, context):
    email=_nonempty(inputs.get("email"),"email",320)
    if "@" not in email: raise FreshdeskError("email must contain @.")
    body={"email":email,"subject":_nonempty(inputs.get("subject"),"subject",500),"description":_nonempty(inputs.get("description"),"description"),"priority":_positive_int(inputs.get("priority",1),"priority",maximum=4),"status":_positive_int(inputs.get("status",2),"status",maximum=5),"source":_positive_int(inputs.get("source",2),"source",maximum=10)}
    return _request("POST","/api/v2/tickets",body=body)

def freshdesk_update_ticket(inputs, context):
    ticket_id=_positive_int(inputs.get("ticket_id"),"ticket_id")
    allowed=("status","priority","subject","type","responder_id","group_id","tags")
    body={k:inputs[k] for k in allowed if k in inputs and inputs[k] is not None}
    if not body: raise FreshdeskError("At least one mutable ticket field is required.")
    if "status" in body: body["status"]=_positive_int(body["status"],"status",maximum=5)
    if "priority" in body: body["priority"]=_positive_int(body["priority"],"priority",maximum=4)
    for k in ("responder_id","group_id"):
        if k in body: body[k]=_positive_int(body[k],k)
    for k in ("subject","type"):
        if k in body: body[k]=_nonempty(body[k],k,500)
    if "tags" in body:
        if not isinstance(body["tags"],list) or any(not isinstance(x,str) or not x.strip() for x in body["tags"]): raise FreshdeskError("tags must be an array of non-empty strings.")
        body["tags"]=[x.strip() for x in body["tags"][:50]]
    return _request("PUT",f"/api/v2/tickets/{ticket_id}",body=body)

def freshdesk_add_note(inputs, context):
    ticket_id=_positive_int(inputs.get("ticket_id"),"ticket_id"); body=_nonempty(inputs.get("body"),"body"); private=inputs.get("private",True)
    if not isinstance(private,bool): raise FreshdeskError("private must be boolean.")
    return _request("POST",f"/api/v2/tickets/{ticket_id}/notes",body={"body":body,"private":private})

def freshdesk_reply_ticket(inputs, context):
    return _request("POST",f"/api/v2/tickets/{_positive_int(inputs.get('ticket_id'),'ticket_id')}/reply",body={"body":_nonempty(inputs.get("body"),"body")})

_h_freshdesk_list_tickets=freshdesk_list_tickets
_h_freshdesk_get_ticket=freshdesk_get_ticket
_h_freshdesk_search_tickets=freshdesk_search_tickets
_h_freshdesk_list_conversations=freshdesk_list_conversations
_h_freshdesk_create_ticket=freshdesk_create_ticket
_h_freshdesk_update_ticket=freshdesk_update_ticket
_h_freshdesk_add_note=freshdesk_add_note
_h_freshdesk_reply_ticket=freshdesk_reply_ticket
