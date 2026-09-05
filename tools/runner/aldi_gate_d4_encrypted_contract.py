from __future__ import annotations
import hashlib,json,os,re,stat
from pathlib import Path
from typing import Any,Mapping

AUDIT='aldi-gate-d4-encrypted-backup-discovery'
TARGET='8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e'
D3_SHA='606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8'
ISSUE=679; PARENT_ISSUE=631; MAX_INPUTS=8
BACKUP_ROOT=Path('/opt/backups'); AGE_KEY=Path('/etc/rpi5-backup/age.key'); TMPFS_PARENT=Path('/dev/shm')
ID_RE=re.compile(r'[a-z0-9][a-z0-9._-]{0,63}'); HEX_RE=re.compile(r'[0-9a-f]{64}')
DECISIONS={'NO_CANDIDATE_IN_DESIGNATED_ROOTS','PLAUSIBLE_RECOVERY_CANDIDATE_FOUND','AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES'}
AUTHORITY_FLAGS=(
'raw_evidence_export_authorized','raw_exception_export_authorized','network_acquisition_authorized',
'archive_extraction_authorized','source_or_corpus_mutation_authorized','manifest_regeneration_authorized',
'parser_execution_authorized','candidate_creation_authorized','review_or_publication_write_authorized',
'production_database_write_authorized','production_deployment_authorized','scheduler_systemd_canary_authorized',
'destructive_cleanup_authorized','newer_41_plus_41_substitution_authorized','historical_recovery_binding_authorized',
'irrecoverable_decision_recording_authorized')

class ContractError(RuntimeError): pass
def require(v:bool,msg:str)->None:
    if not v: raise ContractError(msg)
def canonical_bytes(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def regular_root_file(p:Path,mode:int|None=None)->bool:
    try:s=p.lstat()
    except OSError:return False
    return stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_uid==0 and s.st_gid==0 and (mode is None or stat.S_IMODE(s.st_mode)==mode)
def root_runtime_file(p:Path)->bool:
    try:s=p.lstat()
    except OSError:return False
    return stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_uid==0 and s.st_gid==0 and stat.S_IMODE(s.st_mode) in {0o444,0o555}
def root_runtime_dir(p:Path)->bool:
    try:s=p.lstat()
    except OSError:return False
    return stat.S_ISDIR(s.st_mode) and not p.is_symlink() and s.st_uid==0 and s.st_gid==0 and stat.S_IMODE(s.st_mode) in {0o555,0o755}

def canonical_encrypted_file(raw:Any,backup_root:Path=BACKUP_ROOT)->Path:
    require(isinstance(raw,str) and raw.startswith('/'),'encrypted backup path must be absolute')
    p=Path(raw); require('..' not in p.parts,'encrypted backup path must not traverse')
    require(str(p)==raw,'encrypted backup path must be canonical')
    require(p.parent==backup_root,'encrypted backup must be exact /opt/backups file')
    require(re.fullmatch(r'rpi5_backup_[A-Za-z0-9._-]+\.tar\.gz\.age',p.name) is not None,'encrypted backup name invalid')
    return p

def validate_request_payload(payload:Mapping[str,Any],*,backup_root:Path=BACKUP_ROOT,file_check=regular_root_file,hasher=sha_file)->list[tuple[str,Path,str]]:
    require(set(payload)=={'schema_version','issue_number','parent_issue_number','encrypted_files'},'request fields mismatch')
    require(payload.get('schema_version')==1 and payload.get('issue_number')==ISSUE and payload.get('parent_issue_number')==PARENT_ISSUE,'request identity mismatch')
    rows=payload.get('encrypted_files'); require(isinstance(rows,list) and 1<=len(rows)<=MAX_INPUTS,'encrypted input count invalid')
    out=[]; seen=set()
    for row in rows:
        require(isinstance(row,Mapping) and set(row)=={'id','path','ciphertext_sha256'},'encrypted input fields mismatch')
        i=row.get('id'); require(isinstance(i,str) and ID_RE.fullmatch(i) is not None and i not in seen,'encrypted input id invalid'); seen.add(i)
        p=canonical_encrypted_file(row.get('path'),backup_root); d=row.get('ciphertext_sha256')
        require(isinstance(d,str) and HEX_RE.fullmatch(d) is not None,'ciphertext SHA invalid')
        require(file_check(p,0o600),'encrypted backup missing or unsafe')
        require(hasher(p)==d,'ciphertext SHA mismatch')
        out.append((i,p,d))
    return sorted(out)

def load_json_file(path:Path,*,mode:int=0o600)->dict[str,Any]:
    require(regular_root_file(path,mode),f'{path.name} missing or unsafe')
    try:v=json.loads(path.read_text())
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as e:raise ContractError(f'{path.name} invalid') from e
    require(isinstance(v,dict),f'{path.name} root invalid'); return v

def contains_absolute_path(v:Any)->bool:
    if isinstance(v,str):return v.startswith('/')
    if isinstance(v,Mapping):return any(contains_absolute_path(x) for x in v.values())
    if isinstance(v,list):return any(contains_absolute_path(x) for x in v)
    return False

def validate_result(p:Mapping[str,Any],expected_count:int)->None:
    require(p.get('schema_version')==1 and p.get('mode')=='ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY' and p.get('issue_number')==PARENT_ISSUE,'result identity mismatch')
    require(p.get('request_schema_version')==2 and p.get('authoritative_source_set_complete') is False,'result request binding mismatch')
    decision=p.get('decision'); require(decision in DECISIONS,'unsupported encrypted Gate D4 decision')
    require(p.get('designated_root_count')==0 and p.get('designated_file_count')==expected_count and p.get('designated_input_count')==expected_count,'result input counts mismatch')
    require(p.get('provenance_binding_complete') is False and p.get('historical_recovery_authorized') is False and p.get('irrecoverable_decision_recorded') is False,'result authority drift')
    ids=p.get('complete_identities'); sources=p.get('plausible_recovery_sources'); ic=p.get('distinct_complete_identity_count'); sc=p.get('complete_recovery_source_count')
    require(isinstance(ids,list) and all(isinstance(x,str) and HEX_RE.fullmatch(x) for x in ids) and ids==sorted(set(ids)),'result identities invalid')
    require(isinstance(sources,list) and isinstance(ic,int) and not isinstance(ic,bool) and ic==len(ids) and isinstance(sc,int) and not isinstance(sc,bool) and sc==len(sources),'result source counts invalid')
    source_ids=[]
    for r in sources:
        require(isinstance(r,Mapping) and isinstance(r.get('identity_sha256'),str) and HEX_RE.fullmatch(r['identity_sha256']),'result source identity invalid'); source_ids.append(r['identity_sha256'])
    require(sorted(set(source_ids))==ids,'result source identities mismatch')
    expected='AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES' if len(ids)>1 else 'PLAUSIBLE_RECOVERY_CANDIDATE_FOUND' if ids else 'NO_CANDIDATE_IN_DESIGNATED_ROOTS'
    require(decision==expected,'result decision/count mismatch')
    safety=p.get('safety'); require(isinstance(safety,Mapping),'result safety missing')
    require(safety.get('explicit_inputs_only') is True and safety.get('explicit_roots_only') is False and safety.get('exact_file_allowlist_enabled') is True and safety.get('strict_49_plus_41_frozen_contract_unchanged') is True,'result safety drift')
    for k,v in safety.items():
        if k not in {'explicit_inputs_only','explicit_roots_only','exact_file_allowlist_enabled','strict_49_plus_41_frozen_contract_unchanged'}:require(v is False,f'unsafe result flag: {k}')
    fp=p.get('diagnostic_fingerprint'); require(isinstance(fp,str) and HEX_RE.fullmatch(fp),'fingerprint missing')
    src=dict(p);src.pop('diagnostic_fingerprint',None);require(hashlib.sha256(canonical_bytes(src)).hexdigest()==fp,'fingerprint mismatch')
    require(not contains_absolute_path(p),'absolute path leaked from encrypted discovery')

def evidence_manifest(*,commit_sha:str,request_sha:str,d4_sha:str,result:Mapping[str,Any],rows:list[tuple[str,Path,str]])->dict[str,Any]:
    return {'schema_version':1,'audit':AUDIT,'commit_sha':commit_sha,'decision':result['decision'],'diagnostic_fingerprint':result['diagnostic_fingerprint'],'request_bound':True,'request_sha256':request_sha,'d4_sha256':d4_sha,'d3_sha256':D3_SHA,'encrypted_input_count':len(rows),'encrypted_inputs':[{'id':i,'ciphertext_sha256':d} for i,_p,d in rows],'ciphertext_sha256_verified':True,'age_identity_verified':True,'age_identity_exported':False,'plaintext_tmpfs_verified':True,'plaintext_exported':False,'plaintext_cleanup_verified':True,'sanitization_passed':True,'raw_evidence_exported':False,'raw_exception_exported':False,'raw_stderr_exported':False,'raw_request_exported':False,**{k:False for k in AUTHORITY_FLAGS}}