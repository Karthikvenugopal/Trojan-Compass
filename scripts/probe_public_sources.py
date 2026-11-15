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

for method in ('apiCoursesCoursesByTermSchoolProgram', 'apiCoursesCourse', 'apiProgramsPrefix', 'apiSearchBasic'):
    at=body.find(method+'(')
    part=body[at:at+1800]
    print('QUERY FIELDS',method,re.findall(r'([A-Za-z]+)=\"?\+encodeURIComponent',part),re.findall(r'parameter [^;]{0,70}',part)[:4],flush=True)
    print('METHOD SHAPE',method,part[:950],flush=True)
print('ROUTE PATHS',re.findall(r'path:\"([^\"]{0,160})',body)[-80:],flush=True)
for path in ('api/Schools/TermCode?termCode=20263', 'api/Programs/TermCode?termCode=20263', 'api/Courses/CoursesByTermSchoolProgram?termCode=20263&schoolCode=LAS&programCode=PSYC'):
    try:
        response=get(base+path)
        obj=json.loads(response)
        print('CATALOGUE ENDPOINT',path,'TYPE',type(obj).__name__,'COUNT',len(obj),flush=True)
        sample=obj[:1] if isinstance(obj,list) else obj
        if isinstance(sample,dict):
            print('CATALOGUE TOP KEYS',list(sample),flush=True)
        print('CATALOGUE SAMPLE',json.dumps(sample,ensure_ascii=False)[:4000],flush=True)
    except Exception as error:
        print('CATALOGUE ERROR',path,type(error).__name__,str(error)[:120],flush=True)
for method in ('apiCoursesCoursesByTermSchoolProgram', 'apiCoursesCourse'):
    match=re.search(re.escape(method)+r'\([^)]*\)\{let',body)
    if match:
        print('PUBLIC GET PARAMS',body[match.start():match.start()+1100],flush=True)
for path in (
    'api/Courses/CoursesByTermSchoolProgram?termCode=20263&schoolPrefix=DRNS&programPrefix=PSYC',
    'api/Courses/CoursesByTermSchoolProgram?termCode=20263&schoolPrefix=MEDK&programPrefix=ANY',
    'api/Search/Basic?termCode=20263&searchTerm=PSYC',
):
    try:
        obj=json.loads(get(base+path))
        print('PUBLIC COURSE RESPONSE',path,'TYPE',type(obj).__name__,flush=True)
        rows=obj.get('courses') if isinstance(obj,dict) else obj
        if isinstance(obj,dict):
            print('RESPONSE KEYS',list(obj),flush=True)
        if isinstance(rows,list):
            print('COURSE COUNT',len(rows),flush=True)
            if rows and isinstance(rows[0],dict):
                print('COURSE FIELDS',list(rows[0]),flush=True)
                print('COURSE FACTS',json.dumps({k:v for k,v in rows[0].items() if k.lower() in ('courseid','title','coursename','prefix','units','minunits','maxunits','prerequisite','prerequisites','prerequisitetext','corequisite','description','leveloneprefix','leveltwoprefix','classnumber','coursetitle','coursedescription','corequisites','prerequisitecondition')},ensure_ascii=False)[:2000],flush=True)
    except Exception as error:
        print('PUBLIC COURSE ERROR',type(error).__name__,str(error)[:120],flush=True)
for path in (
    'api/Courses/CoursesByTermSchoolProgram?termCode=20263&school=DRNS&program=PSYC',
    'api/Courses/CoursesByTermSchoolProgram?termCode=20263&school=MUS',
    'api/Courses/CoursesByTermSchoolProgram?termCode=20263&program=PSYC',
):
    try:
        obj=json.loads(get(base+path))
        rows=obj.get('courses') if isinstance(obj,dict) else obj
        print('CONFIRMED PUBLIC COURSE GET',path, 'COUNT',len(rows) if isinstance(rows,list) else None,flush=True)
        if isinstance(rows,list) and rows:
            print('PUBLIC COURSE KEYS',list(rows[0]),flush=True)
            print('PUBLIC COURSE FACTS',json.dumps({k:v for k,v in rows[0].items() if not isinstance(v,(list,dict)) and not any(term in k.lower() for term in ('instructor','contact','email','description','note'))},ensure_ascii=False)[:2500],flush=True)
            for key in rows[0]:
                if 'pre' in key.lower() or 'req' in key.lower():
                    print('PUBLIC REQUISITE',key,json.dumps(rows[0][key],ensure_ascii=False)[:1600],flush=True)
    except Exception as error:
        print('PUBLIC COURSE ERROR',type(error).__name__,str(error)[:120],flush=True)
