# -*- coding: utf-8 -*-
"""计算应用层导入闭合，输出相对一条龙 src 的文件清单（含尚未移植的新增集）。"""
import ast
import os

SRC = r"D:\Temp\ref\ZenlessZoneZero-OneDragon\src"
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")


def module_to_path(mod):
    base = os.path.join(SRC, mod.replace('.', os.sep))
    if os.path.exists(base + '.py'):
        return base + '.py'
    if os.path.isdir(base):
        return os.path.join(base, '__init__.py')
    return None


def parse_imports(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                rel = os.path.relpath(path, SRC).replace('\\', '/')
                pkg = '.'.join(rel.split('/')[:-1])
                if node.module:
                    mods.add((pkg + '.' if pkg else '') + node.module)
            elif node.module:
                mods.add(node.module)
                for a in node.names:
                    cand = node.module + '.' + a.name
                    if module_to_path(cand):
                        mods.add(cand)
    return mods


visited = set()
queue = []
root = os.path.join(SRC, 'zzz_od', 'application')
for dirpath, _dirs, files in os.walk(root):
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            rel = os.path.relpath(os.path.join(dirpath, f), SRC).replace('\\', '/')
            queue.append(rel[:-3].replace('/', '.'))

missing = set()
while queue:
    mod = queue.pop()
    if mod in visited:
        continue
    visited.add(mod)
    p = module_to_path(mod)
    if p is None:
        if mod.split('.')[0] in ('one_dragon', 'zzz_od'):
            missing.add(mod)
        continue
    for m in parse_imports(p):
        if m not in visited:
            queue.append(m)

files = sorted(m for m in visited if module_to_path(m))
have = set()
for dp, _dn, fn in os.walk(DST):
    for f in fn:
        if f.endswith('.py'):
            rel = os.path.relpath(os.path.join(dp, f), DST).replace('\\', '/')
            have.add(rel)

print('=== 闭包内文件总数:', len(files), '===')
print('=== MISSING(引用但不存在的内部模块，多为误报/遥测) ===')
for m in sorted(missing):
    print(' ', m)


def to_dst(rel):
    """一条龙相对路径 → ok-zzz 相对路径（包名映射 one_dragon→onedragon）。"""
    if rel.startswith('one_dragon/'):
        return 'onedragon/' + rel[len('one_dragon/'):]
    return rel


print('=== 新增待移植文件 ===')
n = 0
for m in files:
    rel = os.path.relpath(module_to_path(m), SRC).replace('\\', '/')
    if to_dst(rel) not in have:
        n += 1
        print(rel)
print('=== 新增合计:', n, '===')
