#!/usr/bin/env python3
# 一键更新看板：抓数(5个脚本) -> 推送到 GitHub Pages 永久链接
# 用法: GH_TOKEN=ghp_xxx python3 update_dashboard.py
#
# 说明:
#  - 永远只推送到 GitHub Pages 永久链接 https://vincentChen-7.github.io/futures-dashboard/
#  - 不再使用 workbuddy_cloudstudio_deploy (CloudStudio 沙箱会被回收，链接会死)
#  - echarts.min.js 已随 publish_github.py 的 FILES 清单一起推送，无需单独处理
import os, sys, subprocess, importlib.util

ROOT = os.path.dirname(os.path.abspath(__file__))
_dd = os.path.join(ROOT, 'data-dashboard')
# 兼容两种布局：本地 data-dashboard/ 子目录 或 GitHub 仓库根目录扁平布局
DD = _dd if os.path.isdir(_dd) else ROOT

SCRIPTS = [
    'scraper.py',                 # data.json       (高盛/摩根 i/rb/hc)
    'jm_scraper.py',              # JM_data.json    (焦煤席位)
    'fetch_iron_seats.py',        # IRON_i/rb/hc_data.json (铁矿/螺纹/热卷席位)
    'sgx_auto_update.py',         # sgx_options.json (SGX期权)
    'sgx_futures_auto_update.py', # sgx_futures.json + history (SGX期货)
]


def run_script(name):
    print('\n>>> 运行抓数脚本:', name)
    r = subprocess.run([sys.executable, name], cwd=DD)
    if r.returncode != 0:
        raise SystemExit(f'[失败] 抓数脚本异常退出: {name} (code {r.returncode})')
    print('<<< 完成:', name)


def publish():
    print('\n>>> 推送到 GitHub Pages 永久链接')
    spec = importlib.util.spec_from_file_location(
        'publish_github', os.path.join(ROOT, 'publish_github.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


def main():
    for s in SCRIPTS:
        run_script(s)
    publish()
    print('\n✅ 看板已更新到永久链接: https://vincentChen-7.github.io/futures-dashboard/')


if __name__ == '__main__':
    main()
