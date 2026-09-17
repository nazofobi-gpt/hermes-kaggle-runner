#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

base_url = os.environ.get('KAGGLE_BASE_URL', '').strip().rstrip('/')
api_key = os.environ.get('KAGGLE_API_KEY', '').strip()
model = os.environ.get('KAGGLE_MODEL', 'llama3.1-hermes').strip()

if not base_url:
    raise SystemExit('KAGGLE_BASE_URL is missing')
if not api_key:
    raise SystemExit('KAGGLE_API_KEY is missing')
if not base_url.endswith('/v1'):
    base_url += '/v1'

prompt_path = Path('requests/prompt.txt')
if not prompt_path.exists():
    raise SystemExit('requests/prompt.txt is missing')
prompt = prompt_path.read_text(encoding='utf-8').strip()
if not prompt:
    raise SystemExit('Prompt is empty')

payload = {
    'model': model,
    'messages': [{'role': 'user', 'content': prompt}],
    'stream': False,
    'temperature': 0.2,
    'max_tokens': 600,
}

req = urllib.request.Request(
    base_url + '/chat/completions',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    },
    method='POST',
)

try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read().decode('utf-8'))
except urllib.error.HTTPError as exc:
    text = exc.read().decode('utf-8', errors='replace')[:2000]
    print(f'HTTP_ERROR: {exc.code}', file=sys.stderr)
    print(text, file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:
    print(f'REQUEST_ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
    raise SystemExit(1)

choices = body.get('choices') or []
if not choices:
    print(json.dumps(body, ensure_ascii=False)[:4000])
    raise SystemExit('No choices returned')

message = choices[0].get('message') or {}
content = message.get('content')
print('KAGGLE_REMOTE_CALL_PASS')
print('MODEL:', body.get('model', model))
print('RESPONSE_START')
print(content if content is not None else json.dumps(message, ensure_ascii=False))
print('RESPONSE_END')
