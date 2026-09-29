# -*- coding: utf-8 -*-
"""拉取/更新 ok-zzz 所需的一条龙游戏资产。

优先从本地克隆复制（--src），否则按镜像顺序从 GitHub raw 下载。
资产清单与一条龙仓库保持一致，便于后续同步：
  assets/screen_info/          画面定义 YAML（80 个）
  assets/auto_battle/          战斗 DSL 配置（sample + merged）
  assets/image_analysis_pipelines/  CV 流水线定义
  assets/template/<sub_dir>/   模板图（含 mask）
  assets/dodge_audio/          闪避声音模板
"""
import argparse
import os
import shutil
import sys

# 资产清单与一条龙仓库保持一致（路径即运行时解析路径，勿改）：
#   assets/game_data/screen_info/        画面定义 YAML（80 个）
#   config/auto_battle|auto_battle_operation|auto_battle_state_handler|dodge
#                                        战斗 DSL 配置（loader 按 <工作目录>/config/<sub_dir> 解析）
#   assets/image_analysis_pipelines/     CV 流水线定义
#   assets/template/<sub_dir>/           模板图（含 mask；dodge_audio 为闪避声音模板）
ASSET_SPECS = [
    # (一条龙仓库内路径, 本项目目标目录, 是否整目录复制)
    ('assets/game_data/screen_info', 'assets/game_data/screen_info', True),
    ('config/auto_battle', 'config/auto_battle', True),
    ('config/auto_battle_operation', 'config/auto_battle_operation', True),
    ('config/auto_battle_state_handler', 'config/auto_battle_state_handler', True),
    ('config/dodge', 'config/dodge', True),
    ('assets/image_analysis_pipelines', 'assets/image_analysis_pipelines', True),
    ('assets/template', 'assets/template', False),  # 按 template_subs 复制子目录
]

DEFAULT_SOURCES = [
    'https://raw.githubusercontent.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/main/',
    'https://raw.githubusercontent.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/cnb/',
]

# 战斗引擎本期需要的模板子目录（--all 复制全部）
BATTLE_TEMPLATE_SUBS = ['battle', 'agent_state', 'target_state', 'dodge_audio']


def copy_dir(src_dir: str, dst_dir: str, include_ext=('.yml', '.yaml', '.png', '.wav', '.json', '.csv')):
    n = 0
    for root, _dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        target_root = os.path.join(dst_dir, rel) if rel != '.' else dst_dir
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            if include_ext and not f.lower().endswith(include_ext):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))
            n += 1
    return n


def download_file(url: str, dst: str, timeout: int = 30) -> bool:
    import urllib.request
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, open(dst, 'wb') as fp:
            shutil.copyfileobj(resp, fp)
        return True
    except Exception as e:
        print(f'  下载失败 {url}: {e}')
        return False


def list_remote_dir(github_api: str):
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(github_api, timeout=30) as resp:
            return [item['name'] for item in json.load(resp)]
    except Exception as e:
        print(f'  列目录失败 {github_api}: {e}')
        return []


def fetch_from_github(spec_src: str, dst_dir: str, template_subs=None):
    """按目录遍历从 raw 源下载（速度慢，仅作无本地克隆时的兜底）。"""
    import urllib.request
    api = 'https://api.github.com/repos/OneDragon-Anything/ZenlessZoneZero-OneDragon/contents/'
    n = 0
    stack = [spec_src]
    while stack:
        cur = stack.pop()
        names = list_remote_dir(api + cur)
        for name in names:
            remote = f'{cur}/{name}'
            if template_subs and cur == spec_src and name not in template_subs:
                continue
            # 粗略判断目录：无扩展名且非压缩包
            if not os.path.splitext(name)[1]:
                stack.append(remote)
                continue
            dst = os.path.join(dst_dir, os.path.relpath(remote, spec_src))
            for base in DEFAULT_SOURCES:
                if download_file(base + remote, dst):
                    n += 1
                    break
    return n


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--src', default=None, help='一条龙本地克隆路径（推荐，秒级完成）')
    parser.add_argument('--all', action='store_true', help='复制全部模板子目录（默认仅战斗相关）')
    parser.add_argument('--template-subs', nargs='*', default=BATTLE_TEMPLATE_SUBS)
    args = parser.parse_args()

    total = 0
    if args.src and os.path.isdir(args.src):
        for src_rel, dst_rel, whole in ASSET_SPECS:
            src_dir = os.path.join(args.src, src_rel.replace('/', os.sep))
            if not os.path.isdir(src_dir):
                print(f'[缺失] {src_dir}')
                continue
            if whole:
                if os.path.exists(dst_rel):
                    shutil.rmtree(dst_rel)
                n = copy_dir(src_dir, dst_rel)
            else:
                n = 0
                for sub in args.template_subs:
                    sub_dir = os.path.join(src_dir, sub)
                    if os.path.isdir(sub_dir):
                        n += copy_dir(sub_dir, os.path.join(dst_rel, sub))
            print(f'{dst_rel}: {n} 个文件')
            total += n
    else:
        print('未提供本地克隆，改用 GitHub raw 下载（较慢）...')
        for src_rel, dst_rel, whole in ASSET_SPECS:
            subs = None if whole else args.template_subs
            n = fetch_from_github(src_rel, dst_rel, subs)
            print(f'{dst_rel}: {n} 个文件')
            total += n

    print(f'完成，共 {total} 个资产文件')


if __name__ == '__main__':
    main()
