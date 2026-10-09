"""同步参数标题、中文候选值到 gettext 文本和编译目录。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


def main():
    import polib
    from src.tasks.app_option_ui import OPTION_LABELS, option_schema
    from zzz_od.application.app_options_data import APP_OPTIONS
    labels = {**OPTION_LABELS, 'Game Hotkey Config': '游戏战斗键位'}
    for app in APP_OPTIONS:
        for option in app.get('options', []):
            schema = option_schema(app['app_id'], option['key'])
            if schema:
                labels.update({key: value for key, value in schema['option_labels'].items()
                               if isinstance(key, str) and key and key != value})
    path = ROOT / 'i18n/zh_CN/LC_MESSAGES/ok.po'
    catalog = polib.pofile(str(path))
    for key, label in labels.items():
        entry = catalog.find(key)
        if entry is None:
            catalog.append(polib.POEntry(msgid=key, msgstr=label))
        else:
            entry.msgstr = label
    catalog.save(str(path))
    catalog.save_as_mofile(str(path.with_suffix('.mo')))
    print(f'已同步 {len(labels)} 项中文参数与候选值')


if __name__ == '__main__':
    main()
