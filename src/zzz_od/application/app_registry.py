# -*- coding: utf-8 -*-
"""应用发现与注册（ok-zzz 自写，替代原版 factory_manager 的目录扫描）。

扫描 zzz_od/application 下全部 *_factory.py，按包路径导入，
实例化（factory(ctx)）后注册进 run_context。注册失败的模块
记录日志并跳过，不影响其余应用。
"""
import importlib
import pkgutil

from onedragon.utils.log_utils import log

APP_PACKAGE = 'zzz_od.application'


def discover_factories(ctx) -> list:
    """返回成功注册的工厂列表。"""
    registered = []
    mod = importlib.import_module(APP_PACKAGE)
    factory_modules = []
    for m in pkgutil.walk_packages(mod.__path__, prefix=APP_PACKAGE + '.'):
        if m.name.endswith('_factory'):
            factory_modules.append(m.name)
    factory_modules.sort()

    for name in factory_modules:
        try:
            module = importlib.import_module(name)
            base_cls = getattr(
                importlib.import_module(
                    'onedragon.base.operation.application.application_factory'),
                'ApplicationFactory', None)
            factory_cls = None
            for attr in vars(module).values():
                if not isinstance(attr, type) or attr is base_cls:
                    continue
                if base_cls is None or not issubclass(attr, base_cls):
                    continue
                if attr.__module__ != module.__name__:
                    continue  # 只认本模块定义的工厂
                if factory_cls is None or attr.__name__.endswith('Factory'):
                    factory_cls = attr
            if factory_cls is None:
                continue
            factory = factory_cls(ctx)
            ctx.run_context.registry_application(factory)
            registered.append(factory)
        except Exception as e:
            log.warning(f'应用工厂注册失败 {name}: {e}')
    log.info(f'应用注册完成，共 {len(registered)} 个')
    return registered
