"""矩阵行动主战队伍解析；不改写共享挑战模板。"""
from zzz_od.game_data.agent import AgentEnum


def resolve_agent_ids(values):
    if not isinstance(values, (list, tuple)) or len(values) > 3:
        raise ValueError('主战编队需要一至三个角色')
    aliases = {}
    for member in AgentEnum:
        agent = member.value
        aliases[agent.agent_id] = aliases[agent.agent_name] = agent.agent_id
    agents = []
    for value in values:
        if value in (None, '', 'unknown', '未选择'):
            continue
        if not isinstance(value, str) or value not in aliases:
            raise ValueError(f'无法识别主战角色：{value}')
        agent_id = aliases[value]
        if agent_id in agents:
            raise ValueError(f'主战角色不能重复：{value}')
        agents.append(agent_id)
    if not agents:
        raise ValueError('自定义编队至少需要选择一个主战角色')
    return agents


def custom_matrix_agents(config):
    if config.mission_name != '矩阵行动':
        return None
    if config.matrix_team_mode not in ('沿用挑战配置', '自定义编队'):
        raise ValueError('矩阵行动编队方式无效，请重新选择')
    if config.matrix_team_mode != '自定义编队':
        return None
    return resolve_agent_ids([config.matrix_agent_1, config.matrix_agent_2, config.matrix_agent_3])
