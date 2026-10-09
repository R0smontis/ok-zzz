"""Compare skill code and assets against the local port reference snapshot."""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = Path(r'D:\Temp\ref\ZenlessZoneZero-OneDragon')


def methods(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig').replace('one_dragon.', 'onedragon.'))
    result = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef):
                # The new input guard is an explicit integration difference.
                fn.decorator_list = [d for d in fn.decorator_list
                                     if not isinstance(d, ast.Name) or d.id != 'guarded_battle_action']
                result[cls.name + '.' + fn.name] = ast.dump(fn, include_attributes=False)
    return result


def run():
    report = {'reference': str(REFERENCE),
              'reference_commit': subprocess.check_output(
                  ['git', '-c', 'safe.directory=' + REFERENCE.as_posix(),
                   '-C', str(REFERENCE), 'rev-parse', 'HEAD'], text=True).strip(),
              'code': [], 'resources': {}, 'validation': 'offline; no live game inputs'}
    names = ['zzz_od/auto_battle/auto_battle_context.py',
             'zzz_od/auto_battle/auto_battle_agent_context.py',
             'zzz_od/controller/zzz_pc_controller.py', 'zzz_od/config/game_config.py']
    names += [str(p.relative_to(REFERENCE / 'src')).replace('\\', '/')
              for p in sorted((REFERENCE / 'src/zzz_od/auto_battle/atomic_op').glob('*.py'))]
    for name in names:
        original = methods(REFERENCE / 'src' / name)
        path = ROOT / 'src' / name
        ported = methods(path) if path.is_file() else {}
        report['code'].append({'file': name, 'method_count': len(original),
                               'unchanged_methods': sum(original[k] == ported.get(k) for k in original),
                               'changed_methods': [k for k in original if k in ported and original[k] != ported[k]],
                               'missing_methods': sorted(original.keys() - ported.keys())})
    categories = {'skill_templates': ['config/auto_battle', 'config/auto_battle_operation',
                                     'config/auto_battle_state_handler'],
                  'battle_images': ['assets/template/battle'],
                  'chain_pipeline': ['assets/image_analysis_pipelines/战斗-连携条.yml']}
    for category, paths in categories.items():
        files = []
        for name in paths:
            source = REFERENCE / name
            files += list(source.rglob('*')) if source.is_dir() else [source]
        files = [p for p in files if p.is_file() and
                 (p.suffix == '.png' if category == 'battle_images' else p.suffix in ('.yml', '.yaml'))]
        missing, different = [], []
        for source in files:
            relative = source.relative_to(REFERENCE)
            target = ROOT / relative
            if not target.is_file():
                missing.append(relative.as_posix())
            elif hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
                different.append(relative.as_posix())
        report['resources'][category] = {'reference_files': len(files), 'missing': missing, 'different': different}
    target = ROOT / 'build/battle-port-audit.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(target), 'reference_commit': report['reference_commit'],
                      'missing_methods': sum(len(item['missing_methods']) for item in report['code']),
                      'resources': report['resources']}, ensure_ascii=False))


if __name__ == '__main__':
    run()
