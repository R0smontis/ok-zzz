"""A separate sidebar page for recording and developer tasks."""
from qfluentwidgets import FluentIcon, NavigationItemPosition
from ok import og
from ok.ui.qt.tasks.TaskCard import TaskCard
from ok.ui.qt.tasks.TaskTab import TaskTab


class DebugToolsTab(TaskTab):
    name = '调试'
    icon = FluentIcon.DEVELOPER_TOOLS
    position = NavigationItemPosition.SCROLL
    add_after_default_tabs = True

    def __init__(self):
        self.tasks = [task for task in og.executor.get_all_tasks()
            if getattr(task, 'debug_tool', False)]
        self.tasks.sort(key=lambda task: not getattr(task, 'recording_controls', False))
        super().__init__()
        self.keep_info_when_done = True
        from src.tasks.live_debug_panel import LiveDebugPanel
        self.live_debug_panel = LiveDebugPanel(self.view)
        self.live_debug_card = self.add_card('实时调试与控制', self.live_debug_panel)
        self.vBoxLayout.removeWidget(self.live_debug_card)
        self.vBoxLayout.insertWidget(0, self.live_debug_card)
        self.card_widgets = []
        for task in self.tasks:
            card = TaskCard(task, task in og.executor.onetime_tasks)
            self.card_widgets.append(card)
            self.add_task_card(card)

    def in_current_list(self, task):
        return task in self.tasks
