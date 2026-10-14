"""Incremental JSON envelope decoding without a whole HTTP body/string copy.

The normalized API still owns complete result rows. A byte limit rejects the
entire response, never returns a truncated answer. Only the current token and a
64 KiB input chunk are buffered in addition to decoded objects.
"""
import codecs
import json
import re
import socket
import math
from contextlib import nullcontext
from xgap.backends.request_control import current_control

_SPECIAL=re.compile(r'["\\]')
def _pairs(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError('Duplicate backend JSON member')
        result[k]=v
    return result


def _constant(value):raise ValueError('Nonfinite backend JSON number')


def _float(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError('Nonfinite backend JSON number')
    return result


_FAST=json.JSONDecoder(object_pairs_hook=_pairs,parse_constant=_constant,parse_float=_float)
_DELIMITER=re.compile(r'[\s,\]}]')


class JsonStream:
    def __init__(self,stream,control=None):
        self.stream=stream;self.control=control;self.decoder=codecs.getincrementaldecoder('utf-8')()
        self.buffer='';self.position=0;self.eof=False;self.bytes=0;self.peak_buffer=0

    def more(self):
        if self.eof:return False
        if self.control:self.control.check()
        limit=self.control.max_response_bytes if self.control else None
        size=65536 if limit is None else min(65536,max(1,limit-self.bytes+1))
        raw=self.stream.read(size);self.bytes+=len(raw)
        if self.control:self.control.record_read(len(raw))
        if limit is not None and self.bytes>limit:raise ValueError('Backend response byte budget exceeded')
        if self.control:self.control.check()
        self.eof=not raw
        self.buffer=self.buffer[self.position:]+self.decoder.decode(raw,final=self.eof);self.position=0
        self.peak_buffer=max(self.peak_buffer,len(self.buffer))
        return bool(raw)

    def peek(self):
        while self.position==len(self.buffer) and not self.eof:self.more()
        return self.buffer[self.position:self.position+1]

    def whitespace(self):
        while self.peek() and self.buffer[self.position] in ' \t\r\n':self.position+=1

    def expect(self,char):
        self.whitespace()
        if self.peek()!=char:raise ValueError('Malformed backend JSON: expected '+char)
        self.position+=1

    def string(self):
        self.expect('"');parts=['"'];start=self.position
        while True:
            match=_SPECIAL.search(self.buffer,self.position)
            if match is None:
                parts.append(self.buffer[start:]);self.position=len(self.buffer)
                if not self.more():raise ValueError('Unterminated backend JSON string')
                start=0;continue
            self.position=match.start()+1
            if match.group()=='"':
                parts.append(self.buffer[start:self.position]);return json.loads(''.join(parts))
            # Escape and its following character stay in the JSON token.
            if self.position==len(self.buffer):
                parts.append(self.buffer[start:]);self.position=len(self.buffer)
                if not self.more():raise ValueError('Truncated backend JSON escape')
                start=0
            self.position+=1

    def value(self,path=(),depth=0):
        if depth>128:raise ValueError('Backend JSON nesting limit exceeded')
        self.whitespace();ch=self.peek()
        if ch in ('{','[') and path and path[-1]=='*':
            # C decoder for complete array items already in the bounded chunk.
            # An item crossing a chunk boundary uses the incremental path below.
            try:
                result,end=_FAST.raw_decode(self.buffer,self.position)
            except json.JSONDecodeError:pass
            except RecursionError as exc:raise ValueError('Backend JSON nesting limit exceeded') from exc
            else:
                stack=[(result,depth)]
                while stack:
                    value,level=stack.pop()
                    if level>128:raise ValueError('Backend JSON nesting limit exceeded')
                    if isinstance(value,dict):stack.extend((v,level+1) for v in value.values() if isinstance(v,(dict,list)))
                    elif isinstance(value,list):stack.extend((v,level+1) for v in value if isinstance(v,(dict,list)))
                self.position=end;return result
        if ch=='"':return self.string()
        if ch=='{':
            self.position+=1;result={};self.whitespace()
            if self.peek()=='}':self.position+=1;return result
            while True:
                key=self.string();self.expect(':')
                if key in result:raise ValueError('Duplicate backend JSON member')
                result[key]=self.value(path+(key,),depth+1);self.whitespace();ch=self.peek();self.position+=1
                if ch=='}':return result
                if ch!=',':raise ValueError('Malformed backend JSON object')
        if ch=='[':
            self.position+=1;result=[];self.whitespace()
            if self.peek()==']':self.position+=1;return result
            while True:
                result.append(self.value(path+('*',),depth+1));self.whitespace();ch=self.peek();self.position+=1
                if ch==']':return result
                if ch!=',':raise ValueError('Malformed backend JSON array')
        parts=[]
        while True:
            match=_DELIMITER.search(self.buffer,self.position)
            end=match.start() if match else len(self.buffer)
            parts.append(self.buffer[self.position:end]);self.position=end
            if match or self.eof:break
            self.more()
        raw=''.join(parts)
        if raw in ('NaN','Infinity','-Infinity'):raise ValueError('Nonfinite backend JSON number')
        return json.loads(raw,parse_float=_float,parse_constant=_constant)

    def read(self):
        result=self.value();self.whitespace()
        if self.peek():raise ValueError('Trailing backend JSON content')
        return result


def read_json(stream):
    control=current_control.get()
    # CPython HTTPResponse exposes its connected socket through the buffered
    # reader. Use shutdown (not close) to interrupt a blocked read without
    # contending on BufferedReader's lock. Other transports retain timeout drain.
    sock=getattr(getattr(getattr(stream,'fp',None),'raw',None),'_sock',None)
    def abort_read():
        if sock is None:return dict(transport_interrupted=False,backend_termination_confirmed=False)
        try:sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        return dict(transport_interrupted=True,backend_termination_confirmed=False)
    with control.cancellation(abort_read) if control is not None else nullcontext():
        result=JsonStream(stream,control).read()
        if control:control.check()
        return result
