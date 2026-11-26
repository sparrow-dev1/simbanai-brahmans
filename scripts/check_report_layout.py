"""Render and check report/profile layout using fictional data only."""
from pathlib impimport sys,json
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pypdfium2 as pdfium
from cattle import create_app
from cattle.models import db,User,Animal
from cattle.reporting import build_pdf
from sqlalchemy import select
from PIL import Image,ImageDraw
qa=ROOT/'test-output'/'sample-report-qa'
snapshot=qa/'source-snapshot.sqlite'
if not snapshot.exists():raise SystemExit('Run export_sample_reports.py first; only its disposable snapshot is permitted.')
app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+snapshot.as_posix(),'SESSION_COOKIE_SECURE':False,'SECRET_KEY':'layout-only-snapshot'})
with app.app_context():
 owner=db.session.scalar(select(User).where(User.role=='owner',User.active.is_(True)))
 animal=db.session.scalar(select(Animal).order_by(Animal.id))
 client=app.test_client()
 with client.session_transaction() as session:session.update(user_id=owner.id,version=owner.session_version,csrf='layout-only')
 response=client.get(f'/api/animals/{animal.id}/profile.pdf')
 assert response.status_code==200,response.json
 (qa/'profile-layout.pdf').write_bytes(response.data)
long_ids=['SB-LONG-'+str(i).zfill(4)+'-'+'X'*65 for i in range(180)]
data={'type':'Health','columns':['Date','Record','Station','Participating cattle','Details','Event'],'rows':[['2026-01-01','Dipping','Fictional station',', '.join(long_ids),'Layout fixture only: long identities and large participant appendix.','QA-ONLY']],'participant_groups':[{'title':'Fictional layout fixture','ids':long_ids,'absent':long_ids[:4]}]}
(qa/'large-participants-layout.pdf').write_bytes(build_pdf(data,sample_label='LAYOUT TEST ONLY').getvalue())
files=list((ROOT/'sample-reports').glob('*.pdf'))+[qa/'profile-layout.pdf',qa/'large-participants-layout.pdf']
results=[]
for filename in files:
 document=pdfium.PdfDocument(str(filename));text=[]
 for number in range(len(document)):
  page=document[number];w,h=page.get_size()
  portrait='growth' in filename.name or 'births-deaths' in filename.name or filename.name=='profile-layout.pdf'
  assert (h>w)==portrait,(filename.name,'orientation')
  textpage=page.get_textpage();text.append(textpage.get_text_range())
  for index in range(textpage.count_chars()):
   left,bottom,right,top=textpage.get_charbox(index)
   assert left>=27 and right<=w-27 and bottom>=7 and top<=h-10,(filename.name,number,index,(left,bottom,right,top))
  image=page.render(scale=1.2).to_pil().convert('RGB')
  top=image.crop((0,0,image.width,int(image.height*.31)))
  green=sum(1 for r,g,b in (top.get_flattened_data() if hasattr(top,'get_flattened_data') else top.getdata()) if g>r*1.1 and g>b*1.1 and g<150)
  assert green>150,(filename.name,number,'missing header')
  image.save(qa/(filename.stem+f'-verified-page-{number+1}.png'))
  page.close()
 joined=''.join(text)
 assert 'Page 1' in joined,filename.name
 if filename.name=='large-participants-layout.pdf':
  assert long_ids[0] in joined.replace('\r','').replace('\n','') and long_ids[-1] in joined.replace('\r','').replace('\n','')
 results.append({'file':filename.name,'pages':len(document),'orientation':'portrait' if portrait else 'landscape','verified':True})
 document.close()
(qa/'layout-verification.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
