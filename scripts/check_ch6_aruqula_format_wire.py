"""No-model diagnostic of the original formatter's OpenAI-compatible request.

Run with the isolated author Python environment. A loopback server captures one
request and returns a synthetic fixture; this cannot measure method correctness.
"""
import argparse
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading


def check(author_source, input_logs, output, nonthinking=False):
    source, root = Path(author_source).resolve(), Path(output).resolve()
    if (subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            != '9a3982baca03d62f7250572e300b1e4ba47727cc'
            or subprocess.check_output(['git','diff','HEAD','--'],cwd=source)):
        raise ValueError('Author source changed')
    root.mkdir(parents=True, exist_ok=False)
    logs = Path(input_logs).read_bytes()
    records = [json.loads(line) for line in logs.splitlines()]
    input_text = [r['input'] for r in records if r['template_name']=='format_actions.prompt'][-1]
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            size = int(self.headers['Content-Length'])
            if not 0 < size < 65536: raise ValueError('Unexpected request size')
            requests.append(json.loads(self.rfile.read(size)))
            payload = dict(id='offline-fixture',object='chat.completion',created=0,
                model='qwen3.8-27b',choices=[dict(index=0,finish_reason='stop',
                message=dict(role='assistant',content=json.dumps(dict(thought='offline fixture',
                    action_name='stop',action_argument=''))))],
                usage=dict(prompt_tokens=0,completion_tokens=0,total_tokens=0))
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    receipt = dict(success=False,external_calls=0,model_calls=0,
        input_logs_sha256=hashlib.sha256(logs).hexdigest(),
        scope='offline wire diagnostic only; synthetic response, no provider or answer measurement')
    try:
        import yaml
        config = yaml.safe_load((source/'llm_config.yaml').read_text())
        config['prompt_dirs'] = [str(source/p) for p in config['prompt_dirs']]
        config['llm_endpoints'] = [dict(api_base=f'http://127.0.0.1:{server.server_port}/v1',
            api_key='XGAP_OFFLINE_DUMMY',engine_map={'xgap-qwen':'openai/qwen3.8-27b'})]
        (root/'llm_config.yaml').write_text(json.dumps(config));os.chdir(root)
        os.environ['OPENAI_API_KEY']=os.environ['XGAP_OFFLINE_DUMMY']='offline-placeholder'
        os.environ['NO_PROXY']=os.environ['no_proxy']='127.0.0.1,localhost,::1'
        from chainlite import llm_generation_chain
        if nonthinking:
            from run_chapter7_aruqula_worker import install_nonthinking_transport
            install_nonthinking_transport()
        from langchain.globals import set_llm_cache
        from langchain_community.cache import InMemoryCache
        # Fresh diagnostic cache avoids Redis; actual baseline keeps author Redis.
        set_llm_cache(InMemoryCache())
        chain = llm_generation_chain(template_file='format_actions.prompt',engine='xgap-qwen',
            max_tokens=700,keep_indentation=True,output_json=True)
        asyncio.run(chain.ainvoke({'input':input_text}))
        if len(requests)!=1: raise ValueError('Expected one loopback request')
        body = requests[0]
        (root/'request-body.json').write_text(json.dumps(body,indent=2))
        prompt = (source/'spinach_agent/prompts/format_actions.prompt').read_bytes()
        instruction = prompt.decode().split('# instruction\n',1)[1].split('# distillation instruction',1)[0].strip()
        receipt.update(original_prompt_sha256=hashlib.sha256(prompt).hexdigest(),
            system_instruction_unchanged=body['messages'][0]['content']==instruction,
            last_user_input_unchanged=body['messages'][-1]['content']==input_text,
            message_roles=[m['role'] for m in body['messages']],
            **{k:body.get(k) for k in ('response_format','temperature','top_p','max_tokens')})
        receipt['model_template_parameters']=body.get('chat_template_kwargs')
        receipt['success'] = (receipt['system_instruction_unchanged'] and receipt['last_user_input_unchanged']
            and receipt['response_format']=={'type':'json_object'} and receipt['max_tokens']==700
            and receipt['temperature']==0 and receipt['top_p']==0.9)
        if nonthinking:receipt['success'] &= receipt['model_template_parameters']=={'enable_thinking':False}
    finally:
        server.shutdown();server.server_close();thread.join()
        receipt.update(loopback_calls=len(requests),server_closed=not thread.is_alive())
        (root/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))
    return 0 if receipt['success'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('author-source','input-logs','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--nonthinking',action='store_true')
    raise SystemExit(check(**vars(p.parse_args())))
