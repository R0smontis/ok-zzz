"""迷失之地启动链检查：使用真实资源和状态机，不发送游戏输入。"""
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def check_lost_void_runtime(root):
    import numpy as np
    from onedragon.utils import os_utils
    from zzz_od.context.zzz_context import ZContext
    from zzz_od.application.hollow_zero.lost_void.lost_void_app_factory import LostVoidAppFactory
    from zzz_od.application.hollow_zero.lost_void.lost_void_config import LostVoidTaskEnum
    from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType
    from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel
    from zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det import LostVoidMoveByDet

    root = Path(root)
    original_path = os_utils.get_path_under_work_dir
    with tempfile.TemporaryDirectory(prefix='.lost-void-check-', dir=str(root)) as folder:
        work = Path(folder)
        # 只复制分发的模板配置，初始化记录全部写入临时目录。
        shutil.copytree(root / 'config', work / 'config',
                        ignore=lambda _path, names: [name for name in names
                            if name.isdigit() or name in ('one_dragon.yml', 'model.yml', 'env.yml')])

        def resource_path(*parts):
            if parts and parts[0] == 'config':
                target = work.joinpath(*parts)
                target.mkdir(parents=True, exist_ok=True)
                return str(target)
            return original_path(*parts)

        with patch.object(os_utils, 'get_path_under_work_dir', resource_path):
            ctx = ZContext()
            try:
                ctx.init()
                def release_only(*_args, **kwargs):
                    assert kwargs.get('release'), '启动检查禁止发送按下动作'
                ctx.controller = SimpleNamespace(is_game_window_ready=True,
                    game_win=SimpleNamespace(win_title='离线测试窗口'),
                    screenshot=lambda: (time.time(), np.zeros((1080, 1920, 3), np.uint8)),
                    **{name: release_only for name in ('dodge', 'normal_attack', 'special_attack',
                        'move_w', 'move_s', 'move_a', 'move_d', 'switch_next', 'switch_prev',
                        'switch_backup', 'lock', 'ultimate', 'chain_cancel', 'chain_left', 'chain_right')})
                ctx.run_context.registry_application(LostVoidAppFactory(ctx))
                app = ctx.run_context.get_application('lost_void', instance_idx=ctx.current_instance_idx)
                # 复现同一进程里悬赏完成后改用周计划的操作，确保冻结包也覆盖配置共享。
                from src.tasks.app_task_base import AppTaskBase
                record = app.run_record
                record.bounty_commission_complete = True
                assert record.is_finished_by_day
                settings = {'extra_task': LostVoidTaskEnum.WEEKLY_PLAN_TIMES.value.value,
                            'daily_plan_times': 9999, 'weekly_plan_times': 9999}
                task = SimpleNamespace(app_id='lost_void', name='迷失之地离线检查', ctx=ctx,
                    config=settings, _option_keys=list(settings),
                    _parse_option=lambda _key, value: value, log_info=lambda _message: None)
                AppTaskBase.apply_options(task)
                assert app.config is record.config, '应用和完成判定必须共用配置'
                assert not record.is_finished_by_day, '切换周计划后不应沿用悬赏已完成状态'
                app._init_before_execute()
                assert app._current_node.cn == '检测游戏窗口'
                result = app._execute_one_round()
                assert result.is_success, result.status
                app._current_node = app._get_next_node(result)
                assert app._current_node.cn == '初始化加载', '不应跳转到打开游戏'
                app._reset_status_for_new_node()
                result = app._execute_one_round()
                assert result.is_success and result.status == app.STATUS_AGAIN, result.status
                app._current_node = app._get_next_node(result)
                assert app._current_node.cn == '识别初始画面'
                lost = ctx.lost_void
                assert lost is ctx.lost_void and lost.ctx is ctx
                assert len(lost.all_artifact_list) > 0 and len(lost.investigation_strategy_list) > 0
                assert lost.challenge_config.data and lost.get_auto_op_name()
                assert lost.detector.run(np.zeros((1080, 1920, 3), np.uint8)).results == []
                for cls in (LostVoidRunLevel, LostVoidMoveByDet):
                    args = (ctx, LostVoidRegionType.ENTRY)
                    op = cls(*args) if cls is LostVoidRunLevel else cls(*args, '0000-感叹号')
                    op._init_network()
                    assert op._start_node.cn == '检测游戏窗口'
                ctx.auto_battle_context.init_screen_area()
                assert app.load_auto_op().is_success
                assert ctx.auto_battle_context.auto_op is not None
                patrol = ctx.world_patrol_service
                assert patrol is ctx.world_patrol_service and patrol.ctx is ctx
                assert not patrol.cut_mini_map(np.zeros((1080, 1920, 3), np.uint8)).play_mask_found
                # 使用真实应用核验模式切换，但手柄输入仍由记录替身接收。
                import zzz_od.application.hollow_zero.lost_void.lost_void_app as app_module
                from onedragon.base.geometry.point import Point
                from onedragon.base.geometry.rectangle import Rect
                from unittest.mock import Mock
                from onedragon.base.operation.operation_round_result import OperationRoundResultEnum
                app.config.mission_name = '特遣调查'
                pad_keys = []
                offline_pad = SimpleNamespace(background_mode=True,
                    btn_press=lambda key, **_kwargs: pad_keys.append(key))
                app.last_screenshot = np.zeros((1080,1920,3), np.uint8)
                titles = {'特遣调查': SimpleNamespace(center=Point(1525,340)),
                          '战线肃清': SimpleNamespace(center=Point(976,340))}
                with patch.object(ctx, 'controller', offline_pad), \
                     patch.object(app, '_after_round_wait', lambda **_kwargs: None), \
                     patch.object(app_module, 'detail_mission', side_effect=['战线肃清',None,None,'特遣调查']), \
                     patch.object(app_module, 'focused_card', side_effect=[Rect(711,304,1241,516),Rect(1261,304,1791,516)]), \
                     patch.object(app_module, 'menu_matches', return_value=titles):
                    assert app.goto_mission_screen().result == OperationRoundResultEnum.WAIT
                    assert app.goto_mission_screen().result == OperationRoundResultEnum.WAIT
                    assert app.goto_mission_screen().result == OperationRoundResultEnum.WAIT
                    assert app.goto_mission_screen().is_success
                    assert pad_keys == ['xbox_b','xbox_dpad_right','xbox_a']
                with patch.object(app_module, 'detail_mission', return_value='战线肃清'), \
                     patch.object(app_module, 'match_team_agent_template', Mock(side_effect=AssertionError('错误模式禁止识别 UP'))):
                    mismatch = app.check_for_mission()
                    assert mismatch.status == '副本模式不一致'
                    app._current_node = app._node_map['副本画面识别']
                    assert app._get_next_node(mismatch).cn == '前往副本画面'
                return {'startup_nodes': ['检测游戏窗口', '初始化加载', '识别初始画面'],
                        'mission_selection_verified': 'passed', 'gamepad_mode_recovery': 'passed',
                        'weekly_plan_after_bounty': 'passed',
                        'return_world_minimap': 'passed',
                        'navigation_nodes': 'passed', 'battle_config': lost.get_auto_op_name(),
                        'artifacts': len(lost.all_artifact_list),
                        'strategies': len(lost.investigation_strategy_list),
                        'model': lost.detector.model_name,
                        'providers': lost.detector.session.get_providers(),
                        'classes': len(lost.detector.idx_2_class), 'blank_inference': 'passed',
                        'game_input': 'none'}
            finally:
                ctx.after_app_shutdown()
