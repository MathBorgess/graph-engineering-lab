"""Offline native contracts: real LangChain clients, simulated provider responses."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch
import httpx
try:
    import httpx2  # Current Anthropic SDK transport.
except ImportError:
    import httpx as httpx2  # Earlier SDK versions.
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from proxy import codex, claude
from proxy.client import create_model

@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b

def sse(*events):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events))

def completed(output):
    return {"id":"resp_1", "object":"response", "created_at":1, "status":"completed", "model":"gpt-6.1-sol", "output":output, "usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}

def message(content):
    return {"id":"msg_1","type":"message","role":"assistant","model":"claude-sonnet-4-6","content":content,"stop_reason":"tool_use" if content[0]['type']=='tool_use' else 'end_turn',"stop_sequence":None,"usage":{"input_tokens":3,"output_tokens":2}}

class NativeContracts(unittest.TestCase):
    def model(self, provider, upstream):
        stack = ExitStack()
        self.addCleanup(stack.close)
        module = codex if provider == 'codex' else claude
        if provider == 'codex':
            stack.enter_context(patch.object(codex.CodexAuth,'get_credentials',return_value=('chatgpt','fake','account',None)))
        else:
            stack.enter_context(patch.object(claude.ClaudeAuth,'get_token',return_value='fake'))
        factory = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(upstream),**kw)
        frontend = stack.enter_context(TestClient(module.create_app(factory)))
        lib = httpx if provider == 'codex' else httpx2
        def forward(request):
            response = frontend.post(request.url.path,content=request.content,headers=dict(request.headers))
            return lib.Response(response.status_code,content=response.content,headers=dict(response.headers))
        client = stack.enter_context(lib.Client(transport=lib.MockTransport(forward)))
        if provider == 'codex':
            return create_model(provider,'gpt-6.1-sol',base_url='http://proxy.test/v1',http_client=client,max_retries=0)
        stack.enter_context(patch('langchain_anthropic.chat_models._get_default_httpx_client',return_value=client))
        return create_model(provider,'claude-sonnet-4-6',base_url='http://proxy.test',max_retries=0)

    def test_codex_tool_round_trip(self):
        requests=[]
        def upstream(request):
            body=json.loads(request.content); requests.append(body)
            self.assertTrue(body['stream']); self.assertFalse(body['store'])
            if len(requests)==1:
                self.assertEqual(body['tools'][0]['name'],'add')
                self.assertEqual(body['tool_choice'],'required')
                output=[{"type":"function_call","id":"fc_add","status":"completed","call_id":"call_add","name":"add","arguments":'{"a":2,"b":3}'}]
            else:
                result=body['input'][-1]
                self.assertEqual(result['type'],'function_call_output')
                self.assertEqual(result['call_id'],'call_add'); self.assertEqual(result['output'],'5')
                output=[{"type":"message","id":"msg_1","role":"assistant","status":"completed","content":[{"type":"output_text","text":"5","annotations":[]}]}]
            return sse({'type':'response.completed','response':completed(output)})
        model=self.model('codex',upstream).bind_tools([add],tool_choice='required')
        messages=[HumanMessage(content='Add 2 and 3')]
        call=model.invoke(messages)
        self.assertEqual(call.tool_calls[0]['args'],{'a':2,'b':3})
        final=model.invoke([*messages,call,add.invoke(call.tool_calls[0])])
        self.assertIn('5',str(final.content))

    def test_claude_tool_round_trip(self):
        requests=[]
        def upstream(request):
            body=json.loads(request.content); requests.append(body)
            if len(requests)==1:
                self.assertEqual(body['tools'][0]['input_schema']['properties']['a']['type'],'integer')
                self.assertEqual(body['tool_choice'],{'type':'any'})
                content=[{'type':'tool_use','id':'toolu_add','name':'add','input':{'a':2,'b':3}}]
            else:
                result=body['messages'][-1]['content'][0]
                self.assertEqual(result['type'],'tool_result'); self.assertEqual(result['tool_use_id'],'toolu_add'); self.assertEqual(result['content'],'5')
                content=[{'type':'text','text':'5'}]
            return httpx.Response(200,json=message(content))
        model=self.model('claude',upstream).bind_tools([add],tool_choice='any')
        messages=[HumanMessage(content='Add 2 and 3')]
        call=model.invoke(messages)
        self.assertEqual(call.tool_calls[0]['args'],{'a':2,'b':3})
        self.assertEqual(model.invoke([*messages,call,add.invoke(call.tool_calls[0])]).content,'5')

    def test_claude_stream_arguments(self):
        def upstream(request):
            return sse(
                {'type':'message_start','message':{**message([{'type':'text','text':''}]),'content':[]}},
                {'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'toolu_add','name':'add','input':{}}},
                {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':'{"a":2,'}},
                {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':'"b":3}'}},
                {'type':'content_block_stop','index':0},
                {'type':'message_delta','delta':{'stop_reason':'tool_use','stop_sequence':None},'usage':{'output_tokens':2}},
                {'type':'message_stop'})
        chunks=list(self.model('claude',upstream).bind_tools([add]).stream('Add'))
        merged=chunks[0]
        for chunk in chunks[1:]: merged+=chunk
        self.assertEqual(merged.tool_calls[0]['args'],{'a':2,'b':3})

    def test_codex_stream_arguments(self):
        item={'type':'function_call','id':'fc_add','status':'in_progress','call_id':'call_add','name':'add','arguments':''}
        def upstream(request):
            return sse(
                {'type':'response.output_item.added','output_index':0,'item':item,'sequence_number':1},
                {'type':'response.function_call_arguments.delta','output_index':0,'item_id':'fc_add','delta':'{"a":2,','sequence_number':2},
                {'type':'response.function_call_arguments.delta','output_index':0,'item_id':'fc_add','delta':'"b":3}','sequence_number':3},
                {'type':'response.completed','response':completed([{**item,'status':'completed','arguments':'{"a":2,"b":3}'}]),'sequence_number':4})
        chunks=list(self.model('codex',upstream).bind_tools([add]).stream('Add'))
        merged=chunks[0]
        for chunk in chunks[1:]: merged+=chunk
        self.assertEqual(merged.tool_calls[0]['args'],{'a':2,'b':3})
        self.assertEqual(merged.tool_calls[0]['id'],'call_add')

    def test_codex_incomplete_is_error(self):
        from openai import APIStatusError
        model=self.model('codex',lambda request:sse({'type':'response.created','response':completed([])}))
        with self.assertRaises(APIStatusError) as caught: model.invoke('Hello')
        self.assertEqual(caught.exception.status_code,502)

if __name__ == '__main__': unittest.main()
