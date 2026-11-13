"""Generate private demo registry files from FSR CSV; never activate contacts."""
import argparse
from collections import defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def checksum(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def prepare(source):
    source=Path(source)
    raw=source.read_bytes()
    with io.StringIO(raw.decode('utf-8-sig'),newline='') as f:
        reader=csv.DictReader(f)
        required={'설치고객사명','기종명','호기','제조처'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('FSR columns are missing')
        grouped=defaultdict(list)
        count=0
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('Malformed CSV row')
            key=tuple(row[k].strip() for k in ('설치고객사명','기종명','호기'))
            if any(not x or len(x)>120 or any(ord(c)<32 for c in x) for x in key):
                raise ValueError('Missing or oversized identity; no silent truncation')
            site=row['제조처'].strip()
            if len(site)>120 or any(ord(c)<32 for c in site):raise ValueError('Invalid manufacturing site')
            grouped[key].append(site)
            count+=1
    owners=defaultdict(set)
    for company,model,serial in grouped:owners[(model,serial)].add(company)
    names=sorted({key[0] for key in grouped})
    companies=[];codes=set();company_by_name={}
    for name in names:
        code='M-'+checksum(name)[:10].upper()
        if code in codes:raise ValueError('Company code collision')
        codes.add(code)
        value={'id':str(uuid5(NAMESPACE_URL,'morrono-company|'+name)),'code':code,'name':name,
               'is_active':True,'email':code.lower()+'@example.invalid'}
        companies.append(value);company_by_name[name]=value
    equipment=[]
    for (name,model,serial),sites in sorted(grouped.items()):
        key=checksum(json.dumps([name,model,serial],ensure_ascii=False,separators=(',',':')))
        sites={x for x in sites if x}
        equipment.append({'id':str(uuid5(NAMESPACE_URL,'morrono-equipment|'+key)),
            'company_id':company_by_name[name]['id'],'company_code':company_by_name[name]['code'],
            'model_name':model,'serial_number':serial,'manufacturing_site':next(iter(sites)) if len(sites)==1 else None,
            'is_confirmed':False,'is_active':True,'needs_review':len(owners[(model,serial)])>1 or len(sites)>1,
            'source_kind':'fsr','source_key':key,'reference_count':len(grouped[(name,model,serial)])})
    return {'format':'morrono-registry-demo-v1','source_sha256':hashlib.sha256(raw).hexdigest(),
            'source_rows':count,'companies':companies,'equipment':equipment,
            'ownership_conflicts':sum(len(v)>1 for v in owners.values())}


def spreadsheet_safe(value):
    value='' if value is None else str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value


def export(data, directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'registry-seed.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    company_by_id={c['id']:c for c in data['companies']}
    counts=defaultdict(int)
    for item in data['equipment']:counts[item['company_id']]+=1
    with (directory/'회사_마스터.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['회사코드','설치고객사명','등록이메일','이메일구분','가입허용','등록설비수'])
        for c in data['companies']:
            writer.writerow([spreadsheet_safe(v) for v in [c['code'],c['name'],c['email'],'시연용','아니오',counts[c['id']]]])
    with (directory/'고객사_설비_관리.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['회사코드','설치고객사명','등록이메일','기종명','호기','제조처','등록수량','확인상태','FSR참고건수'])
        for e in data['equipment']:
            c=company_by_id[e['company_id']]
            writer.writerow([spreadsheet_safe(v) for v in [c['code'],c['name'],c['email'],e['model_name'],e['serial_number'],e['manufacturing_site'],1,'소속확인필요' if e['needs_review'] else '확인전',e['reference_count']]])
    (directory/'생성정보.json').write_text(json.dumps({'source_sha256':data['source_sha256'],'source_rows':data['source_rows'],
        'companies':len(data['companies']),'equipment':len(data['equipment']),'ownership_conflicts':data['ownership_conflicts'],
        'emails':'reserved example.invalid; inactive; never used for authentication or sending',
        'quantity':'one row per company/model/serial observation; not verified purchase quantity'},ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    data=prepare(args.source);export(data,args.output)
    print(json.dumps({'companies':len(data['companies']),'equipment':len(data['equipment']),'source_rows':data['source_rows']}))


if __name__=='__main__':main()
