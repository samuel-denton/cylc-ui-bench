"""Local web GUI: configure and start runs, and browse results.

Serves on 127.0.0.1 only. Every request must carry the access token, which is
given once in the URL (?token=...) and then kept in a cookie, so other users
on a shared machine can't use the server. POSTs also need an
X-Requested-With header, which other sites can't send without permission.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import traceback
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from .report import render_html
from .runner import (
    Config, RunError, Runner, raise_interrupt, default_results_dir, find_cylc_ui, make_run_dir,
)
from .suites import SUITES
from .summarise import load, summarise

GUI_DIR = (Path(__file__).parent / 'gui').resolve()
PACKAGE_PARENT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r'\w[\w.-]*')
ACTIVE = ('starting', 'running')
MAX_BODY = 1 << 20
CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
}


class Conflict(Exception):
    """The request clashes with the current state, e.g. a run is in progress."""


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _tail(path: Optional[Path], lines: int = 200) -> str:
    if path is None or not path.is_file():
        return ''
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 64 * 1024))
        text = f.read().decode(errors='replace')
    return '\n'.join(text.splitlines()[-lines:])


def _is_runner(pid: Optional[int]) -> bool:
    """Whether pid is a live cylc-ui-bench process on this machine."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if Path('/proc').is_dir():
        try:
            cmdline = Path(f'/proc/{pid}/cmdline').read_bytes()
        except OSError:
            return False
        return b'cylc_ui_bench' in cmdline or b'cylc-ui-bench' in cmdline
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


class Results:
    """The runs in a results directory, and runs launched from the GUI."""

    def __init__(self, root: Path):
        self.root = root
        self.launched: Dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()

    def path(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(run_id) or not (self.root / run_id).is_dir():
            raise KeyError(run_id)
        return self.root / run_id

    def list(self) -> List[dict]:
        for proc in self.launched.values():
            proc.poll()  # reap finished runs
        if not self.root.is_dir():
            return []
        runs = []
        for path in sorted(self.root.iterdir(), reverse=True):
            if path.is_dir() and RUN_ID.fullmatch(path.name):
                info = self.info(path)
                if info:
                    runs.append(info)
        runs.sort(key=lambda r: r['created'] or '', reverse=True)
        return runs

    def _launch_state(self, run_id: str) -> str:
        proc = self.launched.get(run_id)
        if proc is None:
            return 'unknown'
        return 'starting' if proc.poll() is None else 'error'

    def info(self, path: Path) -> Optional[dict]:
        config = _read_json(path / 'config.json')
        jsonl = sorted(path.glob('*.jsonl'))
        if config is None:
            if path.name in self.launched:
                config = {}
            elif jsonl:
                return self._legacy(path, jsonl)
            else:
                return None
        status = _read_json(path / 'status.json') or {}
        state = status.get('state') or self._launch_state(path.name)
        local = config.get('host') in (None, socket.gethostname())
        if state == 'running' and local and not _is_runner(status.get('pid')):
            state = 'died'
        return {
            'id': path.name,
            'legacy': False,
            'state': state,
            'created': config.get('created') or status.get('started'),
            'refs': [r['label'] for r in config.get('refs', [])],
            'suites': config.get('suites', []),
            'scales': config.get('scales', {}),
            'rounds': config.get('rounds'),
            'iterations': config.get('iterations'),
            'sessions': config.get('sessions'),
            'delay': config.get('delay'),
            'only': config.get('only'),
            'host': config.get('host'),
            'total': status.get('total'),
            'done': status.get('done', 0),
            'failed': status.get('failed', 0),
            'current': status.get('current'),
            'started': status.get('started'),
            'finished': status.get('finished'),
        }

    def _legacy(self, path: Path, jsonl: List[Path]) -> dict:
        """Results from before run directories had config.json/status.json."""
        try:
            runs = load(jsonl)
        except ValueError:
            runs = []
        metas = [r.get('meta', {}) for r in runs]
        dates = sorted(m['date'] for m in metas if m.get('date'))
        return {
            'id': path.name,
            'legacy': True,
            'state': 'legacy',
            'created': dates[0] if dates else None,
            'refs': list(dict.fromkeys(m.get('label') for m in metas)),
            'suites': sorted({m.get('suite', 'store') for m in metas}),
            'total': len(runs),
            'done': len(runs),
            'failed': 0,
            'started': dates[0] if dates else None,
            'finished': dates[-1] if dates else None,
        }

    def detail(self, run_id: str) -> dict:
        path = self.path(run_id)
        info = self.info(path)
        if info is None:
            raise KeyError(run_id)
        jsonl = sorted(path.glob('*.jsonl'))
        try:
            summary = summarise(load(jsonl)) if jsonl else ''
        except Exception as exc:  # partial or malformed results shouldn't break the page
            summary = f'could not summarise results: {exc}'
        log = path / 'run.log'
        if not log.exists():
            logs = [p for p in path.glob('*.log') if p.name != 'stderr.log']
            log = max(logs, key=lambda p: p.stat().st_mtime, default=None)
        return {
            **info,
            'path': str(path),
            'summary': summary,
            'log': _tail(log),
            'stderr': _tail(path / 'stderr.log'),
        }

    def report(self, run_id: str) -> str:
        jsonl = sorted(self.path(run_id).glob('*.jsonl'))
        if not jsonl or not any(p.stat().st_size for p in jsonl):
            return '<!doctype html><p style="font-family: sans-serif">No results yet.</p>'
        return render_html(jsonl)

    def start(self, body: dict, cylc_ui: Path) -> str:
        with self.lock:
            active = [r['id'] for r in self.list() if r['state'] in ACTIVE]
            if active:
                raise Conflict(f'run {active[0]} is in progress; wait for it or stop it first')
            config = config_from_request(body, cylc_ui)
            runner = Runner(config)
            runner.validate()
            if not config.fetch:
                runner.resolve_refs()
            run_dir = make_run_dir(self.root)
            cmd = [
                sys.executable, '-m', 'cylc_ui_bench.cli', 'run',
                '--run-dir', str(run_dir), '-C', str(runner.repo),
                '-r', str(config.rounds), '-i', str(config.iterations),
                '-n', str(config.sessions), '-d', str(config.delay),
            ]
            for suite in config.suites:
                cmd += ['-s', suite]
            for scale in config.scales:
                cmd += ['--scale', scale]
            if config.only:
                cmd += ['--only', config.only]
            if config.fetch:
                cmd.append('--fetch')
            cmd += ['--', *config.refs]
            pythonpath = [str(PACKAGE_PARENT), os.environ.get('PYTHONPATH', '')]
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, pythonpath))}
            with open(run_dir / 'stderr.log', 'w') as stderr:
                # own session, so the run carries on if the GUI is stopped
                self.launched[run_dir.name] = subprocess.Popen(
                    cmd, cwd=run_dir, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=stderr, start_new_session=True,
                )
            return run_dir.name

    def stop(self, run_id: str) -> None:
        path = self.path(run_id)
        info = self.info(path)
        if not info or info['state'] not in ACTIVE:
            raise Conflict('run is not in progress')
        if info.get('host') not in (None, socket.gethostname()):
            raise Conflict(f"run is on another host ({info['host']})")
        pid = (_read_json(path / 'status.json') or {}).get('pid')
        proc = self.launched.get(run_id)
        if not _is_runner(pid) and proc is not None:
            pid = proc.pid
        if not _is_runner(pid):
            raise Conflict('run process not found')
        os.kill(pid, signal.SIGTERM)


def config_from_request(body: dict, cylc_ui: Path) -> Config:
    defaults = Config()

    def number(name, kind=int):
        value = body.get(name, getattr(defaults, name))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RunError(f'{name} must be a number')
        if kind is int and value != int(value):
            raise RunError(f'{name} must be a whole number')
        return kind(value)

    def strings(name, default):
        value = body.get(name, default)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise RunError(f'{name} must be a list of strings')
        return [v.strip() for v in value if v.strip()]

    refs = strings('refs', defaults.refs)
    for ref in refs:
        if ref.startswith('-'):
            raise RunError(f'invalid ref: {ref}')
    only = body.get('only') or None
    if only is not None and not isinstance(only, str):
        raise RunError('only must be a string')
    return Config(
        refs=refs,
        cylc_ui=str(cylc_ui),
        suites=strings('suites', defaults.suites) or defaults.suites,
        scales=strings('scales', []),
        rounds=number('rounds'),
        iterations=number('iterations'),
        sessions=number('sessions'),
        delay=number('delay', float),
        only=only,
        fetch=bool(body.get('fetch', False)),
    )


def _git_refs(repo: Path) -> List[str]:
    def git(*args):
        return subprocess.run(
            ['git', '-C', str(repo), *args], capture_output=True, text=True, check=False,
        ).stdout.split()
    remotes = set(git('remote'))
    refs = git(
        'for-each-ref', '--sort=-committerdate', '--format=%(refname:short)',
        'refs/heads', 'refs/remotes', 'refs/tags',
    )
    return [r for r in refs if not r.endswith('/HEAD') and r not in remotes]


class GuiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, results: Results, cylc_ui: Path):
        super().__init__(('127.0.0.1', port), Handler)
        self.port = self.server_address[1]
        self.token = secrets.token_urlsafe(24)
        self.cookie_name = f'cylc_ui_bench_{self.port}'
        self.allowed_hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}
        self.results = results
        self.cylc_ui = cylc_ui

    def options(self) -> dict:
        defaults = asdict(Config())
        return {
            'cylc_ui': str(self.cylc_ui),
            'results_dir': str(self.results.root),
            'host': socket.gethostname(),
            'refs': _git_refs(self.cylc_ui),
            'suites': [
                {
                    'name': s.name,
                    'description': s.description,
                    'default_scales': list(s.default_scales),
                    'scale_help': s.scale_help,
                }
                for s in SUITES.values()
            ],
            'defaults': {k: defaults[k] for k in ('refs', 'rounds', 'iterations', 'sessions', 'delay')},
        }


class Handler(BaseHTTPRequestHandler):
    server: GuiServer
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        pass

    # -- responses ---------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, headers: Optional[dict] = None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data).encode(), 'application/json')

    def _html(self, text: str):
        self._send(200, text.encode(), CONTENT_TYPES['.html'])

    def _error(self, status: int, message: str):
        # the request body may not have been read, so don't reuse the connection
        self.close_connection = True
        if self.path.startswith('/api/'):
            self._json({'error': message}, status)
        else:
            self._send(status, message.encode(), 'text/plain; charset=utf-8')

    # -- auth --------------------------------------------------------------

    def _token_ok(self, token: str) -> bool:
        return hmac.compare_digest(token.encode(), self.server.token.encode())

    def _check(self) -> bool:
        """Check the Host header and the token cookie, replying if they fail."""
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self._error(HTTPStatus.FORBIDDEN, 'unexpected Host header')
            return False
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
        except CookieError:
            cookie = SimpleCookie()
        morsel = cookie.get(self.server.cookie_name)
        if morsel is None or not self._token_ok(morsel.value):
            self._error(
                HTTPStatus.FORBIDDEN,
                'Not authorised: open the URL printed by "cylc-ui-bench gui", which includes the access token.',
            )
            return False
        return True

    # -- requests ----------------------------------------------------------

    def do_GET(self):
        url = urlsplit(self.path)
        token = parse_qs(url.query).get('token')
        if token and self.headers.get('Host') in self.server.allowed_hosts:
            if not self._token_ok(token[0]):
                return self._error(HTTPStatus.FORBIDDEN, 'invalid token')
            # navigate from this page rather than with a redirect: when opened
            # from another site (e.g. the file:// page that opens the browser)
            # a redirect is still cross-site, so the SameSite=Strict cookie
            # would not be sent with it
            return self._send(
                HTTPStatus.OK,
                b'<!doctype html><script>location.replace("/")</script>'
                b'<a href="/">continue to cylc-ui-bench</a>',
                CONTENT_TYPES['.html'],
                {
                    'Set-Cookie': f'{self.server.cookie_name}={self.server.token};'
                                  ' HttpOnly; SameSite=Strict; Path=/',
                },
            )
        if not self._check():
            return
        self._route('GET', url.path, None)

    def do_POST(self):
        if not self._check():
            return
        if self.headers.get('X-Requested-With') != 'cylc-ui-bench':
            return self._error(HTTPStatus.FORBIDDEN, 'missing X-Requested-With header')
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, 'request too large')
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, 'invalid JSON')
        if not isinstance(body, dict):
            return self._error(HTTPStatus.BAD_REQUEST, 'expected a JSON object')
        self._route('POST', urlsplit(self.path).path, body)

    def _route(self, method: str, path: str, body: Optional[dict]):
        results = self.server.results
        routes = [
            ('GET', r'/', lambda: self._static('index.html')),
            ('GET', r'/gui/(.+)', self._static),
            ('GET', r'/api/options', lambda: self._json(self.server.options())),
            ('GET', r'/api/runs', lambda: self._json(results.list())),
            ('GET', r'/api/runs/([^/]+)', lambda i: self._json(results.detail(i))),
            ('GET', r'/api/runs/([^/]+)/report', lambda i: self._html(results.report(i))),
            ('POST', r'/api/runs', lambda: self._json(
                {'id': results.start(body, self.server.cylc_ui)}, HTTPStatus.CREATED)),
            ('POST', r'/api/runs/([^/]+)/stop', lambda i: (results.stop(i), self._json({}))),
        ]
        for route_method, pattern, handler in routes:
            match = re.fullmatch(pattern, path)
            if match and route_method == method:
                try:
                    handler(*match.groups())
                except KeyError:
                    self._error(HTTPStatus.NOT_FOUND, 'not found')
                except RunError as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc))
                except Conflict as exc:
                    self._error(HTTPStatus.CONFLICT, str(exc))
                except Exception as exc:
                    traceback.print_exc()
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f'{type(exc).__name__}: {exc}')
                return
        self._error(HTTPStatus.NOT_FOUND, 'not found')

    def _static(self, name: str):
        path = (GUI_DIR / name).resolve()
        if not path.is_file() or GUI_DIR not in path.parents:
            raise KeyError(name)
        content_type = CONTENT_TYPES.get(path.suffix, 'application/octet-stream')
        self._send(HTTPStatus.OK, path.read_bytes(), content_type)


def _open_browser(url: str, port: int) -> Optional[Path]:
    """Open url via a private redirect file, keeping the token out of `ps`."""
    cache = Path(os.environ.get('BENCH_TMP') or Path.home() / '.cache' / 'cylc-ui-bench')
    cache.mkdir(parents=True, exist_ok=True)
    redirect = cache / f'gui-{port}.html'
    fd = os.open(redirect, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(
            f'<!doctype html><meta http-equiv="refresh" content="0;url={url}">'
            f'<a href="{url}">open cylc-ui-bench</a>\n'
        )
    threading.Thread(target=webbrowser.open, args=(redirect.as_uri(),), daemon=True).start()
    return redirect


def serve(cylc_ui: Optional[str], results_dir: Optional[str], port: int, open_browser: bool = True) -> int:
    try:
        repo = find_cylc_ui(cylc_ui)
    except RunError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    results = Results(Path(results_dir or default_results_dir()).expanduser().resolve())
    try:
        server = GuiServer(port, results, repo)
    except OSError as exc:
        print(f'error: could not start server on port {port}: {exc}', file=sys.stderr)
        return 2
    url = f'http://127.0.0.1:{server.port}/?token={server.token}'
    print(f'cylc-ui-bench GUI: {url}', flush=True)
    print(f'cylc-ui: {repo}\nresults: {results.root}', flush=True)
    print('Ctrl-C to stop (runs started from the GUI carry on)', flush=True)
    redirect = _open_browser(url, server.port) if open_browser else None
    signal.signal(signal.SIGTERM, raise_interrupt)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if redirect:
            redirect.unlink(missing_ok=True)
    return 0
