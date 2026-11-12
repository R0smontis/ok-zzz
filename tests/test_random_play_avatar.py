"""影像店宣传员识别：有皮肤的代理人第二个头像模板 id 也必须参与匹配。

HEAD 版本在首个模板 id 未命中时就 return None，19 个双皮肤代理人只要有皮肤就选不中。
"""
from types import SimpleNamespace

import numpy as np

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResult
from zzz_od.application.random_play.random_play_app import RandomPlayApp


def build(matched: dict[str, MatchResult]):
    screen = np.zeros((1080, 1920, 3), np.uint8)
    seen: list[str] = []

    def match_one_by_feature(part, sub_dir, template_id):
        seen.append(template_id)
        return matched.get(template_id)

    area = SimpleNamespace(rect=Rect(0, 0, 300, 300), left_top=Point(100, 200))
    ctx = SimpleNamespace(
        screen_loader=SimpleNamespace(get_area=lambda app, key: area),
        tm=SimpleNamespace(match_one_by_feature=match_one_by_feature),
    )
    app = object.__new__(RandomPlayApp)
    app.ctx = ctx
    return app, screen, seen


def test_second_skin_template_is_tried_when_the_first_misses():
    app, screen, seen = build({'avatar_ellen_on_campus': MatchResult(1, 10, 20, 40, 40)})
    mr = app.get_pos_by_avatar(screen, '艾莲')  # 艾莲/安比等 19 个代理人有第二个皮肤模板
    assert seen == ['avatar_ellen', 'avatar_ellen_on_campus']
    assert mr is not None
    assert (mr.left_top.x, mr.left_top.y) == (110, 220)  # 头像坐标补上了列表区的偏移


def test_no_match_returns_none_after_trying_every_template():
    app, screen, seen = build({})
    assert app.get_pos_by_avatar(screen, '艾莲') is None
    assert seen == ['avatar_ellen', 'avatar_ellen_on_campus']


def test_unknown_agent_name_is_not_an_error():
    app, screen, seen = build({})
    assert app.get_pos_by_avatar(screen, '不存在的代理人') is None
    assert seen == []
