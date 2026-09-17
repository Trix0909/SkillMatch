from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from pypdf import PdfReader

base = Path.home() / 'Documents' / 'ICS Project II'
out = Path('docs/source-extracts')
out.mkdir(parents=True, exist_ok=True)
pdf = PdfReader(base / '168111 - Concept note.pdf')
(out / 'concept.txt').write_text('\n\n'.join(f'PAGE {i+1}\n{p.extract_text()}' for i,p in enumerate(pdf.pages)), encoding='utf-8')
with ZipFile(base / 'KinyuaTrinaWanjiku_168111 (where changes are being made).docx') as z:
    root=ET.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in root.findall('.//w:p',ns)]
    (out / 'proposal.txt').write_text('\n'.join(paragraphs),encoding='utf-8')
    for name in z.namelist():
        if name == 'word/comments.xml':
            (out / 'comments.xml').write_bytes(z.read(name))
with ZipFile(base / 'Proposal defense' / 'SkillMatch_Proposal_Defense_Presentation.pptx') as z:
    names=sorted([n for n in z.namelist() if __import__('re').match(r'ppt/slides/slide\d+\.xml$',n)],key=lambda n:int(__import__('re').search(r'slide(\d+)',n)[1]))
    ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    slides=[]
    for name in names:
        root=ET.fromstring(z.read(name))
        slides.append(name+'\n'+'\n'.join(t.text or '' for t in root.findall('.//a:t',ns)))
    (out / 'presentation.txt').write_text('\n\n'.join(slides),encoding='utf-8')
print('Extracted all three source files to',out)
