#!/usr/bin/env python3
from __future__ import annotations
import grp,hashlib,importlib.util,json,os,pwd,stat,subprocess,sys,tempfile
from pathlib import Path

REPO=Path('/home/andris/hermes-deals-audit-source');AUDIT_USER='andris';RUNNER_USER='github-runner'
EXPECTED_TARGET_SHA='8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e'
EXPECTED_D4_BLOB='f8ec4abb3f0c416335144f0f18e8a7c323353f4a';EXPECTED_D3_BLOB='4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7'
EXPECTED_CONTRACT_BLOB='efe99cd59f04df53b62b47dc83fe6afc4c46f57c';EXPECTED_DISPATCHER_BLOB='ad2258201b94299d7ffdfa2a5b1841c4c150c8a5'
D4_PATH='tools/aldi_gate_d4_backup_discovery.py';D3_PATH='tools/aldi_gate_d3_recovery_inventory.py';CONTRACT_PATH='tools/runner/aldi_gate_d4_encrypted_contract.py';DISPATCHER_PATH='tools/runner/aldi_gate_d4_encrypted_backup_dispatch.py'
OWNER_REQUEST=Path('/home/andris/aldi-gate-d4-encrypted-request.json');AGE_KEY=Path('/etc/rpi5-backup/age.key');BACKUP_ROOT=Path('/opt/backups')
RUNTIME_ROOT=Path('/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery');BRIDGE_ROOT=Path('/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-encrypted-backup-discovery')
DISPATCH_DST=Path('/usr/local/sbin/hermes-deals-aldi-gate-d4-encrypted-backup-discovery');CONFIG_DST=Path('/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery.json');REQUEST_DST=Path('/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery-request.json');SUDOERS_DST=Path('/etc/sudoers.d/hermes-deals-aldi-gate-d4-encrypted-backup-discovery')
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'

class RegistrationError(RuntimeError):pass
def require(v,msg):
    if not v:raise RegistrationError(msg)
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def sha_file(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def git(*a,check=True):
    cp=subprocess.run(['/usr/sbin/runuser','-u',AUDIT_USER,'--','/usr/bin/env','-i','HOME=/home/andris','USER=andris','LOGNAME=andris','PATH=/usr/local/bin:/usr/bin:/bin','LANG=C.UTF-8','GIT_OPTIONAL_LOCKS=0','/usr/bin/git','-C',str(REPO),*a],stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,check=False,timeout=30)
    if check:require(cp.returncode==0 and not cp.stderr,f'git failed: {a[0]}')
    return cp
def text(*a):return git(*a).stdout.decode().strip()
def index_snapshot():
    p=REPO/'.git/index';require(p.is_file() and not p.is_symlink() and not (REPO/'.git/index.lock').exists(),'audit index unsafe');s=p.stat();return (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_size,sha_file(p))
def validate_source(target):
    before=index_snapshot();require(text('branch','--show-current')=='main' and git('status','--porcelain=v1','-z','--untracked-files=all').stdout==b'','audit repo not clean main');head=text('rev-parse','HEAD');require(target==EXPECTED_TARGET_SHA and text('rev-parse','--verify',f'{target}^{{commit}}')==target,'target unavailable');require(git('merge-base','--is-ancestor',target,head,check=False).returncode==0,'target not ancestor')
    for p,b in ((D4_PATH,EXPECTED_D4_BLOB),(D3_PATH,EXPECTED_D3_BLOB),(CONTRACT_PATH,EXPECTED_CONTRACT_BLOB),(DISPATCHER_PATH,EXPECTED_DISPATCHER_BLOB)):require(text('rev-parse',f'HEAD:{p}' if p in {CONTRACT_PATH,DISPATCHER_PATH} else f'{target}:{p}')==b,f'blob drift: {p}')
    require(index_snapshot()==before,'index changed');return before,head
def blob(oid):return git('cat-file','blob',oid).stdout
def regular_root_file(p,mode):
    try:s=p.lstat()
    except OSError:return False
    return stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_uid==0 and s.st_gid==0 and stat.S_IMODE(s.st_mode)==mode
def audit_file(p,mode):
    try:s=p.lstat();u=pwd.getpwnam(AUDIT_USER)
    except OSError:return False
    return stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_uid==u.pw_uid and s.st_gid==u.pw_gid and stat.S_IMODE(s.st_mode)==mode
def load_contract():
    p=REPO/CONTRACT_PATH
    if not p.exists():p=Path(__file__).with_name('aldi_gate_d4_encrypted_contract.py')
    spec=importlib.util.spec_from_file_location('d4e_contract_registration',p);require(spec and spec.loader,'contract import unavailable');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def validate_request_payload(payload):
    m=load_contract()
    try:return m.validate_request_payload(payload,backup_root=BACKUP_ROOT,file_check=regular_root_file,hasher=sha_file)
    except Exception as e:raise RegistrationError(str(e)) from e
def load_request():
    require(audit_file(OWNER_REQUEST,0o600),'owner request missing or unsafe');raw=OWNER_REQUEST.read_bytes();payload=json.loads(raw);validate_request_payload(payload);return raw,hashlib.sha256(raw).hexdigest()
def validate_age():
    require(regular_root_file(AGE_KEY,0o600),'age identity missing or unsafe');ok=False
    for p in (Path('/usr/bin/age'),Path('/usr/local/bin/age')):
        try:s=p.lstat()
        except OSError:continue
        if stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_uid==0 and not(stat.S_IMODE(s.st_mode)&0o022):ok=True
    require(ok,'reviewed age executable unavailable')
def validate_runner():
    require(subprocess.run(['/usr/bin/systemctl','is-active','--quiet',RUNNER_SERVICE],check=False).returncode==0,'audit runner inactive');u=pwd.getpwnam(RUNNER_USER);groups={g.gr_name for g in grp.getgrall() if RUNNER_USER in g.gr_mem}|{grp.getgrgid(u.pw_gid).gr_name};require('docker' not in groups,'runner docker group forbidden')
def mkdir_root(p,mode=0o755):
    p.mkdir(parents=True,exist_ok=True,mode=mode);require(p.is_dir() and not p.is_symlink(),'install dir unsafe');os.chown(p,0,0);os.chmod(p,mode)
def atomic(p,b,mode):
    p.parent.mkdir(parents=True,exist_ok=True);fd,n=tempfile.mkstemp(prefix=f'.{p.name}.',dir=p.parent);t=Path(n)
    try:
        with os.fdopen(fd,'wb') as f:f.write(b);f.flush();os.fsync(f.fileno())
        os.chown(t,0,0);os.chmod(t,mode);os.replace(t,p)
    finally:t.unlink(missing_ok=True)
def runtime(target,d4b,d3b):
    mkdir_root(RUNTIME_ROOT);r=RUNTIME_ROOT/target
    if r.exists():
        require(r.is_dir() and not r.is_symlink(),'existing runtime target unsafe');s=r.stat();require(s.st_uid==0 and s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o755,'existing runtime metadata drift')
    else:mkdir_root(r)
    for n,b in (('aldi_gate_d4_backup_discovery.py',d4b),('aldi_gate_d3_recovery_inventory.py',d3b)):
        p=r/n;d=sha_bytes(b)
        if p.exists():require(regular_root_file(p,0o444) and sha_file(p)==d,f'runtime drift: {n}')
        else:atomic(p,b,0o444)
    require(sha_file(r/'aldi_gate_d3_recovery_inventory.py')=='606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8','D3 SHA drift');return r
def sudoers():
    line=f'{RUNNER_USER} ALL=(root) NOPASSWD: {DISPATCH_DST} {EXPECTED_TARGET_SHA} /home/github-runner/_work/_temp/hermes-deals-aldi-gate-d4-encrypted-backup-*\n';fd,n=tempfile.mkstemp(dir=SUDOERS_DST.parent);t=Path(n)
    try:
        os.write(fd,line.encode());os.close(fd);os.chown(t,0,0);os.chmod(t,0o440);cp=subprocess.run(['/usr/sbin/visudo','-cf',str(t)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False);require(cp.returncode==0,'sudoers invalid');os.replace(t,SUDOERS_DST)
    finally:
        try:os.close(fd)
        except OSError:pass
        t.unlink(missing_ok=True)
def main():
    if os.geteuid()!=0 or len(sys.argv)!=2 or sys.argv[1]!=EXPECTED_TARGET_SHA:return 2
    try:
        before,head=validate_source(sys.argv[1]);validate_runner();validate_age();request,request_sha=load_request();d4b,d3b,contract,dispatcher=map(blob,(EXPECTED_D4_BLOB,EXPECTED_D3_BLOB,EXPECTED_CONTRACT_BLOB,EXPECTED_DISPATCHER_BLOB));require(index_snapshot()==before,'index changed reading blobs');r=runtime(sys.argv[1],d4b,d3b);mkdir_root(BRIDGE_ROOT);atomic(BRIDGE_ROOT/'contract.py',contract,0o444);atomic(DISPATCH_DST,dispatcher,0o755);atomic(REQUEST_DST,request,0o600);sudoers()
        cfg={'schema_version':1,'audit':'aldi-gate-d4-encrypted-backup-discovery','commit_sha':sys.argv[1],'d4_file':str(r/'aldi_gate_d4_backup_discovery.py'),'d4_sha256':sha_bytes(d4b),'d3_file':str(r/'aldi_gate_d3_recovery_inventory.py'),'d3_sha256':sha_bytes(d3b),'contract_sha256':sha_bytes(contract),'request_file':str(REQUEST_DST),'request_sha256':request_sha,'dispatcher_sha256':sha_bytes(dispatcher),**{k:False for k in load_contract().AUTHORITY_FLAGS}};atomic(CONFIG_DST,(json.dumps(cfg,sort_keys=True,indent=2)+'\n').encode(),0o600)
        require(index_snapshot()==before and text('rev-parse','HEAD')==head and git('status','--porcelain=v1','-z','--untracked-files=all').stdout==b'','audit repo changed')
        print('REGISTRATION_RESULT=PASS');print(f'REGISTERED_COMMIT={sys.argv[1]}');print(f'AUDIT_REPO_HEAD_UNCHANGED={head}');print(f'D4_GIT_BLOB={EXPECTED_D4_BLOB}');print(f'D3_GIT_BLOB={EXPECTED_D3_BLOB}');print(f'CONTRACT_GIT_BLOB={EXPECTED_CONTRACT_BLOB}');print(f'DISPATCHER_GIT_BLOB={EXPECTED_DISPATCHER_BLOB}');print(f'REQUEST_SHA256={request_sha}');print('DECRYPTION_EXECUTED=false');print('NON_REWIND_REGISTRATION=true');print('AUDIT_REPO_INDEX_PRESERVED=true');print('RUNNER_HAS_DOCKER_GROUP=false');return 0
    except Exception as e:print(f'REGISTRATION_RESULT=BLOCKED error_type={type(e).__name__}',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
