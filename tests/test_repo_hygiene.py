"""Source files must not be hidden by .gitignore, or a fresh clone fails to import them."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which('git') is None or not (ROOT / '.git').exists(),
                                reason='needs a git checkout')


def _check_ignore(paths):
    # NUL-separated bytes: text-mode stdin on Windows would turn '\n' into '\r\n'.
    result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=ROOT,
                            input='\0'.join(paths).encode('utf-8'), capture_output=True)
    return [p for p in result.stdout.decode('utf-8').split('\0') if p]


def test_no_source_file_is_ignored():
    sources = [p.relative_to(ROOT).as_posix() for p in (ROOT / 'src').rglob('*.py') if '__pycache__' not in p.parts]
    assert not _check_ignore(sources)


def test_runtime_output_folders_stay_ignored():
    paths = ['debug/live/session.json', 'build/ok-zzz/x.toc', 'dist/ok-zzz/ok-zzz.exe']
    assert _check_ignore(paths) == paths


def test_project_imports_resolve():
    """src/ 内运行时执行的项目包导入（src、onedragon、zzz_od）必须能解析到实际文件。

    ``from one_dragon.base.operation.one_dragon_context import ...`` 这类只出现在
    ``if TYPE_CHECKING:`` 里的上游引用不执行，跳过。
    """
    import ast
    src_root = ROOT / 'src'
    package_roots = {'src', 'onedragon', 'zzz_od'}

    def guarded_by_type_checking(node, parents):
        current = parents.get(node)
        while current is not None:
            test = current.test if isinstance(current, ast.If) else None
            if (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or (
                    isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'):
                return True
            current = parents.get(current)
        return False

    missing = []
    for path in sorted(src_root.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        parents = {child: parent for parent in ast.walk(tree)
                   for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            if guarded_by_type_checking(node, parents):
                continue
            for name in names:
                root_name = name.split('.')[0]
                if root_name not in package_roots:
                    continue
                # src.* 是仓库根下的包；onedragon / zzz_od 在 src/ 下。
                base = ROOT if root_name == 'src' else src_root
                target = base.joinpath(*name.split('.'))
                if target.with_suffix('.py').is_file() or (target / '__init__.py').is_file():
                    continue
                missing.append(f'{path.relative_to(ROOT).as_posix()}: {name}')
    assert not missing, '无法解析的项目内导入：\n' + '\n'.join(missing)


def test_translation_catalogs_load():
    """i18n 下的 .mo 必须是真正的编译目录（英文目录曾误放 .po 文本）。"""
    import gettext
    catalogs = sorted((ROOT / 'i18n').glob('*/LC_MESSAGES/ok.mo'))
    assert catalogs
    for path in catalogs:
        with path.open('rb') as stream:
            gettext.GNUTranslations(stream)


def test_tests_run_isolated_from_the_checkout():
    """测试必须运行在临时运行目录副本上，不读写仓库内的真实配置。"""
    from onedragon.utils import os_utils
    work = Path(os_utils.get_work_dir()).resolve()
    assert work != ROOT and (work / 'config').is_dir()


def test_generated_app_files_are_in_sync():
    """app_tasks.py 与 app_options_data.py 必须与生成器输出一致（gen_app_tasks.py --check）。"""
    result = subprocess.run([sys.executable, str(ROOT / 'tools/gen_app_tasks.py'), '--check'],
                            cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
                            timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_user_lock_excludes_dev_tools():
    """用户锁文件不带开发工具；开发依赖单独在 requirements-dev.txt 声明。"""
    lock = (ROOT / 'requirements.lock.txt').read_text(encoding='utf-8').lower()
    for package in ('pytest==', 'pluggy==', 'iniconfig==', 'pygments==', 'polib=='):
        assert package not in lock, f'{package} 不应出现在用户锁文件中'
    dev = (ROOT / 'requirements-dev.txt').read_text(encoding='utf-8')
    assert 'pytest' in dev and 'polib' in dev


# Packages whose metadata names a dependency the lock leaves out on purpose (installed with --no-deps).
INTENTIONALLY_UNLOCKED = {
    'pyside6': 'pyside6-fluent-widgets needs PySide6 only for QtCore/QtGui/QtWidgets/QtSvg/QtXml, all in '
               'pyside6-essentials; the meta package would add pyside6-addons (~440 MB, never imported)',
    'sympy': 'onnxruntime imports sympy only in its offline symbolic shape-inference tool',
}
USED_EXTRAS = {'ok-script': {'qt', 'ocr'}}


def _locked():
    import re
    text = (ROOT / 'requirements.lock.txt').read_text(encoding='utf-8')
    return {m.group(1).lower().replace('_', '-'): m.group(2)
            for m in re.finditer(r'^([A-Za-z0-9_.-]+)==(\S+)', text, re.M)}


def test_user_lock_is_complete_for_a_no_deps_install():
    """pyappify installs the lock with --no-deps, so every runtime dependency must be locked itself."""
    import importlib.metadata as md
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    locked = _locked()
    installed = {}
    for name, version in locked.items():
        try:
            installed[name] = md.distribution(name)
        except md.PackageNotFoundError:
            pass
    if set(installed) != set(locked):
        pytest.skip('test environment was not installed from the lock: '
                    + ', '.join(sorted(set(locked) - set(installed))))
    missing = []
    for name, dist in installed.items():
        extras = USED_EXTRAS.get(name, set()) | {''}
        for text in dist.requires or []:
            requirement = Requirement(text)
            environments = [{'extra': e, 'sys_platform': 'win32', 'platform_system': 'Windows',
                             'python_version': '3.12'} for e in extras]
            if requirement.marker is not None and not any(requirement.marker.evaluate(env) for env in environments):
                continue
            dep = canonicalize_name(requirement.name)
            if dep not in locked and dep not in INTENTIONALLY_UNLOCKED:
                missing.append(f'{name} -> {text}')
    assert not missing, '锁文件缺少运行依赖：' + '; '.join(missing)


def test_unused_heavy_packages_stay_out_of_the_user_lock():
    locked = _locked()
    for package in ('pyside6', 'pyside6-addons', 'sympy', 'librosa', 'numba', 'llvmlite', 'scikit-learn',
                    'opencv-contrib-python'):
        assert package not in locked, f'{package} 不应进入用户锁文件（见 requirements.txt 说明）'
    assert 'pyside6-essentials' in locked and 'opencv-python' in locked
    assert '--no-deps' in (ROOT / 'pyappify.yml').read_text(encoding='utf-8')
