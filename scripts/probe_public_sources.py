"""Inspect only public USC feed formats. No credentials or student inputs accepted."""

import json
import re
import urllib.request

URLS = [
    'https://calendar.usc.edu/api/2/events?days=365&pp=2',
    'https://calendar.usc.edu/api/2/departments?pp=2',
    'https://classes.usc.edu/term/20263/catalogue',
    'https://web-app.usc.edu/web/soc/api/classes/20263/PSYC',
    'https://classes.usc.edu/term/20263/catalogue/course/psyc-100',
]
for url in URLS:
    print('PUBLIC URL', url, flush=True)
    try:
        request = urllib.request.Request(url, headers={'User-Agent':'TrojanCompass-PublicDataImporter/1.0', 'Accept':'application/json,text/html'})
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(5_000_000).decode('utf-8', errors='replace')
            print('STATUS', response.status, 'BYTES', len(body), flush=True)
        try:
            data = json.loads(body)
            print('TOP LEVEL', list(data) if isinstance(data, dict) else type(data).__name__, flush=True)
            if isinstance(data, dict):
                for key in ('events', 'departments'):
                    rows = data.get(key, [])
                    if isinstance(rows, list):
                        for row in rows[:2]:
                            item = next(iter(row.values())) if isinstance(row, dict) else {}
                            if isinstance(item, dict):
                                selected = {k: item[k] for k in ('id','title','name','localist_url','url','event_instances','filters','timezone','experience','location_name') if k in item}
                                print('PUBLIC METADATA', json.dumps(selected, ensure_ascii=False)[:5000], flush=True)
                courses = data.get('OfferedCourses')
                if isinstance(courses, dict):
                    print('COURSE KEYS', list(courses), flush=True)
                    print('COURSE SHAPE', str(type(courses.get('course'))), flush=True)
                    course = courses.get('course', [])
                    if isinstance(course, list):
                        course = course[0] if course else {}
                    if isinstance(course, dict):
                        print('FIRST COURSE KEYS', list(course), flush=True)
                        details = course.get('CourseData', {})
                        print('COURSE DATA', json.dumps({k:v for k,v in details.items() if 'section' not in k.lower() and 'instructor' not in k.lower()}, ensure_ascii=False)[:4000], flush=True)
        except ValueError:
            print('SCRIPTS', re.findall(r'<script[^>]+src=[\'\"]([^\'\"]+)',body)[:8], flush=True)
            print('API REFERENCES', re.findall(r'.{0,70}(?:api|graphql|__NEXT_DATA__).{0,120}',body)[:12], flush=True)
    except Exception as error:
        print(type(error).__name__, str(error)[:150], flush=True)
