from unittest.mock import patch

import cv2

from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.auto_battle_agent_context import TeamInfo
from zzz_od.game_data.agent import AgentEnum


def test_partial_party_reuses_observed_skin_before_scanning_full_catalogue(ctx):
    agent = AgentEnum.ROXY.value
    context = AutoBattleContext(ctx).agent_context
    context.team_info = TeamInfo(['洛克茜', None, None])
    context.team_info.agent_list[0].matched_template_id = 'roxy'
    candidates = context.get_possible_agent_list()
    image = cv2.cvtColor(cv2.imread('assets/template/battle/avatar_1_roxy/raw.png'), cv2.COLOR_BGR2RGB)
    with patch.object(ctx.tm, 'match_template', wraps=ctx.tm.match_template) as matcher:
        assert context._match_agent_in(image, True, candidates) == (agent, 'roxy')
    assert matcher.call_count == 1
    assert len(candidates) == len(AgentEnum)


def test_portrait_history_keeps_missing_backup_candidate_and_clears_next_battle(ctx):
    context = AutoBattleContext(ctx).agent_context
    agent = AgentEnum.ROXY.value
    context._known_portrait_templates[agent.agent_id] = (agent, 'roxy')
    context.team_info = TeamInfo(['克拉蕾', None, None])
    assert (agent, 'roxy') in context.get_possible_agent_list()
    context.init_battle_agent_context()
    assert (agent, 'roxy') not in context.get_possible_agent_list()
    assert (agent, None) in context.get_possible_agent_list()


def test_unmatched_new_portrait_still_reaches_full_catalogue(ctx):
    context = AutoBattleContext(ctx).agent_context
    context.team_info = TeamInfo(['克拉蕾', None, None])
    context.team_info.agent_list[0].matched_template_id = 'claret'
    image = cv2.cvtColor(cv2.imread('assets/template/battle/avatar_1_roxy/raw.png'), cv2.COLOR_BGR2RGB)
    assert context._match_agent_in(image, True, context.get_possible_agent_list())[0] == AgentEnum.ROXY.value
