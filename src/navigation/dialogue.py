"""Controller input for dialogue detected on the current frame; never click unknown screens."""
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.menus import label_focused, press_labelled


SENSITIVE_OPTIONS = ('购买', '支付', '消耗', '充值', '解锁', '拆解', '销毁', '兑换')


def _text(value):
    return str(value).replace(' ', '').strip()


def _rows(op, screen, rect):
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=rect)
    return rows if isinstance(rows, (list, tuple)) else []


def dialogue_action(op, screen, action):
    """Run one detected action. A changed action releases the old pending confirmation.

    Options require a unique filled focus and a matching visible label; skip confirmations
    are only supplied by DialogueDetector after it sees an explicit 跳过 prompt.
    """
    if action is None:
        op._dialogue_pad_pending = None
        op._dialogue_pad_steps = 0
        op._dialogue_menu_opened = False
        return op.round_retry('等待已核验的对话画面', wait=.5)
    text = _text(action.text)
    if action.kind == 'option' and any(word in text for word in SENSITIVE_OPTIONS):
        return op.round_retry('对话选项涉及购买、消耗或解锁，等待人工确认', wait=1)
    body = tuple(_text(r.data) for r in _rows(op, screen, Rect(418, 831, 1500, 980))) if action.kind == 'advance' else ()
    signature = (action.kind, text, action.point.x, action.point.y, body)
    pending = getattr(op, '_dialogue_pad_pending', None)
    if pending is not None and pending['signature'] == signature:
        pending['waits'] += 1
        if pending['waits'] >= 6:
            return op.round_fail('对话确认后页面未变化，不重复确认')
        return op.round_wait('等待对话画面变化，未重复确认', wait=.5)
    op._dialogue_pad_pending = None
    previous = getattr(op, '_dialogue_pad_target', None)
    if previous != signature:
        op._dialogue_pad_steps = 0
        op._dialogue_pad_target = signature
    steps = getattr(op, '_dialogue_pad_steps', 0)
    if steps >= 12:
        return op.round_fail('手柄定位对话选项未生效')

    if action.kind == 'option':
        # The detector chooses first/last; input still needs the current option's focus.
        rows = _rows(op, screen, Rect(500, 220, 1920, 850))
        labels = [r for r in rows if abs(r.center.x - action.point.x) < 180
                  and 220 < r.center.y < 850 and len(_text(r.data)) > 1]
        target = next((r for r in labels if _text(r.data) == text
                       and abs(r.center.y - action.point.y) < 25), None)
        focused = [r for r in labels if label_focused(screen, r.center, 110)]
        if target is None or len(focused) != 1:
            return op.round_retry('对话选项及唯一焦点未核验，未操作', wait=.5)
        op._dialogue_pad_steps = steps + 1
        if abs(focused[0].center.y - target.center.y) >= 25:
            pad(op.ctx, 'dpad_up' if target.center.y < focused[0].center.y else 'dpad_down')
            return op.round_wait('手柄定位已配置的对话选项', wait=.5)
        pad(op.ctx, 'a')
    elif action.kind == 'confirm_skip':
        if not label_focused(screen, action.point, 120):
            return op.round_retry('跳过确认焦点未核验，未操作', wait=.5)
        pad(op.ctx, 'a')
    elif action.kind == 'advance':
        # DialogueDetector verified the dialogue body and excluded battle and menu HUDs.
        pad(op.ctx, 'a')
    elif action.kind in ('skip', 'menu', 'auto'):
        label = {'skip': '跳过', 'menu': '菜单', 'auto': '自动'}[action.kind]
        if not press_labelled(op, screen, label, Rect(1500, 0, 1920, 330)):
            return op.round_retry('剧情按钮的手柄提示未核验，未操作', wait=.5)
    else:
        return op.round_retry('尚未适配的对话动作，未操作', wait=.5)
    op._dialogue_menu_opened = action.kind == 'menu'
    op._dialogue_pad_pending = dict(signature=signature, waits=0)
    return op.round_wait(f'手柄{text}，等待实际画面', wait=.5)
