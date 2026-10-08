# -*- coding: utf-8 -*-
"""应用选项元数据提取器（离线运行，不需要游戏与 ok-script 运行时）。

扫描一条龙移植代码中的应用工厂/配置类：
1. 读取 *_const.py 的应用元数据（APP_ID/APP_NAME/PRIORITY/DEFAULT_GROUP）
2. 从工厂源码中解析 create_config 返回的配置类
3. 实例化配置类并内省全部 @property 选项（名称/默认值/类型/枚举可选值）

输出 options 数据供任务类生成器（gen_app_tasks.py）使用。
"""
import dataclasses
import enum
import inspect
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

OPT_OUT_PROPS = {
    'plan_id', 'last_daily_reset_dt', 'skip_plan',  # charge_plan 运行态字段
}
SKIP_VALUES = (type(None),)


def find_config_class(factory_module_name: str):
    """从工厂模块源码解析 create_config 返回的配置类 (module_name, class_name)。"""
    import importlib
    mod = importlib.import_module(factory_module_name)
    src = inspect.getsource(mod)
    m = re.search(r'def create_config\(.*?return\s+(\w+)\(', src, re.S)
    if m is None:
        return None
    cls_name = m.group(1)
    cls = getattr(mod, cls_name, None)
    if cls is not None:
        return cls
    # 类在别的模块：全包搜索
    pkg = factory_module_name.rsplit('.', 1)[0]
    pkg_mod = importlib.import_module(pkg)
    import pkgutil
    for m2 in pkgutil.walk_packages(pkg_mod.__path__, prefix=pkg + '.'):
        try:
            sub = importlib.import_module(m2.name)
        except Exception:
            continue
        if hasattr(sub, cls_name):
            return getattr(sub, cls_name)
    return None


def instantiate_config(cls):
    """按常见构造签名尝试实例化配置类。"""
    attempts = [
        dict(instance_idx=0, group_id='one_dragon'),
        dict(instance_idx=0),
        dict(),
    ]
    for kwargs in attempts:
        try:
            sig = inspect.signature(cls.__init__)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                pass  # 有 **kwargs 时多余键可忽略
            filtered = {k: v for k, v in kwargs.items()
                        if k in sig.parameters or any(
                            p.kind == inspect.Parameter.VAR_KEYWORD
                            for p in sig.parameters.values())}
            return cls(**filtered)
        except Exception:
            continue
    return None


def find_enum_choices(config_module, default_value):
    """在配置类所在模块中查找包含 default_value 的枚举，返回可选值列表。"""
    if not isinstance(default_value, str):
        return None
    for name, obj in vars(config_module).items():
        if (isinstance(obj, type) and issubclass(obj, enum.Enum)
                and obj is not enum.Enum):
            try:
                values = [m.value.value if hasattr(m.value, 'value') else m.value
                          for m in obj]
            except Exception:
                continue
            if default_value in values:
                return [v for v in values if isinstance(v, str)]
            # StrEnum 配置经常存成员名（如 HOUR_20），而显示值是中文。
            names = [member.name for member in obj]
            if default_value in names:
                return names
    return None


def extract_options(config_cls):
    """内省配置类属性 → 选项字典列表。"""
    config = instantiate_config(config_cls)
    if config is None:
        return None, '无法实例化'
    config_module = inspect.getmodule(config_cls)
    options = []
    for name, member in inspect.getmembers(type(config)):
        if name.startswith('_') or name in OPT_OUT_PROPS:
            continue
        if not isinstance(member, property) or member.fget is None:
            continue
        if member.fset is None:
            continue  # 只读属性不是选项
        try:
            value = getattr(config, name)
        except Exception:
            continue  # 需要数据文件/服务的属性跳过
        if value is None or isinstance(value, SKIP_VALUES):
            continue
        # 兼容早期选项桥把 JSON 文本直接存入 list/dict 配置的情况。
        annotation = str(member.fget.__annotations__.get('return', ''))
        if isinstance(value, str) and annotation.startswith(('list[', 'dict[')):
            try:
                value = json.loads(value.replace('\\n', '\n'))
            except ValueError:
                continue
        if isinstance(value, bool):
            options.append({'key': name, 'type': 'bool', 'default': value})
        elif isinstance(value, int):
            options.append({'key': name, 'type': 'int', 'default': value})
        elif isinstance(value, float):
            options.append({'key': name, 'type': 'float', 'default': value})
        elif isinstance(value, (list, dict)):
            # dataclass 计划项等复杂结构 → JSON 文本域
            options.append({'key': name, 'type': 'json',
                            'default': json.dumps(value, ensure_ascii=False, indent=1)})
        elif isinstance(value, str):
            choices = find_enum_choices(config_module, value)
            if choices:
                options.append({'key': name, 'type': 'enum',
                                'default': value, 'choices': choices})
            elif '\n' in value or len(value) > 60:
                options.append({'key': name, 'type': 'text', 'default': value})
            else:
                options.append({'key': name, 'type': 'str', 'default': value})
        elif dataclasses.is_dataclass(value):
            options.append({'key': name, 'type': 'json',
                            'default': json.dumps(dataclasses.asdict(value),
                                                  ensure_ascii=False, indent=1)})
    return options, None


MANUAL_OPTIONS = {
    'auto_battle': [
        {'key': 'auto_battle_config', 'type': 'enum', 'default': '全配队通用'},
        {'key': 'screenshot_interval', 'type': 'float', 'default': 0.02},
        {'key': 'background_mode', 'type': 'bool', 'default': False},
        {'key': 'use_merged_file', 'type': 'bool', 'default': True},
        {'key': 'auto_ultimate_enabled', 'type': 'bool', 'default': False},
    ],
    'dodge_assistant': [
        {'key': 'dodge_assistant_config', 'type': 'enum', 'default': '闪避'},
        {'key': 'screenshot_interval', 'type': 'float', 'default': 0.02},
        {'key': 'background_mode', 'type': 'bool', 'default': False},
    ],
}
# 枚举可选值：战斗配置= config/auto_battle 下模板名（运行时扫描，这里给常用项）
MANUAL_CHOICES = {
    'auto_battle_config': ['全配队通用'],
    'dodge_assistant_config': ['闪避', '智能格挡', '本-格挡',
                               '闪A切下一个', '闪A切强攻', '切换角色-下一个'],
}


def collect_apps():
    """扫描全部应用：元数据 + 工厂 + 配置选项。"""
    import importlib, pkgutil
    apps = []
    const_mods = []
    base = os.path.join(ROOT, 'src', 'zzz_od', 'application')
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith('_const.py'):
                rel = os.path.relpath(os.path.join(dirpath, f[:-3]),
                                      os.path.join(ROOT, 'src')).replace('\\', '/')
                const_mods.append(rel.replace('/', '.'))
    for const_name in sorted(const_mods):
        try:
            const = importlib.import_module(const_name)
            app_id = getattr(const, 'APP_ID', None)
            if app_id is None:
                continue  # 非应用级 const（操作/交互目标等）
            pkg_name = const_name.rsplit('.', 1)[0]
            factory_name = None
            pkg_mod = importlib.import_module(pkg_name)
            for fname in os.listdir(os.path.dirname(pkg_mod.__file__)):
                if fname.endswith('_factory.py'):
                    factory_name = f'{pkg_name}.{fname[:-3]}'
                    break
            config_cls = None
            if factory_name:
                config_cls = find_config_class(factory_name)
            options, err = (None, '无配置')
            if config_cls is not None:
                options, err = extract_options(config_cls)
            if app_id in MANUAL_OPTIONS:
                opts = []
                for o in MANUAL_OPTIONS[app_id]:
                    o = dict(o)
                    if o['type'] == 'enum' and o['key'] in MANUAL_CHOICES:
                        o['choices'] = MANUAL_CHOICES[o['key']]
                    opts.append(o)
                options, err = opts, None
            apps.append({
                'app_id': app_id,
                'app_name': const.APP_NAME,
                'default_group': const.DEFAULT_GROUP,
                'priority': getattr(const, 'PRIORITY', None),
                'const_module': const_name,
                'factory_module': factory_name,
                'config_class': config_cls.__name__ if config_cls else None,
                'options': options or [],
                'options_error': err,
            })
        except Exception as e:
            apps.append({'app_id': const_name, 'error': str(e)[:100]})
    return apps


ICONS = {
    'auto_battle': '⚔️', 'dodge_assistant': '🛡️', 'charge_plan': '⚡',
    'coffee': '☕', 'random_play': '🎬', 'notorious_hunt': '🐲',
    'hollow_zero': '🕳️', 'withered_domain': '🕳️', 'lost_void': '🌌',
    'world_patrol': '🌍', 'suibian_temple': '🏪', 'intel_board': '📋',
    'email': '📧', 'daily_signin': '📅', 'scratch_card': '🎟️',
    'trigrams_collection': '🔮', 'hou_hou_bakery': '🍞', 'city_fund': '🏙️',
    'ridu_weekly': '📈', 'engagement_reward': '🎁', 'redemption_code': '🎫',
    'drive_disc_dismantle': '💎', 'life_on_line': '🎮',
    'commission_assistant': '🤝', 'notify': '📢',
    'one_dragon': '🐉',
}

UI_ONLY_KEYS = ('结束后', '关机延迟秒')


def emit_tasks(apps):
    """生成 src/tasks/app_tasks.py：每个应用一个 ok-script 任务类。"""
    lines = [
        '# -*- coding: utf-8 -*-',
        '# 由 tools/gen_app_tasks.py 生成：一条龙各应用的 ok-script 运行任务。',
        '# 每个任务的细则选项与一条龙原版配置键一致，运行前写回应用配置。',
        '# 重新生成: .venv/Scripts/python tools/gen_app_tasks.py',
        '',
        'import json',
        '',
        'from ok import BaseTask',
        '',
        'from src.tasks.app_task_base import AppTaskBase',
        '',
        '',
    ]
    n = 0
    for app in apps:
        if 'error' in app or app.get('app_id') in ('one_dragon',):
            continue
        app_id = app['app_id']
        cls_name = 'App_' + ''.join(
            w.capitalize() for w in app_id.replace('-', '_').split('_'))
        icon = ICONS.get(app_id, '▶️')
        lines.append(f'class {cls_name}(AppTaskBase):')
        lines.append(f"    app_id = {app_id!r}")
        lines.append('')
        lines.append('    def __init__(self, *args, **kwargs):')
        lines.append('        super().__init__(*args, **kwargs)')
        lines.append(f"        self.name = {f'{icon} {app["app_name"]}'!r}")
        lines.append(f"        self.description = {f'运行一条龙应用：{app["app_name"]}'!r}")
        if app.get('options'):
            lines.append('        self.default_config.update({')
            for o in app['options']:
                lines.append(f"            {o['key']!r}: {o['default']!r},")
            lines.append("            '结束后': '无',")
            lines.append("            '关机延迟秒': 60,")
            lines.append('        })')
            type_lines = []
            for o in app['options']:
                if o['type'] == 'enum':
                    choices = o.get('choices') or []
                    type_lines.append(
                        f"            {o['key']!r}: {{'type': 'drop_down', "
                        f"'options': {choices!r}}},")
                elif o['type'] in ('json', 'text'):
                    type_lines.append(f"            {o['key']!r}: {{'type': 'text_edit'}},")
            if type_lines:
                lines.append('        self.config_type.update({')
                lines.extend(type_lines)
                lines.append('        })')
            lines.append('        self._option_keys = ['
                         + ', '.join(repr(o['key']) for o in app['options']) + ']')
        else:
            lines.append("        self.default_config.update({'结束后': '无', '关机延迟秒': 60})")
            lines.append("        self._option_keys = []")
        lines.append('')
        lines.append('')
        n += 1
    out = os.path.join(ROOT, 'src', 'tasks', 'app_tasks.py')
    with open(out, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('\n'.join(lines))
    return n


if __name__ == '__main__':
    import textwrap
    apps = collect_apps()
    out = os.path.join(ROOT, 'src', 'zzz_od', 'application', 'app_options_data.py')
    payload = json.dumps(apps, ensure_ascii=False, indent=1)
    with open(out, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('# -*- coding: utf-8 -*-\n')
        fp.write('# 由 tools/gen_app_tasks.py 生成：各应用的细则选项元数据。\n')
        fp.write('# 重新生成: .venv/Scripts/python tools/gen_app_tasks.py\n\n')
        fp.write('import json\n\n')
        fp.write('APP_OPTIONS = json.loads(\n')
        fp.write(textwrap.indent(repr(payload) + '\n', ' ' * 4))
        fp.write(')\n')
    n_tasks = emit_tasks(apps)
    ok = [a for a in apps if a.get('options')]
    print(f'共 {len(apps)} 个应用，{len(ok)} 个提取到选项，生成 {n_tasks} 个任务类')
    for a in apps:
        n = len(a.get('options') or [])
        print(f"  {a['app_id']:<28} {a.get('app_name',''):<10} 选项数={n}"
              + (f"  [{a['options_error']}]" if a.get('options_error') and n == 0 else ''))
