import os, base64, time, jwt, httpx

app_id = os.environ.get('GITHUB_APP_ID', '')
raw_key = os.environ.get('GITHUB_APP_PRIVATE_KEY', '')
pem = base64.b64decode(raw_key).decode('utf-8')

now = int(time.time())
payload = {'iat': now - 10, 'exp': now + 60, 'iss': app_id}
token = jwt.encode(payload, pem, algorithm='RS256')

resp = httpx.get('https://api.github.com/app', headers={
    'Authorization': f'Bearer {token}',
    'Accept': 'application/vnd.github+json',
})
print(resp.status_code, resp.json())
