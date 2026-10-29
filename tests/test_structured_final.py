from test_native_tools import agent_with_api, reply


def test_reserves_budget_and_retries_invalid_structured_answer(monkeypatch,tmp_path):
 agent,requests=agent_with_api(monkeypatch,tmp_path,[
  reply('search','{"query":["a"]}'),
  reply(content='broken',finish='stop'),
  reply(content='{"answer":"42"}',finish='stop')],max_rounds=4)
 agent.custom_call_tool=lambda *_:'evidence'
 result=agent._run({'item':{'question':'q','answer':'42'}},'test-model')
 assert result['prediction']=='42'
 assert result['messages'][-1]['content']=='<answer>42</answer>'
 assert [r['tool_choice'] for r in requests]==['auto','none','none']
 assert requests[1]['response_format']['json_schema']['strict'] is True
 assert result['policy_call_counts']=={'research':1,'final':1,'correction':1,'http_attempts':3,'http_retries':0}

def test_budget_one_finalizes_without_research(monkeypatch,tmp_path):
 agent,requests=agent_with_api(monkeypatch,tmp_path,[reply(content='{"answer":"Unknown"}',finish='stop')],max_rounds=1)
 result=agent._run({'item':{'question':'q','answer':'x'}},'test-model')
 assert result['prediction']=='Unknown' and len(requests)==1
 assert requests[0]['tool_choice']=='none'
