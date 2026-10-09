# -*- coding: utf-8 -*-
"""计算一条龙源码的导入闭合（只读分析工具）。

给定入口模块集合，递归解析项目内导入，输出分类清单：
- IN_TREE:   one_dragon / zzz_od 内部模块
- MISSING:   被引用但尚未列入移植集的内部模块
- EXTERNAL:  第三方依赖
"""
import ast
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else r"D:\Temp\ref\ZenlessZoneZero-OneDragon\src"
ENTRY_PREFIXES = sys.argv[2:] if len(sys.argv) > 2 else []


def default_entries():
    """默认入口：zzz_od/application 下全部 py 模块（点路径）。"""
    mods = []
    root = os.path.join(SRC, 'zzz_od', 'application')
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith('.py') and f != '__init__.py':
                rel = os.path.relpath(os.path.join(dirpath, f), SRC).replace('\\', '/')
                mods.append(rel[:-3].replace('/', '.'))
    return mods


def module_to_path(mod: str):
    base = os.path.join(SRC, mod.replace('.', os.sep))
    if os.path.exists(base + '.py'):
        return base + '.py'
    if os.path.isdir(base):
        return os.path.join(base, '__init__.py')
    return None


def parse_imports(path: str):
    tree = ast.parse(open(path, encoding='utf-8').read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                rel = os.path.relpath(path, SRC).replace('\\', '/')
                parts = rel.split('/')[:-1]
                pkg = '.'.join(parts)
                if node.module:
                    mods.add(pkg + '.' + node.module if pkg else node.module)
                # from . import x
                for a in node.names:
                    mods.add((pkg + '.' if pkg else '') + a.name)
            elif node.module:
                mods.add(node.module)
                for a in node.names:  # from pkg import submod 可能指向子模块
                    cand = node.module + '.' + a.name
                    if module_to_path(cand):
                        mods.add(cand)
    return mods


visited = set()
queue = default_entries() if not ENTRY_PREFIXES else list(ENTRY_PREFIXES)
external = set()
missing = []

while queue:
    mod = queue.pop()
    if mod in visited:
        continue
    visited.add(mod)
    p = module_to_path(mod)
    if p is None:
        if mod.split('.')[0] in ('one_dragon', 'zzz_od', 'onnxocr'):
            missing.append(mod)
        else:
            external.add(mod.split('.')[0])
        continue
    for m in parse_imports(p):
        if m not in visited:
            queue.append(m)

print('=== IN_TREE (可见) ===')
print(len([m for m in visited if module_to_path(m)]))
print('=== MISSING (被引用但文件缺失) ===')
for m in sorted(set(missing)):
    print(' ', m)
print('=== EXTERNAL (第三方，按顶层包) ===')
for e in sorted(external):
    print(' ', e)
