"""Standard-library client for the installed live debug interface."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import uuid


class LiveClient:
    def __init__(self, session):
        self.session = Path(session)
        data = json.loads(self.session.read_text(encoding='utf-8'))
        if not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}', data['url']):
            raise ValueError('调试地址必须是127.0.0.1')
        self.url, self.token = data['url'], data['token']
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path, body=None, binary=False):
        headers = {'Authorization': 'Bearer '+self.token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.url+path, headers=headers,
                          data=None if body is None else json.dumps(body).encode('utf-8'))
        try:
            with self.opener.open(request, timeout=6) as response:
                value = response.read()
                return (value, dict(response.headers)) if binary else json.loads(value)
        except HTTPError as error:
            body = error.read()
            try:
                value = json.loads(body)
            except ValueError:
                value = None
            detail = value.get('error') if isinstance(value, dict) else None
            raise ValueError(detail or f'HTTP {error.code}') from error

    def command(self, command, timeout=15):
        command = dict(command)
        if command['op'] in ('click', 'drag', 'scroll', 'key', 'action'):
            frame = self.request('/status')['frame']
            if frame is None:
                raise ValueError('尚无游戏画面')
            command.setdefault('frame_id', frame['id'])
            command.setdefault('hwnd', frame['hwnd'])
        command.setdefault('request_id', uuid.uuid4().hex)
        job = self.request('/commands', command)
        deadline = time.monotonic()+timeout
        while job['state'] in ('queued', 'running'):
            if time.monotonic() >= deadline:
                self.request('/cancel/'+job['id'], {})
                raise TimeoutError('调试指令超时，已发送取消请求')
            time.sleep(.1)
            job = self.request('/jobs/'+job['id'])
        if job['state'] != 'done':
            raise ValueError(job.get('error', job['state']))
        return job

    def save_frame(self, destination):
        data, headers = self.request('/frame.png', binary=True)
        path = Path(destination).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        frame_id = int(headers['X-Frame-Id'])
        status = self.request('/status')
        sidecar = path.with_suffix('.json')
        sidecar.write_text(json.dumps({'image_frame_id': frame_id, 'status': status},
                                     ensure_ascii=False, indent=2), encoding='utf-8')
        return {'path': str(path), 'frame_id': frame_id, 'status_file': str(sidecar)}


def find_session(root):
    root = Path(root).resolve()
    candidates = [root/'debug/live/session.json', *root.glob('dist/ok-zzz-fixed-*/debug/live/session.json')]
    candidates = sorted((p for p in candidates if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            client = LiveClient(path)
            status = client.request('/status')
            if status['monitoring']:
                return path
        except Exception:
            continue
    raise ValueError('没有运行中的实时调试接口：在调试页点击「开始监控」，'
                     '或运行 tools/live_debug.py --root <运行目录> enable')


def enable_session(root, timeout=15.0):
    """Ask the ok-zzz running in `root` to start monitoring, then wait for its session."""
    from src.live.request import write_request
    root = Path(root).resolve()
    try:
        return find_session(root)
    except ValueError:
        pass
    folder = root/'debug/live'
    write_request(folder)
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        time.sleep(.5)
        try:
            return find_session(root)
        except ValueError:
            continue
    (folder/'request').unlink(missing_ok=True)
    raise ValueError(f'{timeout:g}秒内未开启实时调试：请确认ok-zzz正在 {root} 运行（版本需支持按需开启）')


def run(argv=None):
    # Chinese Windows consoles default to GBK; task names contain emoji that GBK cannot encode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description='ok-zzz本机实时调试客户端')
    parser.add_argument('--session', help='debug/live/session.json的绝对路径')
    parser.add_argument('--root', default=str(Path.cwd()))
    parser.add_argument('--output', help='保存JSON结果，适用于无控制台EXE')
    subs = parser.add_subparsers(dest='operation', required=True)
    subs.add_parser('status')
    enable = subs.add_parser('enable', help='请求正在运行的ok-zzz开启实时调试并等待会话')
    enable.add_argument('--timeout', type=float, default=15)
    subs.add_parser('release')
    events = subs.add_parser('events')
    events.add_argument('--after', type=int, default=0)
    frame = subs.add_parser('frame')
    frame.add_argument('path')
    command = subs.add_parser('command')
    command.add_argument('json', help='JSON指令，或@文件路径')
    command.add_argument('--timeout', type=float, default=15)
    bundle = subs.add_parser('bundle')
    bundle.add_argument('folder')
    watch = subs.add_parser('watch')
    watch.add_argument('--seconds', type=float, default=0, help='0表示持续监控')
    watch.add_argument('--interval', type=float, default=1)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'enable':
            session = Path(args.session) if args.session else enable_session(args.root, args.timeout)
            client = LiveClient(session)
            status = client.request('/status')
        else:
            client = LiveClient(args.session or find_session(args.root))
        if args.operation == 'enable':
            result = {'session': str(session), 'url': client.url, 'monitoring': status['monitoring'],
                      'session_id': status['session_id']}
        elif args.operation == 'status':
            result = client.request('/status')
        elif args.operation == 'release':
            result = client.request('/release', {})
        elif args.operation == 'events':
            result = client.request('/events?after='+str(args.after))
        elif args.operation == 'frame':
            result = client.save_frame(args.path)
        elif args.operation == 'command':
            content = Path(args.json[1:]).read_text(encoding='utf-8-sig') if args.json.startswith('@') else args.json
            result = client.command(json.loads(content), timeout=args.timeout)
        elif args.operation == 'bundle':
            folder = Path(args.folder).resolve()
            folder.mkdir(parents=True, exist_ok=True)
            result = client.save_frame(folder/'frame.png')
            (folder/'events.json').write_text(json.dumps(client.request('/events'), ensure_ascii=False, indent=2), encoding='utf-8')
        elif args.operation == 'watch':
            if args.interval < .25:
                raise ValueError('监控间隔至少0.25秒')
            deadline = time.monotonic()+args.seconds if args.seconds else float('inf')
            while time.monotonic() < deadline:
                result = {'time': datetime.now().isoformat(), **client.request('/status')}
                line = json.dumps(result, ensure_ascii=False)
                if args.output:
                    with Path(args.output).open('a', encoding='utf-8') as file:
                        file.write(line+'\n')
                else:
                    print(line, flush=True)
                time.sleep(args.interval)
            return 0
    except Exception as error:
        result = {'error': str(error)}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding='utf-8')
    else:
        print(text)
    return 1 if 'error' in result else 0
