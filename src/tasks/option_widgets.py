"""项目内的中文配置控件适配，不修改 ok-script 依赖或配置键。"""
import json
from importlib import import_module

from PySide6.QtWidgets import QVBoxLayout
from qfluentwidgets import ComboBox
from ok.ui.qt.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget


class AppChoiceWidget(ConfigLabelAndWidget):
    def __init__(self, description, config, key, schema):
        super().__init__(description, config, key)
        self.options = schema['options']
        labels = schema.get('option_labels', {})
        self.combo_box = ComboBox()
        self.combo_box.addItems([str(labels.get(value, value)) for value in self.options])
        self.combo_box.setMinimumWidth(180)
        self.add_widget(self.combo_box, stretch=0)
        self.update_value()
        # 先写配置，ConfigCard 随后订阅同一个信号才能读到最新值。
        self.combo_box.currentTextChanged.connect(self._text_changed)

    def _text_changed(self, _text):
        self._changed(self.combo_box.currentIndex())

    def _changed(self, index):
        if 0 <= index < len(self.options):
            self.update_config(self.options[index])

    def update_value(self):
        value = self.config.get(self.key)
        self.combo_box.blockSignals(True)
        self.combo_box.setCurrentIndex(self.options.index(value) if value in self.options else -1)
        self.combo_box.blockSignals(False)


class AppPriorityWidget(ConfigLabelAndWidget):
    """按先后顺序选择兑换物品，仍保存为原有的 JSON 数组文本。"""
    def __init__(self, description, config, key, schema):
        super().__init__(description, config, key)
        self.options = [None, *schema['options']]
        labels = schema['option_labels']
        layout = QVBoxLayout()
        self.boxes = []
        for index in range(len(schema['options'])):
            box = ComboBox()
            box.addItems(['不兑换', *[labels.get(value, value) for value in schema['options']]])
            box.setToolTip(f'兑换优先级 {index + 1}')
            box.setMinimumWidth(180)
            layout.addWidget(box)
            self.boxes.append(box)
        self.add_layout(layout, stretch=0)
        self.update_value()
        for box in self.boxes:
            box.currentIndexChanged.connect(self._changed)

    def _changed(self, _index):
        values = []
        for box in self.boxes:
            index = box.currentIndex()
            value = self.options[index] if index >= 0 else None
            if value is not None and value not in values:
                values.append(value)
        self.update_config(json.dumps(values, ensure_ascii=False))
        self.update_value()

    def update_value(self):
        try:
            values = self.config.get(self.key, '[]')
            values = json.loads(values) if isinstance(values, str) else values
        except (ValueError, TypeError):
            values = []
        for index, box in enumerate(self.boxes):
            value = values[index] if index < len(values) else None
            box.blockSignals(True)
            box.setCurrentIndex(self.options.index(value) if value in self.options else -1)
            box.blockSignals(False)


def install_option_widgets():
    """只适配明确声明的应用选项；其它依赖控件仍走原来的工厂。"""
    from src.tasks.diagnostic_controls import install_diagnostic_controls
    install_diagnostic_controls()
    task_card = import_module('ok.ui.qt.tasks.TaskCard').TaskCard
    if not getattr(task_card, '_zzz_default_expanded', False):
        original_init = task_card.__init__

        def initialize(self, task, onetime):
            original_init(self, task, onetime)
            if getattr(task, 'default_expanded', False):
                self.setExpand(True)

        task_card.__init__ = initialize
        task_card._zzz_default_expanded = True
    card = import_module('ok.ui.qt.tasks.ConfigCard')
    if getattr(card.config_widget, '_zzz_options', False):
        return
    original = card.config_widget

    def factory(config_type, description, config, key, value, task):
        from src.tasks.app_option_ui import OPTION_LABELS
        schema = (config_type or {}).get(key, {})
        if isinstance(schema, dict) and schema.get('type') == 'daily_plan':
            from src.tasks.plan_widgets import DailyPlanWidget
            widget = DailyPlanWidget(description, config, key, schema, task)
        elif isinstance(schema, dict) and schema.get('type') == 'charge_plans':
            from src.tasks.plan_widgets import ChargePlanWidget
            widget = ChargePlanWidget(description, config, key, schema)
        elif isinstance(schema, dict) and schema.get('type') == 'ordered_choices':
            widget = AppPriorityWidget(description, config, key, schema)
        elif isinstance(schema, dict) and schema.get('localized_choices'):
            widget = AppChoiceWidget(description, config, key, schema)
        else:
            widget = original(config_type, description, config, key, value, task)
        if isinstance(schema, dict) and schema.get('label'):
            widget.title.setText(schema['label'])
        elif key in OPTION_LABELS:
            widget.title.setText(OPTION_LABELS[key])
        project_task = task is not None and type(task).__module__.startswith('src.tasks.')
        if key in OPTION_LABELS or project_task:
            from qfluentwidgets import SwitchButton
            switch = getattr(widget, 'switch_button', None)
            if isinstance(switch, SwitchButton):
                switch.setOnText('是')
                switch.setOffText('否')
        return widget

    factory._zzz_options = True
    card.config_widget = factory
    original_buttons = card.ConfigContentMixin.add_buttons

    def localized_buttons(self):
        from src.tasks.app_option_ui import OPTION_LABELS
        original_buttons(self)
        project_task = self.task is not None and type(self.task).__module__.startswith('src.tasks.')
        if not project_task and not any(key in OPTION_LABELS for key in self.default_config or {}):
            return
        if self.reset_config is not None:
            self.reset_config.setText('恢复默认设置')
        if self.viewLayout.count():
            row = self.viewLayout.itemAt(self.viewLayout.count() - 1).widget()
            if hasattr(row, 'title'):
                row.title.setText('操作')
                from qfluentwidgets import PushButton
                for button in row.findChildren(PushButton):
                    if button is not self.reset_config:
                        button.setText('添加开始菜单快捷方式')

    card.ConfigContentMixin.add_buttons = localized_buttons
