import json
from pathlib import Path
from types import SimpleNamespace
from onedragon.base.geometry.rectangle import Rect

import pytest

from src.navigation.restore_charge import quick_use, source_page
from zzz_od.operation.restore_charge import RestoreCharge
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from test_lost_void_background_menus import operation
from test_daily_menu_results import fixture


CARD_X={'储蓄电量':819,'以太电池':960,'菲林':1101}


def edit_cards(raw, hide=(), counts=None):
    """OCR of the same dialog with some cards absent or showing another count (label + number row)."""
    rows=[]
    for row in raw:
        x,y,w,h=row['rect']
        card=next((n for n,cx in CARD_X.items() if abs(x+w/2-cx)<45 and 560<y+h/2<650),None)
        if card in hide:
            continue
        if card in (counts or {}) and 560<y+h/2<605:
            row=dict(row,text=str(counts[card]))
        rows.append(row)
    return rows


def restore(name, policy='使用储蓄电量', hide=(), counts=None):
    op = operation(RestoreCharge)
    fixture(op, name)
    data=json.loads((Path(__file__).parent/'fixtures/daily_map'/f'{name}.json').read_text(encoding='utf-8'))
    raw=edit_cards(data['result']['ocr'],hide,counts)
    unique={}
    for row in raw:
        x,y,w,h=row['rect']
        key=(row['text'].replace(' ',''),x+w/2,y+h/2)
        if not any(key[0]==old[0] and abs(key[1]-old[1])<8 and abs(key[2]-old[2])<8 for old in unique):
            unique[key]=SimpleNamespace(data=row['text'],center=Rect(x,y,x+w,y+h).center)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect,**kw:[
        row for row in unique.values() if rect.x1<=row.center.x<rect.x2 and rect.y1<=row.center.y<rect.y2])
    op.config = SimpleNamespace(restore_charge=policy)
    op.skip_backup_charge = False
    op.is_after_battle_retry = False
    op._previous_node=None
    return op


@pytest.mark.parametrize('name,expected', [('restore-quick', ('储蓄电量',501,60)),
                                          ('restore-ether-use', ('以太电池',28,1))])
def test_real_quick_use_reads_source_inventory_and_complete_exchange_number(name, expected):
    assert quick_use(restore(name)) == expected


@pytest.mark.parametrize('name,source,button', [
    ('restore-select','储蓄电量','confirm'), ('restore-up','储蓄电量',None),
    ('restore-ether-focus','以太电池',None), ('restore-source-confirm','以太电池','cancel'),
    ('restore-confirm-focus','以太电池','confirm')])
def test_real_source_cards_keep_identity_while_button_has_focus(name, source, button):
    state = source_page(restore(name))
    assert state['selected'] == source and state['button'] == button


def test_real_cards_and_counts_are_read():
    state = source_page(restore('restore-ether-focus'))
    assert set(state['cards']) == {'储蓄电量','以太电池','菲林'}
    assert state['counts'] == {'储蓄电量':501,'以太电池':28,'菲林':31}


BOTH='同时使用储蓄电量和以太电池'


@pytest.mark.parametrize('name,hide,counts,policy,expected', [
    # 以太电池 hidden or at 0 (2026-10-25 onward): 储蓄电量 is still chosen.
    ('restore-up',('以太电池',),None,BOTH,'储蓄电量'),
    ('restore-up',(),{'以太电池':0},BOTH,'储蓄电量'),
    # 储蓄电量 hidden or at 0: both-enabled goes straight to 以太电池.
    ('restore-ether-focus',('储蓄电量',),None,BOTH,'以太电池'),
    ('restore-ether-focus',(),{'储蓄电量':0},BOTH,'以太电池'),
])
def test_source_page_is_recognised_whichever_sources_are_missing(name, hide, counts, policy, expected):
    op = restore(name, policy, hide, counts)
    assert source_page(op) is not None
    result = op.select_charge_source()
    assert result.is_success and result.status == expected and op._restore_source == expected
    op.ctx.controller.btn_press.assert_not_called()


def test_missing_card_keeps_button_focus_handling_and_card_direction():
    op = restore('restore-select', '使用储蓄电量', hide=('以太电池',))
    assert op.select_charge_source().result == R.WAIT  # Focus is on 确认: back to the cards first.
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)
    op = restore('restore-up', '使用以太电池')
    assert op.select_charge_source().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)


@pytest.mark.parametrize('hide,counts,policy', [
    (('以太电池',),None,'使用以太电池'), ((),{'以太电池':0},'使用以太电池'),
    (('储蓄电量','以太电池'),None,BOTH), ((),{'储蓄电量':0,'以太电池':0},BOTH)])
def test_no_usable_source_closes_the_popup_and_reports_charge_not_enough(hide, counts, policy):
    from src.navigation.restore_charge import NO_SOURCE
    op = restore('restore-up', policy, hide, counts)
    result = op.select_charge_source()
    assert result.is_success and result.status == NO_SOURCE
    op.ctx.controller.btn_press.assert_not_called()
    op._previous_round_result = result
    op._previous_node = SimpleNamespace(cn='选择电量来源')
    assert op.close_restore_popup().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    op.ctx.ocr_service.get_ocr_result_list = lambda **kwargs: []
    op.round_by_find_area = lambda *args: SimpleNamespace(is_success=False)
    closed = op.close_restore_popup()
    assert closed.is_success and closed.status == RestoreCharge.STATUS_CHARGE_NOT_ENOUGH
    assert op.ctx.controller.btn_press.call_count == 1


def test_focus_on_film_moves_left_and_film_is_never_chosen(monkeypatch):
    import src.navigation.restore_charge as module
    card = lambda x: SimpleNamespace(center=SimpleNamespace(x=x))
    state = dict(cards={'储蓄电量':card(890),'菲林':card(1030)}, counts={'储蓄电量':186,'菲林':31},
                 selected='菲林', button=None)
    monkeypatch.setattr(module, 'source_page', lambda op: state)
    op = restore('restore-up', BOTH)
    assert module.choose_source(op, ['储蓄电量','以太电池']).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_left',press_time=.12)
    assert module.usable_sources(state, ['菲林']) == []


def test_backup_only_never_confirms_ether_or_film():
    op = restore('restore-ether-focus')
    assert op.select_charge_source().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_left',press_time=.12)
    op = restore('restore-ether-use')
    op._previous_round_result = op.round_success('储蓄电量')
    assert op.set_charge_amount().is_fail
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()


def test_source_confirm_waits_for_quick_page_not_input_delivery():
    op = restore('restore-select')
    op._restore_source='储蓄电量'
    assert op.confirm_charge_source().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    following=restore('restore-quick')
    op.last_screenshot=following.last_screenshot
    op.ctx.ocr_service=following.ctx.ocr_service
    assert op.confirm_charge_source().is_success
    assert op.ctx.controller.btn_press.call_count == 1


def test_source_confirmation_navigates_from_cancel_to_confirm():
    op = restore('restore-source-confirm', '使用以太电池')
    op._restore_source='以太电池'
    assert op.confirm_charge_source().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)


@pytest.mark.parametrize('policy,source', [('使用储蓄电量','储蓄电量'),('使用以太电池','以太电池'),
                                         ('同时使用储蓄电量和以太电池','储蓄电量')])
def test_policy_selects_only_allowed_source(policy, source):
    op=restore('restore-up',policy)
    result=op.select_charge_source()
    if source=='储蓄电量':
        assert result.is_success and result.status==source
    else:
        assert result.result==R.WAIT
        op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)


@pytest.mark.parametrize('current,exchange,ok', [(60,60,True),(59,60,False),(0,0,False),
                                              (501,60,True),(28,1,True),(-1,1,False)])
def test_stock_equal_to_request_is_valid_but_zero_or_excess_is_not(current,exchange,ok):
    assert operation(RestoreCharge)._should_confirm_restore(current,exchange)==ok


def test_confirmation_requires_unchanged_quick_use_source_and_amount():
    op=restore('restore-quick')
    op._previous_round_result=op.round_success('储蓄电量')
    assert op.set_charge_amount().is_success
    assert op.confirm_restore_charge().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    following=restore('restore-ether-use')
    op.last_screenshot=following.last_screenshot
    op.ctx.ocr_service=following.ctx.ocr_service
    assert op.confirm_restore_charge().result==R.RETRY
    assert op.ctx.controller.btn_press.call_count==1


def test_no_repeat_consumption_and_no_success_on_unknown_screen():
    op=restore('restore-quick')
    op._restore_source='储蓄电量';op._restore_before_amount=501
    op._restore_obtained_seen=False
    assert op.confirm_after_restore().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    fixture(op,'restore-ether-focus')
    op.ctx.ocr_service.get_ocr_result_list=lambda **kwargs: []
    op.round_by_find_area=lambda *args:SimpleNamespace(is_success=False)
    assert op.confirm_after_restore().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_unavailable_backup_uses_ether_only_when_both_enabled(monkeypatch):
    import zzz_od.operation.restore_charge as module
    for policy,expected in [('使用储蓄电量',RestoreCharge.STATUS_CHARGE_NOT_ENOUGH),
                            ('同时使用储蓄电量和以太电池','重新选择电量来源')]:
        op=restore('restore-quick',policy)
        op._previous_round_result=op.round_success('储蓄电量')
        monkeypatch.setattr(module,'quick_use',lambda op:('储蓄电量',0,0))
        result=op.set_charge_amount()
        assert result.status==expected
        assert op.skip_backup_charge == (expected=='重新选择电量来源')
        op.ctx.controller.btn_press.assert_not_called()


def test_disabled_restore_returns_to_finish_after_popup_closes():
    from zzz_od.operation.challenge_mission.check_next_after_battle import ChooseNextOrFinishAfterBattle
    op=operation(ChooseNextOrFinishAfterBattle)
    op.try_next=True
    visible=[True]
    op.round_by_find_area=lambda *args:SimpleNamespace(is_success=visible[0])
    op.ctx.run_context=SimpleNamespace(get_config=lambda **kwargs:SimpleNamespace(is_restore_charge_enabled=False))
    op.ctx.current_instance_idx=1
    assert op.restore_charge().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    visible[0]=False
    result=op.restore_charge()
    assert result.is_success and result.status=='战斗结果-完成'
    assert not op.try_next
