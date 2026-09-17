"""Create editable, uncompressed Draw.io source diagrams for the implemented system."""
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path('docs/diagrams')
OUT.mkdir(parents=True, exist_ok=True)
file = ET.Element('mxfile', host='app.diagrams.net', type='device')


class Diagram:
    def __init__(self, name, width=1200, height=900):
        page = ET.SubElement(file, 'diagram', id=name.lower().replace(' ', '-'), name=name)
        model = ET.SubElement(page, 'mxGraphModel', dx='1200', dy='900', grid='1', gridSize='10', page='1', pageScale='1', pageWidth=str(width), pageHeight=str(height))
        self.root = ET.SubElement(model, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')
        self.serial = 1
        self.node(name, 30, 15, width - 60, 45, 'text;html=0;fontSize=26;fontStyle=1;align=left;strokeColor=none;fillColor=none;')

    def node(self, text, x, y, w=230, h=90, style=''):
        self.serial += 1
        key = str(self.serial)
        style = style or 'rounded=1;whiteSpace=wrap;html=0;fillColor=#eef3fc;strokeColor=#9ab2d9;fontColor=#233a56;fontSize=14;spacing=12;'
        cell = ET.SubElement(self.root, 'mxCell', id=key, value=text, style=style, vertex='1', parent='1')
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), **{'as':'geometry'})
        return key

    def edge(self, source, target, label='', style=''):
        self.serial += 1
        cell = ET.SubElement(self.root, 'mxCell', id=str(self.serial), value=label, edge='1', parent='1', source=source, target=target,
                             style=style or 'edgeStyle=orthogonalEdgeStyle;rounded=0;html=0;endArrow=block;strokeColor=#7c90aa;fontColor=#425974;fontSize=12;labelBackgroundColor=#ffffff;')
        ET.SubElement(cell, 'mxGeometry', relative='1', **{'as':'geometry'})


d = Diagram('System architecture', 1200, 850)
a = d.node('Job seeker / Employer / Administrator\nWeb browser', 430, 90, 340, 75)
b = d.node('Presentation tier\nDjango templates + Bootstrap 5\nCSS + JavaScript skill tags', 390, 225, 420, 110)
c = d.node('Application tier\nDjango routing, authentication, forms\nViews, role and ownership checks', 390, 410, 420, 110)
m = d.node('MatchingAlgorithm\nCount terms → cap at 2 → TF-IDF\nCosine × certification × experience', 850, 410, 310, 110)
db = d.node('Data tier\nSQLite via Django ORM\nUsers, profiles, skills, evidence, jobs', 390, 610, 420, 110)
for s,t,l in [(a,b,'HTML response / form input'),(b,c,'Django request / response'),(c,db,'ORM query / save'),(c,m,'Eligible query and corpus'),(m,b,'Ranked score breakdown')]: d.edge(s,t,l)

d = Diagram('Database schema', 1400, 1000)
u=d.node('auth_user\nPK id · username · email\nfirst_name · last_name\npassword hash · active · staff',560,90,300,120)
acc=d.node('Account\nPK id · FK user (unique)\nrole: seeker | employer',60,100,290,95)
p=d.node('JobSeekerProfile\nPK id · FK user (unique)\ncertification_level · experience_level\nbio · portfolio · updated_at',170,330,350,145)
emp=d.node('EmployerProfile\nPK id · FK user (unique)\ncompany_name · description',870,340,340,100)
s=d.node('Skill\nPK id · FK profile\nname · normalized_name\nFK category (optional)\nUNIQUE(profile, normalized_name)',70,650,330,155)
e=d.node('EvidenceLink\nPK id · FK profile\nurl (HTTP/S)',450,650,300,100)
j=d.node('JobPost\nPK id · FK employer\ntitle · description · required_skills\ncertification_level · experience_level\nis_active · timestamps',900,630,350,160)
cat=d.node('SkillCategory\nPK id · name (unique)',70,870,330,75)
for src,tgt,label in [(u,acc,'1 → 1'),(u,p,'1 → 0..1'),(u,emp,'1 → 0..1'),(p,s,'1 → many'),(p,e,'1 → 0..many'),(emp,j,'1 → many'),(cat,s,'0..1 → many')]:d.edge(src,tgt,label)

d=Diagram('Use cases',1400,1050)
actorstyle='shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=0;fontSize=15;'
seeker=d.node('Job seeker',50,210,75,95,actorstyle)
employer=d.node('Employer',1240,210,75,95,actorstyle)
admin=d.node('Administrator',1240,805,75,95,actorstyle)
ellipse='ellipse;whiteSpace=wrap;html=0;fillColor=#eef3fc;strokeColor=#9ab2d9;fontSize=14;'
shared=d.node('Register / Log in / Sign out',520,100,340,85,ellipse)
profile=d.node('Create and edit professional profile\nUnique skill tags, levels, bio, portfolio\nOptional evidence links',210,280,410,120,ellipse)
recommend=d.node('View ranked job recommendations\nand job details',210,490,410,100,ellipse)
browse=d.node('Browse open job posts',210,680,410,85,ellipse)
company=d.node('Manage company profile',790,280,360,90,ellipse)
post=d.node('Create and manage job posts',790,460,360,90,ellipse)
rank=d.node('Search / rank candidates\nInspect profile and score details',790,640,360,100,ellipse)
manage=d.node('Manage users, profiles and jobs',690,850,410,90,ellipse)
for src,tgt in [(seeker,shared),(employer,shared),(seeker,profile),(seeker,recommend),(seeker,browse),(employer,company),(employer,post),(employer,rank),(admin,manage)]:d.edge(src,tgt,'','endArrow=none;html=0;strokeColor=#7c90aa;')

d=Diagram('Matching activity',1150,1450)
steps=[('Employer submits job or search text',400,90),('Authorize employer and job ownership',400,225),('Load active candidate profiles\nKeep only profiles with skills, bio and portfolio',400,360),('Concatenate skills + bio + portfolio\nPrepare employer text',400,515),('Tokenize and remove stop words\nCap raw term frequencies at 2',400,670),('Fit shared TF-IDF representation\nCompute cosine similarity',400,825),('Apply profile certification multiplier\nApply profile experience multiplier',400,980),('Sort descending, break ties by ID\nPaginate ranked candidate profiles',400,1135)]
nodes=[d.node(t,x,y,430,95) for t,x,y in steps]
for src,tgt in zip(nodes,nodes[1:]):d.edge(src,tgt)
d.node('Reverse workflow\nA complete seeker profile is the query.\nDocuments are open jobs from active employers.\nUse the same pipeline and profile multipliers.',30,800,300,165)
d.node('Empty corpus or empty vocabulary\nShow an empty list or zero scores.\nNo fabricated matches.',30,1060,300,120)

d=Diagram('Implementation class diagram',1300,900)
user=d.node('Django User\nusername, password, active\ncheck_password(), get_full_name()',480,90,330,110)
profile=d.node('JobSeekerProfile\ncertification_level, experience_level\nbio, portfolio\nis_complete, matching_text',50,325,390,140)
employer=d.node('EmployerProfile\ncompany_name, description\njobs (related manager)',850,325,360,120)
job=d.node('JobPost\ntitle, description, required_skills\nlevels, is_active\nmatching_text',850,610,360,140)
engine=d.node('MatchingAlgorithm\nvectorize(texts)\ncompute_similarity(query, documents)\napply_multipliers(base, profile)\nrank_candidates(query, profiles)\nrank_jobs(profile, jobs)',390,570,420,210)
skill=d.node('Skill / EvidenceLink\nUnique skill name / URL\nFK profile',40,620,285,105)
for src,tgt,l in [(user,profile,'one-to-one composition'),(user,employer,'one-to-one composition'),(profile,skill,'owns many'),(employer,job,'owns many'),(engine,profile,'reads'),(engine,job,'reads')]:d.edge(src,tgt,l)
d.node('Django implements role profiles through composition\nrather than subclassing its concrete User model.',410,810,480,60,'text;html=0;fontSize=13;fontColor=#60748e;strokeColor=none;fillColor=none;')

d=Diagram('Matching sequence',1300,950)
labels=['Employer browser','Django view / form','Django ORM / SQLite','MatchingAlgorithm']
xs=[50,370,690,1010]
heads=[d.node(label,x,100,220,65) for label,x in zip(labels,xs)]
for head,x in zip(heads,xs):
    bottom=d.node('',x+109,830,2,2,'fillColor=none;strokeColor=none;')
    d.edge(head,bottom,'','dashed=1;endArrow=none;strokeColor=#b6c3d4;')
def message(start,end,y,label):
    p=d.node('',xs[start]+109,y,2,2,'fillColor=none;strokeColor=none;')
    q=d.node('',xs[end]+109,y,2,2,'fillColor=none;strokeColor=none;')
    d.edge(p,q,label,'endArrow=block;html=0;fontSize=12;strokeColor=#637d9d;labelBackgroundColor=#ffffff;')
for row in [(0,1,230,'1. Submit job description'),(1,2,310,'2. Check ownership and retrieve active profiles'),(2,1,390,'3. Profiles, unique skills and portfolio text'),(1,3,470,'4. Rank query against profile corpus'),(3,3,530,'5. Cap TF, vectorize, cosine, multipliers'),(3,1,620,'6. Ranked Match objects'),(1,0,735,'7. Render candidates, skills and score breakdown')]:
    if row[0]==row[1]:d.node(row[3],910,row[2]-15,340,60)
    else:message(*row)

d=Diagram('Interface wireframes',1500,1300)
frames=[('Registration and login',40,100),('Professional profile',780,100),('Employer job posting',40,710),('Ranked match results',780,710)]
for title,x,y in frames:
    d.node(title,x,y,660,520,'rounded=0;whiteSpace=wrap;html=0;fillColor=#ffffff;strokeColor=#b6c3d4;fontColor=#29425f;fontSize=18;verticalAlign=top;spacingTop=20;')
d.node('Name · Email · Username\nRole selector\nCompany name (employers only)\nPassword · Confirm password',90,190,560,240)
d.node('Create account / Sign in',90,465,560,70)
d.node('Names\nSingle skill input + Add skill\nSkill tags with removal and duplicate feedback\nCertification and experience dropdowns\nBio · Portfolio description\nOptional evidence links',830,190,560,310)
d.node('Save profile',830,525,560,55)
d.node('Job title and description\nUnique required skill tags\nMinimum certification and experience',90,800,560,210)
d.node('Post job and find matches',90,1050,560,70)
d.node('Candidate / Job title and summary\nMatching skill tags\nCertification and experience levels\nView profile / opportunity',830,800,350,250)
d.node('Weighted score\nWhy this match?\nBase similarity\n× Certification\n× Experience',1200,800,190,250)
d.node('Pagination · query retained',830,1090,560,60)

ET.indent(file)
path=OUT/'SkillMatch-system-design.drawio'
ET.ElementTree(file).write(path,encoding='utf-8',xml_declaration=True)
assert len(file.findall('diagram')) == 7
for page in file.findall('diagram'):
    cells=page.findall('.//mxCell')
    ids={c.attrib['id'] for c in cells}
    assert len(ids)==len(cells)
    for cell in cells:
        if cell.get('edge'):
            assert cell.get('source') in ids and cell.get('target') in ids
print('Created and structurally checked 7 editable Draw.io pages:',path)
