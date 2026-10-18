"""Structured daily ordering and charge-plan forms on the existing task cards."""
import copy
import json
from pathlib import Path
import uuid

from PySide6.QtCore import Qt, QMimeData, Signal, QTimer
from PySide6.QtGui import QDrag, QPainter, QPen, QPalette, QColor
from PySide6.QtWidgets import (QDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView, QScrollArea,
    QAbstractItemView, QLayout, QSizePolicy)
from qfluentwidgets import (CheckBox, ComboBox, FluentIcon, PushButton, SpinBox,
    PrimaryPushButton, TableWidget, ScrollArea, isDarkTheme, qconfig)
from ok import og
from ok.ui.qt.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget


def _form_palette(widget):
    palette = widget.palette()
    background = QColor('#303030' if isDarkTheme() else '#fafafa')
    text = QColor('#f5f5f5' if isDarkTheme() else '#202020')
    for role in (QPalette.Window, QPalette.Base, QPalette.Button):
        palette.setColor(role, background)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(role, text)
    widget.setPalette(palette)


NOTORIOUS_HUNT = '恶名狩猎'


def new_notorious_hunt_plan(compendium):
    """恶名狩猎计划固定在训练页，按狩猎目标区分，不选择具体副本。"""
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    targets = compendium.get_notorious_hunt_plan_mission_type_list(NOTORIOUS_HUNT)
    return ChargePlanItem(tab_name='训练', category_name=NOTORIOUS_HUNT,
                          mission_type_name=targets[0].value if targets else '', mission_name=None).to_dict()


def parse_charge_plans(value, *, single=False, category=None):
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem, CardNumEnum
    from dataclasses import fields
    data = json.loads(value) if isinstance(value, str) else copy.deepcopy(value)
    if not isinstance(data, dict if single else list):
        raise ValueError('双倍奖励计划应为一项计划，普通刷本计划应为计划列表')
    rows = [data] if single else data
    allowed = {field.name for field in fields(ChargePlanItem) if field.name != 'skipped'}
    result = []
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row)-allowed-{'skipped', 'double_reward_enabled'}:
            raise ValueError(f'计划 {number} 含未知字段或格式错误')
        if not isinstance(row.get('double_reward_enabled', True), bool):
            raise ValueError(f'计划 {number} 的双倍开关格式错误')
        item = ChargePlanItem.from_dict({key: val for key, val in row.items() if key != 'skipped'})
        if category is not None and item.category_name != category:
            raise ValueError(f'计划 {number} 的副本类别应为{category}')
        for key in ('category_name', 'mission_type_name', 'mission_name', 'level', 'auto_battle_config'):
            val = getattr(item, key)
            if val is not None and not isinstance(val, str):
                raise ValueError(f'计划 {number} 的文本字段格式错误')
        if not item.category_name or not item.auto_battle_config:
            raise ValueError(f'计划 {number} 的副本类别和战斗模板不能为空')
        if item.supports_double_reward and item.plan_times == 0:
            raise ValueError(f'计划 {number} 的双倍次数和单倍次数不能都为 0')
        for key, low, high in (('plan_times', 1, 99999), ('run_times', 0, 99999),
                ('predefined_team_idx', -1, 19), ('notorious_hunt_buff_num', 1, 3),
                ('double_times', 0, 99999), ('single_times', 0, 99999)):
            val = getattr(item, key)
            if isinstance(val, bool) or not isinstance(val, int) or not low <= val <= high:
                raise ValueError(f'计划 {number} 的 {key} 超出允许范围')
        if item.card_num not in {member.value.value for member in CardNumEnum}:
            raise ValueError(f'计划 {number} 的卡片数量应为默认数量或1至5')
        result.append(item.to_dict())
    ids = [row['plan_id'] for row in result]
    if len(set(ids)) != len(ids):
        raise ValueError('不同刷本计划不能使用相同计划编号')
    return result[0] if single else result


class ChargePlanWidget(ConfigLabelAndWidget):
    fields = [('category_name', '副本类别'), ('mission_type_name', '副本类型'),
        ('mission_name', '副本名称'), ('level', '副本等级'),
        ('auto_battle_config', '战斗模板'), ('card_num', '卡片数量'),
        ('plan_times', '计划次数'), ('double_times', '双倍次数'), ('single_times', '单倍次数'),
        ('predefined_team_idx', '预备编队'),
        ('notorious_hunt_buff_num', '狩猎增益编号')]
    hunt_fields = [('mission_type_name', '狩猎目标'), ('level', '副本等级'),
        ('auto_battle_config', '战斗模板'), ('plan_times', '计划次数'),
        ('predefined_team_idx', '预备编队'), ('notorious_hunt_buff_num', '狩猎增益编号')]

    def __init__(self, description, config, key, schema):
        super().__init__(description, config, key)
        self.single = bool(schema.get('single'))
        self.hunt = schema.get('mode') == 'notorious_hunt'
        if self.hunt:
            self.fields = self.hunt_fields
        self.add_text = '添加狩猎计划' if self.hunt else '添加刷本计划'
        self.layout.setDirection(QHBoxLayout.TopToBottom)
        self.layout.takeAt(1)  # Remove the horizontal row's flexible spacer.
        self.layout.setSpacing(12)
        from zzz_od.game_data.compendium import CompendiumService
        self.compendium = CompendiumService()
        self.compendium._load_all_compendium()
        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.body = QWidget(self)
        self.body.setObjectName('chargePlanBody')
        self.rows_layout = QVBoxLayout(self.body)
        self.rows_layout.setContentsMargins(0, 8, 0, 8)
        self.rows_layout.setSpacing(12)
        self.rows_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.scroll.setWidget(self.body)
        self._refresh_theme()
        qconfig.themeChangedFinished.connect(self._refresh_theme)
        self.add_widget(self.scroll, stretch=0)
        self.add_button = PushButton(FluentIcon.ADD, self.add_text, self)
        self.add_widget(self.add_button, stretch=0)
        self.add_button.setVisible(not self.single)
        self.add_button.clicked.connect(self.add_plan)
        self.error_label = QLabel('', self)
        self.error_label.setWordWrap(True)
        self.add_widget(self.error_label, stretch=0)
        self.update_value()

    def _refresh_theme(self):
        _form_palette(self.scroll)
        _form_palette(self.body)
        text = '#f5f5f5' if isDarkTheme() else '#202020'
        background = '#303030' if isDarkTheme() else '#fafafa'
        self.body.setStyleSheet(
            f'QWidget#chargePlanBody {{ background: {background}; }} '
            f'QLabel {{ color: {text}; background: transparent; }} '
            f'QGroupBox {{ color: {text}; background: {background}; }}')

    def update_value(self):
        try:
            value = self.config.get(self.key)
            if value in ('', None):
                value = '{}' if self.single else '[]'
            parsed = parse_charge_plans(value, single=self.single,
                                        category=NOTORIOUS_HUNT if self.hunt else None)
            self.rows = [parsed] if self.single else parsed
            self.error_label.clear()
        except (ValueError, TypeError) as exc:  # JSONDecodeError 是 ValueError 的子类
            self.rows = []
            self.error_label.setText(f'原配置需要修正：{exc}。点击添加或重建计划后重新填写。')
        self.add_button.setVisible(not self.single or not self.rows)
        self.add_button.setText('重建此计划' if self.single else self.add_text)
        self._render()

    def _save(self):
        value = json.dumps(self.rows[0] if self.single else self.rows, ensure_ascii=False)
        try:
            parse_charge_plans(value, single=self.single,
                               category=NOTORIOUS_HUNT if self.hunt else None)
        except (ValueError, TypeError) as exc:
            self.error_label.setText(str(exc))
            return
        self.error_label.clear()
        self.update_config(value)

    def add_plan(self):
        from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
        self.rows.append(new_notorious_hunt_plan(self.compendium) if self.hunt else ChargePlanItem().to_dict())
        self._save()
        self._render()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def move_plan(self, index, delta):
        other = index+delta
        if 0 <= other < len(self.rows):
            self.rows[index], self.rows[other] = self.rows[other], self.rows[index]
            self._save()
            self._render()

    def remove_plan(self, index):
        self.rows.pop(index)
        self._save()
        self._render()

    def _changed(self, index, key, value):
        self.rows[index][key] = value or None if key == 'mission_name' else value
        row = self.rows[index]
        if key in ('double_times', 'single_times'):
            row['plan_times'] = row['double_times'] + row['single_times']
        elif key == 'plan_times':
            row['single_times'] = value
        self._save()

    @staticmethod
    def _set_choices(control, choices, current, *, preserve=True):
        choices = list(choices)
        if preserve and current not in [value for label, value in choices]:
            choices.append((f'已有配置：{current}', current))
        control.blockSignals(True)
        control.clear()
        for label, value in choices:
            control.addItem(label, userData=value)
        control.setCurrentIndex(control.findData(current))
        control.setEnabled(len(choices) > 1)
        control.blockSignals(False)

    def _mission_choices(self, row, key):
        if key == 'category_name':
            items = self.compendium.get_charge_plan_category_list()
            if self.single:
                items = [item for item in items if item.value == '实战模拟室']
        elif key == 'mission_type_name':
            if self.hunt:
                items = self.compendium.get_notorious_hunt_plan_mission_type_list(NOTORIOUS_HUNT)
            else:
                items = self.compendium.get_charge_plan_mission_type_list(row['category_name'])
        else:
            items = self.compendium.get_charge_plan_mission_list(row['category_name'], row['mission_type_name'])
        return [(item.label, item.value) for item in items] or [('无需选择', None if key == 'mission_name' else '')]

    def _choices(self, row, key):
        from zzz_od.application.charge_plan.charge_plan_config import CardNumEnum
        if key in ('category_name', 'mission_type_name', 'mission_name'):
            return self._mission_choices(row, key)
        if key == 'card_num':
            return [(item.value.label, item.value.value) for item in CardNumEnum]
        if key == 'predefined_team_idx':
            return [('沿用当前队伍', -1), *[(f'预备编队 {i+1}', i) for i in range(20)]]
        if key == 'auto_battle_config':
            from src.tasks.auto_combat_task import list_battle_templates
            return [(name, name) for name in list_battle_templates('auto_battle')]
        if key == 'level':
            # Only deep pursuit exposes a selectable level in the current runner.
            if row['category_name'] == '恶名狩猎':
                from zzz_od.application.notorious_hunt.notorious_hunt_config import NotoriousHuntLevelEnum
                return [(item.value.label, item.value.value) for item in NotoriousHuntLevelEnum]
            return [('默认等级', '默认等级')]
        return []

    def _choice_changed(self, index, key):
        control = self.editors[index][key]
        value = control.currentData()
        row = self.rows[index]
        row[key] = value
        if key == 'category_name':
            from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
            # 支持双倍的类别显示双倍/单倍次数，其余类别只显示计划次数
            row.update(ChargePlanItem(**{**row, 'plan_times': max(row['plan_times'], 1),
                                         'single_times': None}).to_dict())
            QTimer.singleShot(0, self._render)  # 不在控件自身信号中删除控件
        downstream = ('mission_type_name', 'mission_name', 'level') if key == 'category_name' else (
            ('mission_name',) if key == 'mission_type_name' else ())
        for child in downstream:
            if child not in self.editors[index]:
                continue
            choices = self._choices(row, child)
            values = [val for label, val in choices]
            row[child] = row.get(child) if row.get(child) in values else values[0]
            self._set_choices(self.editors[index][child], choices, row[child], preserve=False)
        self._save()

    def _row_fields(self, row):
        from zzz_od.application.charge_plan.charge_plan_config import DOUBLE_REWARD_CATEGORIES
        if self.hunt:
            return self.fields
        hidden = ('plan_times',) if row['category_name'] in DOUBLE_REWARD_CATEGORIES else (
            'double_times', 'single_times')
        return [(key, title) for key, title in self.fields if key not in hidden]

    def _render(self):
        self.add_button.setVisible(not self.single or not self.rows)
        while self.rows_layout.count():
            widget = self.rows_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self.editors = []
        self.scroll.setFixedHeight(320 if self.rows else 64)
        if not self.rows:
            self.rows_layout.addWidget(QLabel(f'暂无计划，点击“{self.add_text}”开始填写。', self.body))
        for index, row in enumerate(self.rows):
            group = QGroupBox(f'计划 {index+1} · 已完成 {row.get("run_times", 0)} 次', self.body)
            layout = QVBoxLayout(group)
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(6)
            editors = {}
            for slot, (key, title) in enumerate(self._row_fields(row)):
                cell = QWidget(group)
                cell_layout = QVBoxLayout(cell)
                cell_layout.setContentsMargins(0, 0, 0, 6)
                label = QLabel(title, cell)
                cell_layout.addWidget(label)
                value = row.get(key)
                if key in ('plan_times', 'notorious_hunt_buff_num', 'double_times', 'single_times'):
                    control = SpinBox(cell)
                    limits = {'plan_times': (1, 99999), 'predefined_team_idx': (-1, 19),
                              'double_times': (0, 99999), 'single_times': (0, 99999),
                              'notorious_hunt_buff_num': (1, 3)}
                    control.setRange(*limits[key])
                    control.setValue(value)
                    control.valueChanged.connect(lambda val, i=index, k=key: self._changed(i, k, val))
                else:
                    control = ComboBox(cell)
                    control.setMaxVisibleItems(10)
                    self._set_choices(control, self._choices(row, key), value)
                    control.currentIndexChanged.connect(lambda _, i=index, k=key: self._choice_changed(i, k))
                    control.setToolTip('先选择副本类别，再选择类型与副本；已保存的旧值会保留')
                control.setMinimumWidth(0)
                control.setAccessibleName(title)
                label.setBuddy(control)
                cell_layout.addWidget(control)
                grid.addWidget(cell, slot//3, slot%3)
                grid.setColumnStretch(slot%3, 1)
                editors[key] = control
            self.editors.append(editors)
            layout.addLayout(grid)
            if not self.single:
                actions = QHBoxLayout()
                actions.addStretch()
                for label, icon, action, enabled in (
                    ('上移', FluentIcon.UP, lambda _, i=index: self.move_plan(i, -1), index > 0),
                    ('下移', FluentIcon.DOWN, lambda _, i=index: self.move_plan(i, 1), index+1 < len(self.rows)),
                    ('删除', FluentIcon.DELETE, lambda _, i=index: self.remove_plan(i), True)):
                    button = PushButton(icon, label, group)
                    button.setEnabled(enabled)
                    button.clicked.connect(action)
                    actions.addWidget(button)
                layout.addLayout(actions)
            self.rows_layout.addWidget(group)
        # ExpandSettingCard fixes its height when built. Rebuilding the rows can
        # change this editor from its empty height to its populated height;
        # propagate that change after Qt has laid out the new controls.
        QTimer.singleShot(0, self._refresh_container_geometry)

    def _refresh_container_geometry(self):
        self.error_label.setVisible(bool(self.error_label.text()))
        self.rows_layout.activate()
        self.layout.invalidate()
        self.layout.activate()
        self.updateGeometry()
        parent = self.parentWidget()
        while parent is not None:
            if parent.layout() is not None:
                parent.layout().invalidate()
                parent.layout().activate()
            adjust = getattr(parent, '_adjust_config_content_size', None)
            if callable(adjust):
                adjust()
                parent.updateGeometry()
                break
            parent = parent.parentWidget()


class DailyOrderTable(TableWidget):
    """Move whole daily rows by identity; cell widgets are rebuilt after a drop."""
    rowMoved = Signal(int, int)
    MIME = 'application/x-okzzz-daily-order'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = uuid.uuid4().hex
        self._drop_slot = None
        self._scroll_step = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._scroll_during_drag)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAutoScroll(True)
        self.setAccessibleName('一条龙执行顺序，拖动行排序，也可按Ctrl加上下方向键')

    def row_mime(self, row):
        mime = QMimeData()
        name = self.item(row, 2).data(Qt.UserRole)
        mime.setData(self.MIME, json.dumps([self._token, name], ensure_ascii=False).encode('utf-8'))
        return mime

    def _source_row(self, mime):
        try:
            token, name = json.loads(bytes(mime.data(self.MIME)))
            if token == self._token:
                return next(row for row in range(self.rowCount()) if self.item(row, 2).data(Qt.UserRole) == name)
        except (ValueError, TypeError, StopIteration, AttributeError):
            pass
        return None

    def startDrag(self, supported_actions):
        row = self.currentRow()
        if row < 0:
            return
        drag = QDrag(self)
        drag.setMimeData(self.row_mime(row))
        drag.setPixmap(self.viewport().grab(self.visualRect(self.model().index(row, 2))))
        drag.exec(Qt.MoveAction)
        self._drop_slot = None
        self._scroll_timer.stop()
        self.viewport().update()

    def dragEnterEvent(self, event):
        if self._source_row(event.mimeData()) is not None:
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def _slot_at(self, point):
        row = self.rowAt(point.y())
        if row < 0:
            return self.rowCount()
        rect = self.visualRect(self.model().index(row, 0))
        return row + (point.y() >= rect.center().y())

    def dragMoveEvent(self, event):
        if self._source_row(event.mimeData()) is None:
            event.ignore()
            return
        self._drop_slot = self._slot_at(event.position().toPoint())
        y = event.position().y()
        self._scroll_step = -16 if y < 28 else (16 if y > self.viewport().height()-28 else 0)
        self._scroll_timer.start()
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.viewport().update()

    def dragLeaveEvent(self, event):
        self._drop_slot = None
        self._scroll_timer.stop()
        self.viewport().update()
        event.accept()

    def dropEvent(self, event):
        source = self._source_row(event.mimeData())
        self._scroll_timer.stop()
        if source is None:
            event.ignore()
            return
        slot = self._slot_at(event.position().toPoint())
        target = max(0, min(self.rowCount()-1, slot-(source < slot)))
        self._drop_slot = None
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.rowMoved.emit(source, target)
        self.setCurrentCell(target, 2)
        self.viewport().update()

    def _scroll_during_drag(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.value()+self._scroll_step)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_slot is not None and self.rowCount():
            last = min(self._drop_slot, self.rowCount()-1)
            rect = self.visualRect(self.model().index(last, 0))
            y = rect.bottom() if self._drop_slot == self.rowCount() else rect.top()
            painter = QPainter(self.viewport())
            painter.setPen(QPen(self.palette().highlight().color(), 3))
            painter.drawLine(0, y, self.viewport().width(), y)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier and event.key() in (Qt.Key_Up, Qt.Key_Down):
            source = self.currentRow()
            target = source+(-1 if event.key() == Qt.Key_Up else 1)
            if 0 <= source < self.rowCount() and 0 <= target < self.rowCount():
                self.rowMoved.emit(source, target)
                self.setCurrentCell(target, 2)
            event.accept()
            return
        super().keyPressEvent(event)


class DraftConfig(dict):
    def __init__(self, values, defaults):
        super().__init__(copy.deepcopy(dict(values)))
        self.default = copy.deepcopy(defaults)

    def has_user_config(self):
        return True

    def get_default(self, key):
        return self.default.get(key)

    def reset_to_default(self):
        self.clear()
        self.update(copy.deepcopy(self.default))


def app_task_for_editor(app_id, owner):
    from src.tasks import app_tasks
    from ok.util.config import Config
    cls = next(value for value in vars(app_tasks).values()
        if isinstance(value, type) and getattr(value, 'app_id', None) == app_id)
    existing = next((task for task in owner.get_tasks() if getattr(task, 'app_id', None) == app_id), None)
    if existing:
        return existing
    task = cls(executor=owner.executor, app=og.app)
    task.config = Config(cls.__name__, task.default_config,
        folder=str(Path(owner.config.config_file).parent), validator=task.validate)
    task.post_init()
    engine = owner.ctx.run_context.get_config(app_id, instance_idx=owner.ctx.current_instance_idx)
    for key in task._option_keys:
        if key in engine.data:
            val = engine.data[key]
            if isinstance(task.default_config.get(key), str) and isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)
            task.config[key] = val
    return task


class AppSettingsDialog(QDialog):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        from ok.ui.qt.tasks.ConfigCard import ConfigContentMixin
        class Form(ConfigContentMixin, QWidget):
            def __init__(self, draft):
                super().__init__()
                self.viewLayout = QVBoxLayout(self)
                self._init_config_content(task, draft, task.default_config,
                    task.config_description, task.config_type)
        self.task = task
        self._refresh_theme()
        qconfig.themeChangedFinished.connect(self._refresh_theme)
        self.setWindowTitle(f'编辑：{task.name}')
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        self.draft = DraftConfig(task.config, task.default_config)
        self.form = Form(self.draft)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form)
        layout.addWidget(scroll)
        self.error_label = QLabel('', self)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = PushButton('取消', self)
        save = PrimaryPushButton('保存设置', self)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)

    def _refresh_theme(self):
        _form_palette(self)

    def save(self):
        original = self.task.config
        try:
            if self.task.running:
                raise ValueError('该应用正在运行，请停止后再保存设置')
            self.task.config = self.draft
            self.task.apply_options()
        except Exception as exc:
            self.error_label.setText(f'未保存：{exc}')
            return
        finally:
            self.task.config = original
        original.update(self.draft)
        original.save_file()
        self.task.log_info(f'{self.task.name}：设置已保存')
        self.accept()


class DailyPlanWidget(ConfigLabelAndWidget):
    def __init__(self, description, config, key, schema, task):
        super().__init__(description, config, key)
        self.task = task
        self.options = schema['options']
        self.layout.setDirection(QHBoxLayout.TopToBottom)
        self.layout.takeAt(1)
        self.layout.setSpacing(12)
        self.table = DailyOrderTable(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['排序', '启用', '执行内容', '设置'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 48)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 64)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 100)
        self.table.verticalHeader().hide()
        self.table.rowMoved.connect(self.move_to)
        self.add_widget(self.table)
        self.update_value()

    def update_value(self):
        stored = self.config.get('执行顺序') or []
        self.order = list(dict.fromkeys([name for name in stored if name in self.options]+self.options))
        enabled = set(self.config.get(self.key) or [])
        self.table.setRowCount(len(self.order))
        self.checks = []
        self.table.setFixedHeight(min(440, 38+42*len(self.order)))
        from zzz_od.application.app_options_data import APP_OPTIONS
        by_name = {a['app_name']: a['app_id'] for a in APP_OPTIONS if 'app_id' in a}
        from src.tasks.task_presentation import TASK_DESCRIPTIONS
        for row, name in enumerate(self.order):
            self.table.setRowHeight(row, 42)
            grip = QTableWidgetItem('≡')
            grip.setTextAlignment(Qt.AlignCenter)
            grip.setToolTip('拖动此行调整执行顺序；Ctrl+↑/↓也可排序')
            self.table.setItem(row, 0, grip)
            check = CheckBox('', self.table)
            check.setChecked(name in enabled)
            check.setAccessibleName(f'启用{name}')
            check.toggled.connect(lambda value, n=name: self._toggle(n, value))
            self.table.setCellWidget(row, 1, check)
            self.checks.append(check)
            label = QTableWidgetItem(f'{row+1}. {name}')
            label.setData(Qt.UserRole, name)
            label.setToolTip(TASK_DESCRIPTIONS.get(by_name.get(name), ''))
            self.table.setItem(row, 2, label)
            actions = QWidget(self.table)
            layout = QHBoxLayout(actions)
            layout.setContentsMargins(4, 4, 4, 4)
            button = PushButton('编辑', actions)
            button.clicked.connect(lambda _, aid=by_name[name]: self.edit_app(aid))
            layout.addWidget(button)
            self.table.setCellWidget(row, 3, actions)

    def _toggle(self, name, enabled):
        current = set(self.config.get(self.key) or [])
        current.add(name) if enabled else current.discard(name)
        self.update_config([name for name in self.order if name in current])

    def move(self, row, delta):
        self.move_to(row, row+delta)

    def move_to(self, row, other):
        if 0 <= row < len(self.order) and 0 <= other < len(self.order) and row != other:
            self.order.insert(other, self.order.pop(row))
            self.config['执行顺序'] = self.order[:]
            self.update_value()

    def edit_app(self, app_id):
        if self.task.running:
            self.task.log_info('一条龙运行中，请停止后编辑应用设置', notify=True)
            return
        try:
            self.settings_dialog = AppSettingsDialog(app_task_for_editor(app_id, self.task), self.window())
            self.settings_dialog.exec()
        except Exception as exc:
            self.task.log_error(f'打开应用设置失败：{exc}', notify=True)
