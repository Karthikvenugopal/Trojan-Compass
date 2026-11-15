"""Inspect public USC metadata only; no credentials or student inputs."""
import json
import re
import urllib.request


def get(url: str) -> str:
    req=urllib.request.Request(url, headers={'User-Agent':'TrojanCompass-PublicDataImporter/1.0'})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read(6_000_000).decode('utf-8', errors='replace')

url='https://calendar.usc.edu/api/2/events?days=365&pp=3&page=2'
data=json.loads(get(url))
print('EVENT PAGE',data.get('page'),flush=True)
for row in data.get('events',[])[:2]:
    event=row['event']
    print('EVENT KEYS',list(event),flush=True)
    print('EVENT METADATA',json.dumps({k:event[k] for k in ('id','title','departments','tags','event_instances','filters','status','canceled','experience','room_number','location_name') if k in event},ensure_ascii=False)[:7000],flush=True)
base='https://classes.usc.edu/'
html=get(base+'term/20263/catalogue')
print('BASE',re.findall(r'<base[^>]+>',html),flush=True)
scripts=re.findall(r'<script[^>]+src=[\'\"]([^\'\"]+)',html)
for name in scripts:
    if not name.startswith('main.'):
        continue
    body=get(base+name)
    print('MAIN JS BYTES',len(body),flush=True)
    print('PUBLIC URLS',sorted(set(re.findall(r'https?[^\s"\'`<>]{1,180}',body)))[:100],flush=True)
    print('API STRINGS',re.findall(r'.{0,100}(?:api/|apiUrl|apiURL|baseUrl|graphql|/catalogue|departments|course_data|apiBase).{0,160}',body)[:55],flush=True)
