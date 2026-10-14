#!/usr/bin/env python3
# 将本地最新数据 + 站点 + 抓取脚本 + 工作流 推送到 GitHub Pages（永久链接）。
# 用法: GH_TOKEN=xxx python3 publish_github.py
# 说明: 本机 git 缺 https 助手，故走 GitHub Git Data API（python urllib）推送。
import os, base64, json, urllib.request, urllib.error, ssl, datetime

TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
if not TOKEN:
    raise SystemExit('缺少 GH_TOKEN 环境变量（GitHub Personal Access Token，需 repo 权限；GitHub Actions 内用内置 GITHUB_TOKEN）')
OWNER = 'VincentChen-7'
REPO = 'futures-dashboard'
BASE = f'https://api.github.com/repos/{OWNER}/{REPO}/git'

ROOT = os.path.dirname(os.path.abspath(__file__))
_dd = os.path.join(ROOT, 'data-dashboard')
# 兼容两种布局：本地 data-dashboard/ 子目录；GitHub 仓库根目录扁平布局
SRC = _dd if os.path.isdir(_dd) else ROOT

# 仓库完整文件清单（扁平布局）。一次性全量推送，避免在 Runner 上运行时误删脚本/工作流。
FILES = [
    'index.html', 'echarts.min.js',
    'data.json', 'JM_data.json',
    'IRON_i_data.json', 'IRON_rb_data.json', 'IRON_hc_data.json',
    'sgx_options.json', 'sgx_futures.json',
    'sgx_options_history.json', 'sgx_futures_history.json',
    'update_dashboard.py', 'publish_github.py',
    'scraper.py', 'jm_scraper.py', 'fetch_iron_seats.py',
    'sgx_auto_update.py', 'sgx_futures_auto_update.py', 'sgx_options_processor.py',
    'requirements.txt', '.github/workflows/update.yml',
]
WF = '.github/workflows/update.yml'
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def api(method, url, data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header('Authorization', f'Bearer {TOKEN}')
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', 'workbuddy')
    if data is not None:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(data).encode('utf-8')
    try:
        with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise SystemExit(f'API {method} {url} 失败 {e.code}: {e.read().decode()[:400]}')


def local_path(fn):
    p = os.path.join(SRC, fn)
    if os.path.isfile(p):
        return p
    p2 = os.path.join(ROOT, fn)
    if os.path.isfile(p2):
        return p2
    raise SystemExit(f'缺少文件: {fn} (SRC={SRC})')


def build_entries():
    entries = []
    for fn in FILES:
        p = local_path(fn)
        with open(p, 'rb') as f:
            c = f.read()
        b64 = base64.b64encode(c).decode('ascii')
        blob = api('POST', f'{BASE}/blobs', {'content': b64, 'encoding': 'base64'})
        entries.append({'path': fn, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        print('  blob', fn, len(c), 'bytes')
    return entries


def push(entries, base_sha, msg):
    tree = api('POST', f'{BASE}/trees', {'tree': entries})
    commit = api('POST', f'{BASE}/commits', {'message': msg, 'tree': tree['sha'], 'parents': [base_sha]})
    api('PATCH', f'{BASE}/refs/heads/main', {'sha': commit['sha']})
    return commit['sha']


def main():
    ref = api('GET', f'{BASE}/refs/heads/main')
    base_sha = ref['object']['sha']
    print('base commit:', base_sha)
    entries = build_entries()
    # 空 .nojekyll，禁用 Jekyll
    nb = api('POST', f'{BASE}/blobs', {'content': '', 'encoding': 'base64'})
    entries.append({'path': '.nojekyll', 'mode': '100644', 'type': 'blob', 'sha': nb['sha']})

    msg = f'Update dashboard {datetime.date.today()}'
    if any(e['path'] == WF for e in entries):
        no_wf = [e for e in entries if e['path'] != WF]
        try:
            push(entries, base_sha, msg)
            print('已推送（含工作流）')
        except SystemExit as e:
            em = str(e).lower()
            # GitHub 对缺少 workflow 权限的 PAT 提交工作流文件会返回 404/403
            if ('403' in str(e) or '404' in str(e) or 'workflow' in em):
                print('⚠ PAT 缺少 workflow 权限（GitHub 返回 404/403），先推送数据/脚本；工作流文件需单独处理。')
                push(no_wf, base_sha, msg + ' (no workflow)')
            else:
                raise
    else:
        push(entries, base_sha, msg)
    print('已推送到 https://github.com/%s/%s  ->  https://%s.github.io/%s/' % (OWNER, REPO, OWNER.lower(), REPO))


if __name__ == '__main__':
    main()
