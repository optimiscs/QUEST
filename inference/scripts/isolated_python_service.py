"""Loopback SandboxFusion-compatible Python executor with chroot and seccomp.

This is a limited Python backend, not the upstream SandboxFusion server.
"""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2] / 'workspace/strict-reproduction/sandbox-isolated/rootfs'
SLOTS = queue.Queue()
for index in range(8):
    SLOTS.put(62000 + index)

DRIVER = r'''
import ctypes,errno,io,json,os,resource,sys
payload=json.loads(sys.stdin.read())
os.chdir('/tmp/'+payload['work'])
sys.stdin=io.StringIO(payload.get('stdin') or '')
resource.setrlimit(resource.RLIMIT_CPU,(55,55))
resource.setrlimit(resource.RLIMIT_AS,(1536*1024**2,1536*1024**2))
resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024**2,4*1024**2))
resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
lib=ctypes.CDLL('/usr/lib/x86_64-linux-gnu/libseccomp.so.2')
lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
lib.seccomp_load.argtypes=[ctypes.c_void_p]
ctx=lib.seccomp_init(0x7fff0000)
if not ctx: raise RuntimeError('seccomp init failed')
for name in ['socket','socketpair','connect','accept','accept4','bind','listen','clone','clone3','fork','vfork','execve','execveat','ptrace','kill','tkill','tgkill','pidfd_open','pidfd_send_signal','mount','umount2','unshare','setns','bpf','keyctl','open_by_handle_at','process_vm_readv','process_vm_writev','io_uring_setup','io_uring_enter','io_uring_register']:
    nr=lib.seccomp_syscall_resolve_name(name.encode())
    if nr>=0 and lib.seccomp_rule_add(ctx,0x50000|errno.EPERM,nr,0)!=0:raise RuntimeError('seccomp rule failed')
if lib.seccomp_load(ctx)!=0:raise RuntimeError('seccomp load failed')
exec(compile(payload['code'],'<QUEST-python-tool>','exec'),{'__name__':'__main__'})
'''


def execute(request):
    if request.get('language') != 'python' or not isinstance(request.get('code'), str):
        return {'status': 'SandboxError', 'message': 'Only Python code is supported', 'files': {}}
    if request.get('files') or request.get('fetch_files'):
        return {'status': 'SandboxError', 'message': 'File upload and retrieval are not supported by this backend', 'files': {}}
    timeout = min(max(float(request.get('run_timeout') or 50), 1), 50)
    try:
        uid = SLOTS.get(timeout=60)
    except queue.Empty:
        return {'status': 'SandboxError', 'message': 'Python sandbox capacity unavailable', 'files': {}}
    work = uuid.uuid4().hex
    directory = ROOT / 'tmp' / work
    started = time.monotonic()
    try:
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, uid)
        payload = json.dumps({'code': request['code'], 'stdin': request.get('stdin'), 'work': work})
        cmd = ['/usr/sbin/chroot', f'--userspec={uid}:{uid}', '--groups=', str(ROOT),
               '/opt/python/bin/python3.10', '-I', '-c', DRIVER]
        env = {'PATH': '/opt/python/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
               'MPLCONFIGDIR': '/tmp/' + work}
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                proc = subprocess.run(cmd, input=payload.encode(), stdout=stdout, stderr=stderr,
                                      timeout=timeout, env=env, start_new_session=True)
                status, rc = 'Finished', proc.returncode
            except subprocess.TimeoutExpired:
                status, rc = 'TimeLimitExceeded', None
            stdout.seek(0); stderr.seek(0)
            out = stdout.read(100000).decode('utf-8', errors='replace')
            err = stderr.read(100000).decode('utf-8', errors='replace')
        return {'status': 'Success' if status == 'Finished' and rc == 0 else 'Failed',
                'message': 'Restricted local Python executor; not upstream SandboxFusion',
                'run_result': {'status': status, 'execution_time': time.monotonic() - started,
                               'return_code': rc, 'stdout': out, 'stderr': err}, 'files': {}}
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        SLOTS.put(uid)


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path in ('/health', '/v1/ping'):
            self.respond(200, {'status': 'ok', 'backend': 'isolated-python', 'capacity': 8})
        else:
            self.respond(404, {'error': 'not found'})

    def do_POST(self):
        if self.path != '/run_code':
            self.respond(404, {'error': 'not found'}); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2_000_000:
                self.respond(413, {'error': 'invalid request size'}); return
            request = json.loads(self.rfile.read(length))
            self.respond(200, execute(request))
        except (ValueError, TypeError, OSError, json.JSONDecodeError):
            self.respond(400, {'error': 'invalid request or execution setup'})


if __name__ == '__main__':
    if not (ROOT / 'opt/python/bin/python3.10').is_file():
        raise SystemExit('Prepare the isolated Python runtime first')
    ThreadingHTTPServer(('127.0.0.1', 8080), Handler).serve_forever()
