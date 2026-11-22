"""
Streaming log console for DRAW.

Replaces the third-party ``django-log-viewer`` package:
  * /logs/                    — console page (file picker, filters, actions)
  * /logs/stream/?file=...    — Server-Sent Events live tail (history + new lines)
  * /logs/download/?file=...  — single log file download
  * /logs/download-all/       — zip archive of all log files

All endpoints require Django admin (staff) access.
"""
import io
import json
import os
import time
import zipfile
from datetime import datetime

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

# Maximum lines retained client-side before pruning (informational; enforced in JS)
DEFAULT_WINDOW = 500
MIN_WINDOW = 50
MAX_WINDOW = 5000

# Safety caps
MAX_DOWNLOAD_ALL_BYTES = 500 * 1024 * 1024  # 500 MB total for the zip
TAIL_READ_CAP = 1_000_000                   # only scan the last 1 MB for history
POLL_INTERVAL = 1.0                         # seconds between tail polls
HEARTBEAT_TICKS = 15                        # SSE keep-alive comment every N polls


def _logs_dir():
    d = settings.LOGS_DIR
    if isinstance(d, str):
        from pathlib import Path as _P
        d = _P(d)
    return d


def _human_size(num):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if num < 1024 or unit == 'GB':
            return ('%d %s' if unit == 'B' else '%.1f %s') % (num, unit)
        num /= 1024.0


def _list_log_files():
    """All regular *.log* files directly inside LOGS_DIR, newest first."""
    directory = _logs_dir()
    files = []
    for entry in os.listdir(directory):
        path = directory / entry
        if entry.startswith('.') or not path.is_file() or '.log' not in entry:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        files.append({'name': entry, 'size': st.st_size, 'size_human': _human_size(st.st_size), 'mtime': st.st_mtime})
    files.sort(key=lambda f: f['mtime'], reverse=True)
    return files


def _resolve_log(name):
    """Resolve a requested log file name to a safe path inside LOGS_DIR."""
    name = os.path.basename(name or '')
    if not name or name.startswith('.') or not name.endswith('.log'):
        raise Http404('Log file not found')
    path = (_logs_dir() / name).resolve()
    if path.parent != _logs_dir().resolve() or not path.is_file():
        raise Http404('Log file not found')
    return path


def _read_tail_lines(path, n):
    """Last n lines of the file (only reads the final megabyte)."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    with open(path, 'rb') as fh:
        if size > TAIL_READ_CAP:
            fh.seek(size - TAIL_READ_CAP)
            fh.readline()  # discard the (possibly partial) first line
        data = fh.read()
    lines = data.decode('utf-8', 'replace').splitlines()
    return lines[-n:]


def _sse(line):
    return 'data: {}\n\n'.format(json.dumps(line))


def _tail_stream(request, path, window):
    """Yield SSE events: history (last ``window`` lines) then live lines.

    Handles file rotation/truncation by re-reading the tail when the file
    shrinks. Emits an SSE comment every ~15s so proxies keep the stream open.
    """
    for line in _read_tail_lines(path, window):
        yield _sse(line)

    try:
        position = path.stat().st_size
    except OSError:
        return
    buffer = b''
    idle = 0
    while True:
        try:
            size = path.stat().st_size
        except OSError:
            # File disappeared (rotation without successor); keep polling.
            time.sleep(POLL_INTERVAL)
            continue

        if size < position:
            # Rotated or truncated: restart tail at the (new) end.
            for line in _read_tail_lines(path, min(window, 50)):
                yield _sse(line)
            position = size
            buffer = b''
        elif size > position:
            with open(path, 'rb') as fh:
                fh.seek(position)
                chunk = fh.read(size - position)
            position = size
            buffer += chunk
            if b'\n' in buffer:
                parts = buffer.split(b'\n')
                buffer = parts.pop()  # keep the incomplete tail line
                for raw in parts:
                    yield _sse(raw.decode('utf-8', 'replace'))
            if len(buffer) > 1_000_000:
                buffer = buffer[-500:]  # guard against huge single "lines"
        else:
            time.sleep(POLL_INTERVAL)
            idle += 1
            if idle % HEARTBEAT_TICKS == 0:
                yield ': heartbeat\n\n'


@staff_member_required
def console(request):
    files = _list_log_files()
    file_names = [f['name'] for f in files]
    selected = request.GET.get('file')
    if not selected or selected not in file_names:
        selected = file_names[0] if file_names else None
    try:
        window = int(request.GET.get('window', DEFAULT_WINDOW))
    except (TypeError, ValueError):
        window = DEFAULT_WINDOW
    window = max(MIN_WINDOW, min(MAX_WINDOW, window))

    context = {
        'files': files,
        'selected': selected,
        'file_names': file_names,
        'window': window,
        'total_size': _human_size(sum(f['size'] for f in files)),
    }
    return render(request, 'log_console/console.html', context)


@staff_member_required
def stream(request):
    path = _resolve_log(request.GET.get('file'))
    try:
        window = int(request.GET.get('window', DEFAULT_WINDOW))
    except (TypeError, ValueError):
        window = DEFAULT_WINDOW
    window = max(MIN_WINDOW, min(MAX_WINDOW, window))
    response = StreamingHttpResponse(
        _tail_stream(request, path, window),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache, no-transform'
    response['X-Accel-Buffering'] = 'no'
    return response


def _iter_file_chunks(path, chunk_size=1 << 16):
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield chunk


@staff_member_required
def download_single(request):
    path = _resolve_log(request.GET.get('file'))
    response = StreamingHttpResponse(
        _iter_file_chunks(path), content_type='text/plain; charset=utf-8'
    )
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(path.name)
    return response


def _zip_chunks(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)
    buf.seek(0)

    def _chunks():
        while True:
            chunk = buf.read(1 << 16)
            if not chunk:
                break
            yield chunk

    return _chunks()


@staff_member_required
@require_http_methods(['GET'])
def download_all(request):
    files = []
    total = 0
    for f in _list_log_files():
        p = _logs_dir() / f['name']
        total += f['size']
        files.append(p)
    if total > MAX_DOWNLOAD_ALL_BYTES:
        return StreamingHttpResponse(
            'Log directory exceeds the {} MB download limit ({} MB found). '
            'Download individual files instead.'.format(
                MAX_DOWNLOAD_ALL_BYTES // (1024 * 1024), total // (1024 * 1024)
            ),
            status=413,
            content_type='text/plain',
        )
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    response = StreamingHttpResponse(
        _zip_chunks(files), content_type='application/zip'
    )
    response['Content-Disposition'] = 'attachment; filename="draw-logs-{}.zip"'.format(stamp)
    return response
