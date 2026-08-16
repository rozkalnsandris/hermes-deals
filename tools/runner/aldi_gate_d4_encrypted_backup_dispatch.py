#!/usr/bin/env python3
from __future__ import annotations
import grp,hashlib,importlib.util,json,os,pwd,re,shutil,stat,subprocess,sys,tempfile
from pathlib import Path
from typing import Any

CONTRACT_PATH=Path('/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-encrypted-backup-discovery/contract.py')
if not CONTRACT_PATH.exists():CONTRACT_PATH=Path(__file__).with_name('aldi_gate_d4_encrypted_contract.py')
spec=importlib.util.spec_from_file_location('d4e_contract',CONTRACT_PATH); assert spec and spec.loader
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
EncryptedDispatchError=c.ContractError; require=c.require; canonical_bytes=c.canonical_bytes; sha_file=c.sha_file; regular_root_file=c.regular_root_file; validate_result=c.validate_result
EXPECTED_TARGET_SHA=c.TARGET; BACKUP_ROOT=c.BACKUP_ROOT; AGE_KEY=c.AGE_KEY; TMPFS_PARENT=c.TMPFS_PARENT
CONFIG=Path('/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery.json');REQUEST=Path('/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery-request.json')
RUNTIME_ROOT=Path('/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery');EXPORT_ROOT=Path('/home/github-runner/_work/_temp');EXPORT_PREFIX='hermes-deals-aldi-gate-d4-encrypted-backup-'
AUDIT_USER='andris';RUNNER_USER='github-runner';AGE_BINARIES=(Path('/usr/bin/age'),Path('/usr/local/bin/age'))

def runner_in_docker_group(name:str)->bool:
    u=pwd.getpwnam(name);return any(g.gr_name=='docker' and (name in g.gr_mem or g.gr_gid==u.pw_gid) for g in grp.getgrall())
def validate_export_dir(p:Path,u:pwd.struct_passwd)->Path:
    require(p.is_absolute() and '..' not in p.parts and p.parent.resolve(strict=True)==EXPORT_ROOT.resolve(strict=True) and p.name.startswith(EXPORT_PREFIX),'export path invalid')
    require(p.is_dir() and not p.is_symlink(),'export directory missing');s=p.lstat();require(s.st_uid==u.pw_uid and s.st_gid==u.pw_gid and stat.S_IMODE(s.st_mode)==0o700 and not any(p.iterdir()),'export directory unsafe');return p
def load_config(commit:str)->dict[str,Any]:
    p=c.load_json_file(CONFIG); fields={'schema_version','audit','commit_sha','d4_file','d4_sha256','d3_file','d3_sha256','contract_sha256','request_file','request_sha256','dispatcher_sha256',*c.AUTHORITY_FLAGS}
    require(set(p)==fields and p.get('schema_version')==1 and p.get('audit')==c.AUDIT and p.get('commit_sha')==commit==EXPECTED_TARGET_SHA,'config identity mismatch')
    require(p.get('d3_sha256')==c.D3_SHA and all(p.get(k) is False for k in c.AUTHORITY_FLAGS),'config authority drift')
    require(all(isinstance(p.get(k),str) and c.HEX_RE.fullmatch(p[k]) for k in ('d4_sha256','contract_sha256','request_sha256','dispatcher_sha256')),'config SHA invalid')
    require(p.get('request_file')==str(REQUEST),'request path mismatch');return p
def load_request(config:dict[str,Any]):
    require(regular_root_file(REQUEST,0o600),'request missing or unsafe');require(sha_file(REQUEST)==config['request_sha256'],'request SHA drift')
    try:p=json.loads(REQUEST.read_text())
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as e:raise EncryptedDispatchError('request invalid') from e
    require(isinstance(p,dict),'request root invalid');return p,c.validate_request_payload(p,backup_root=BACKUP_ROOT,file_check=regular_root_file,hasher=sha_file)
def validate_runtime(config:dict[str,Any],commit:str)->Path:
    r=RUNTIME_ROOT/commit;d4=r/'aldi_gate_d4_backup_discovery.py';d3=r/'aldi_gate_d3_recovery_inventory.py'
    require(c.root_runtime_dir(r) and c.root_runtime_file(d4) and c.root_runtime_file(d3),'runtime missing or unsafe')
    require(config['d4_file']==str(d4) and config['d3_file']==str(d3) and sha_file(d4)==config['d4_sha256'] and sha_file(d3)==c.D3_SHA,'runtime identity drift')
    require(sha_file(CONTRACT_PATH)==config['contract_sha256'] and sha_file(Path(__file__))==config['dispatcher_sha256'],'bridge identity drift');return d4
def validate_age_key()->None:require(regular_root_file(AGE_KEY,0o600),'age identity missing or unsafe')
def select_age_binary()->Path:
    for p in AGE_BINARIES:
        try:s=p.lstat()
        except OSError:continue
        if stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_uid==0 and not (stat.S_IMODE(s.st_mode)&0o022):return p
    raise EncryptedDispatchError('reviewed age executable unavailable')
def mount_fstype(path:Path)->str|None:
    target=str(path.resolve(strict=True));best=None
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        parts=line.split();sep=parts.index('-') if '-' in parts else -1
        if sep>0 and target==parts[4]:best=parts[sep+1]
    return best
def prepare_tmpfs(user:pwd.struct_passwd,total:int)->Path:
    require(mount_fstype(TMPFS_PARENT)=='tmpfs','plaintext parent is not tmpfs');free=shutil.disk_usage(TMPFS_PARENT).free;require(free>=max(total*2,64*1024*1024),'insufficient tmpfs capacity')
    p=Path(tempfile.mkdtemp(prefix='hermes-d4e-',dir=TMPFS_PARENT));os.chown(p,user.pw_uid,user.pw_gid);os.chmod(p,0o700);return p
def decrypt_one(age:Path,user:pwd.struct_passwd,input_id:str,source:Path,expected:str,run_dir:Path)->Path:
    before=source.lstat();require(stat.S_ISREG(before.st_mode) and not source.is_symlink(),'ciphertext changed type');flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0);fd=os.open(source,flags)
    dest=run_dir/f'{input_id}.tar.gz'
    try:
        opened=os.fstat(fd);require((opened.st_dev,opened.st_ino)==(before.st_dev,before.st_ino),'ciphertext changed during open');require(_sha_fd(fd)==expected,'ciphertext SHA mismatch')
        with dest.open('xb') as out:
            cp=subprocess.run([str(age),'-d','-i',str(AGE_KEY),f'/proc/self/fd/{fd}'],stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.PIPE,pass_fds=(fd,),check=False,timeout=180)
        require(cp.returncode==0,'age decrypt failed');after=os.fstat(fd);require((after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)==(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns),'ciphertext changed during decrypt')
        require(dest.stat().st_size>2 and dest.open('rb').read(2)==b'\x1f\x8b','decrypted payload is not gzip');os.chown(dest,user.pw_uid,user.pw_gid);os.chmod(dest,0o600);return dest
    except Exception:
        dest.unlink(missing_ok=True);raise
    finally:os.close(fd)
def _sha_fd(fd:int)->str:
    h=hashlib.sha256();os.lseek(fd,0,os.SEEK_SET)
    for b in iter(lambda:os.read(fd,1024*1024),b''):h.update(b)
    os.lseek(fd,0,os.SEEK_SET);return h.hexdigest()
def audit_user_command(*args:str):
    return subprocess.run(['/usr/sbin/runuser','-u',AUDIT_USER,'--','/usr/bin/env','-i','HOME=/home/andris','USER=andris','LOGNAME=andris','PATH=/usr/local/bin:/usr/bin:/bin','LANG=C.UTF-8',*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=180)
def write_manifest(export:Path,*,commit_sha:str,request_sha:str,d4_sha:str,result:dict[str,Any],encrypted_rows:list[tuple[str,Path,str]])->None:
    (export/'dispatcher-evidence-manifest.json').write_bytes(canonical_bytes(c.evidence_manifest(commit_sha=commit_sha,request_sha=request_sha,d4_sha=d4_sha,result=result,rows=encrypted_rows))+b'\n')
def cleanup_tmpfs(p:Path|None)->None:
    if p is None:return
    shutil.rmtree(p);require(not p.exists(),'tmpfs plaintext cleanup failed')

def main()->int:
    stage='argument_validation';reason='dispatch_error';export=None;run_dir=None
    try:
        require(os.geteuid()==0 and len(sys.argv)==3,'dispatcher invocation invalid');commit,raw=sys.argv[1],sys.argv[2];require(commit==EXPECTED_TARGET_SHA,'unexpected runtime SHA')
        stage='runner_validation';runner=pwd.getpwnam(RUNNER_USER);user=pwd.getpwnam(AUDIT_USER);require(not runner_in_docker_group(RUNNER_USER),'runner docker group forbidden')
        stage='export_validation';export=validate_export_dir(Path(raw),runner)
        stage='config_validation';config=load_config(commit)
        stage='request_validation';_request,rows=load_request(config)
        stage='runtime_validation';d4=validate_runtime(config,commit)
        stage='age_environment_validation';validate_age_key();age=select_age_binary()
        stage='tmpfs_preparation';run_dir=prepare_tmpfs(user,sum(p.stat().st_size for _i,p,_d in rows))
        files=[]
        for i,p,d in rows:
            stage='age_decryption';files.append({'id':i,'path':str(decrypt_one(age,user,i,p,d,run_dir))})
        internal=run_dir/'request.json';internal.write_bytes(canonical_bytes({'schema_version':2,'issue_number':c.PARENT_ISSUE,'authoritative_source_set_complete':False,'roots':[],'files':files})+b'\n');os.chown(internal,user.pw_uid,user.pw_gid);os.chmod(internal,0o600)
        result_path=run_dir/'result.json';stage='d4_cli_preflight';require(audit_user_command('/usr/bin/python3',str(d4),'--help').returncode==0,'D4 CLI preflight failed')
        stage='d4_execution';cp=audit_user_command('/usr/bin/python3',str(d4),'--request',str(internal),'--output',str(result_path));reason=f'd4_exit_{cp.returncode}';require(cp.returncode==0,'D4 execution failed')
        result=json.loads(result_path.read_text());stage='result_validation';validate_result(result,len(rows));stage='tmpfs_cleanup';cleanup_tmpfs(run_dir);run_dir=None
        stage='result_export';(export/'diagnostic-result.json').write_bytes(canonical_bytes(result)+b'\n');(export/'diagnostic-exit-code.txt').write_text('0\n');write_manifest(export,commit_sha=commit,request_sha=config['request_sha256'],d4_sha=config['d4_sha256'],result=result,encrypted_rows=rows);return 0
    except Exception as e:
        if run_dir is not None:
            try:shutil.rmtree(run_dir)
            except Exception:reason='tmpfs_cleanup_failed'
        if export is not None:
            failure={'schema_version':1,'audit':c.AUDIT,'error_type':type(e).__name__,'failure_stage':stage,'reason_code':reason,'raw_exception_exported':False,'raw_stderr_exported':False,'raw_request_exported':False,'age_identity_exported':False,'plaintext_exported':False}
            try:(export/'diagnostic-failure.json').write_bytes(canonical_bytes(failure)+b'\n')
            except Exception:pass
        return 1
if __name__=='__main__':raise SystemExit(main())
