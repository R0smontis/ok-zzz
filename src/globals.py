# -*- coding: utf-8 -*-
"""ok-zzz 全局单例（ok-script my_app）。

持有 ZzzContext（战斗引擎与应用框架装配点），并桥接 ok-script 运行时：
- OCR: og.app.executor.ocr_lib('default')（onnxocr）
- 截图: og.executor.next_frame / frame
- 应用注册: discover_factories(ctx)
"""
import time
import threading

from ok import Logger
from ok import og

logger = Logger.get_logger(__name__)


class Globals:

    def __init__(self, exit_event):
        super().__init__()
        from src.controls.win32_compat import install_win32_compat
        install_win32_compat()
        from src.controls.capture_compat import install_capture_compat
        install_capture_compat()
        from src.controls.interaction import install_interaction_labels
        install_interaction_labels()
        from src.runtime.logging_bridge import install_runtime_logging
        install_runtime_logging()
        from src.tasks.option_widgets import install_option_widgets
        install_option_widgets()
        from src.runtime.gpu_ocr import install_gpu_ocr
        install_gpu_ocr()
        from src.runtime.startup import install_update_compat
        install_update_compat()
        from src.runtime.game_discovery import install_game_discovery
        self._game_discovery_timer = install_game_discovery()
        self.exit_event = exit_event
        self._context = None
        self._shutdown_lock = threading.Lock()
        self._stopped = False
        if hasattr(exit_event, 'bind_stop'):
            exit_event.bind_stop(self)
        self._stop_on_session_end()

    def _stop_on_session_end(self):
        """Windows logoff/shutdown can end the process before the normal exit path runs."""
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            app.commitDataRequest.connect(lambda _manager: self._session_ending())

    def _session_ending(self):
        logger.info('Windows 正在注销或关机：停止任务并移除虚拟手柄')
        self.stop()

    def stop(self):
        """Framework ExitEvent callback; release inputs before captures are closed."""
        with self._shutdown_lock:
            if self._stopped:
                return
            self._stopped = True
        live_debug = getattr(self, 'live_debug', None)
        if live_debug is not None:
            live_debug.stop()
        from src.diagnostics.recorder import recorder
        recorder.stop('程序退出')
        executor = getattr(og, 'executor', None)
        for task in getattr(executor, 'trigger_tasks', ()):
            stop_engine = getattr(task, '_stop_engine', None)
            if callable(stop_engine):
                try:
                    stop_engine()
                except Exception as error:
                    logger.warning(f'退出时停止助手失败: {error}')
        context = self._context
        if context is not None:
            try:
                context.run_context.stop_running()
            except Exception as error:
                logger.warning(f'退出时停止任务失败: {error}')
            context.after_app_shutdown()
            if context.controller is not None:
                try:
                    context.controller.disconnect_virtual_gamepad_bus()
                except Exception as error:
                    logger.warning(f'退出时移除虚拟手柄失败: {error}')
        overlay = getattr(self, '_overlay_manager', None)
        if overlay is not None:
            try:
                overlay.shutdown()
            except Exception as error:
                logger.warning(f'退出时停止悬浮窗失败: {error}')
        logger.info('程序退出清理完成：战斗输入、声音监听、调试录制与虚拟手柄已停止')

    # ------------------------------------------------------------------ #
    # ok-script 桥接
    # ------------------------------------------------------------------ #

    def _get_ocr_lib(self):
        """返回 ok-script 的 onnxocr 实例（供 OkOcrMatcher 惰性调用）。"""
        return og.executor.ocr_lib('default')

    def _frame_provider(self):
        """强制取新帧并返回 (截图时间, BGR 帧)，由控制器转换到 RGB。"""
        executor = og.executor
        frame = executor.next_frame(time_out=12)
        if frame is None:
            context = self._context
            if context is not None:
                context.auto_battle_context.stop_auto_battle()
                if context.controller is not None:
                    context.controller.cancel_inputs()
            raise RuntimeError('连续12秒无法取得游戏画面，已停止输入；请检查截图方式和游戏窗口')
        from src.runtime.frozen_capture import FrozenCaptureWatch, handle_frozen_capture
        watch = self.__dict__.setdefault('_capture_watch', FrozenCaptureWatch())
        handle_frozen_capture(watch, frame, getattr(executor, 'method', None))
        return executor._last_frame_time, frame

    def _window_provider(self):
        """Use the selected capture device; never rediscover a game by title."""
        manager = getattr(og, 'device_manager', None)
        if manager is None:
            return 0
        device = manager.get_preferred_device()
        if not device or device.get('device') != 'windows':
            return 0
        window = getattr(manager, 'hwnd_window', None)
        hwnd = getattr(window, 'hwnd', 0)
        return hwnd if hwnd and hwnd == device.get('real_hwnd') else 0

    def _sync_game_hotkeys(self, game_config):
        from src.config import key_config_option
        from src.controls.hotkey_settings import sync_hotkeys
        sync_hotkeys(og.global_config.get_config(key_config_option), game_config)
        from src.controls.interaction import background_mode_selected
        game_config._framework_background_mode = background_mode_selected()

    @property
    def context(self):
        """ZzzContext 惰性创建（需要 ok-script 完成设备初始化后调用）。"""
        if self._context is None:
            if self._stopped:
                raise RuntimeError('程序正在退出，无法创建游戏上下文')
            from zzz_od.application.app_registry import discover_factories
            from zzz_od.context.zzz_context import ZContext
            context = ZContext(
                get_ocr_lib=self._get_ocr_lib if og.executor is not None else None,
                frame_provider=self._frame_provider,
                window_provider=self._window_provider,
                game_config_sync=self._sync_game_hotkeys,
            )
            discover_factories(context)
            context.init()
            self._adopt_game_path(context)
            self._context = context
            logger.info('ZzzContext 已创建并完成应用注册')
        return self._context

    @staticmethod
    def _adopt_game_path(context):
        """Share the selected/detected executable with the account's launch config."""
        from src.runtime.game_discovery import configure_game_path, OPTION_NAME, PATH_KEY
        global_config = getattr(og, 'global_config', None)
        settings = global_config.get_config(OPTION_NAME) if global_config is not None else {}
        path = configure_game_path(getattr(og, 'device_manager', None),
            context.game_account_config, selected_path=settings.get(PATH_KEY, ''))
        if path:
            logger.info(f'已使用游戏路径：{path}')

    def ensure_context_for_game(self):
        """游戏启动后的完整初始化（画面区域等）。"""
        self.context.init_for_application()
        return self.context

    def ensure_overlay(self):
        """游戏内悬浮窗（识别框/HUD/日志面板，热键 o 开关）；失败静默。"""
        if self._context is None:
            return None
        if getattr(self, '_overlay_manager', None) is not None:
            return self._overlay_manager
        try:
            from onedragon.qt.overlay.overlay_manager import OverlayManager
            self._overlay_manager = OverlayManager(self._context)
            self._overlay_manager.start()
            logger.info('Overlay 已启动（热键 o 开关）')
            return self._overlay_manager
        except Exception as e:
            logger.warning(f'Overlay 启动失败（不影响核心功能）: {e}')
            self._overlay_manager = None
            return None
