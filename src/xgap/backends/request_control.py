"""Request-scoped cooperative cancellation and bounded transport admission.

Adapters may register a query-specific cancellation callback. No process-wide
kill, credential changes, or cancellation of other requests is permitted.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from threading import Event,Lock
import time

current_control=ContextVar('xgap_backend_request_control',default=None)


class RequestControl:
    def __init__(self,deadline=None,max_response_bytes=None):
        self.deadline=deadline;self.max_response_bytes=max_response_bytes
        self.cancelled=Event();self.lock=Lock();self.callbacks={};self.receipts=[];self.response_bytes=0

    def record_read(self,count):
        with self.lock:self.response_bytes+=count

    def check(self):
        if self.cancelled.is_set() or self.deadline is not None and time.perf_counter()>=self.deadline:
            raise TimeoutError('XGAP request cancelled or deadline exhausted')

    def timeout(self,default):
        self.check()
        return default if self.deadline is None else max(.001,min(default,self.deadline-time.perf_counter()))

    @contextmanager
    def cancellation(self,callback):
        """Callback must cancel only this invocation and return promptly."""
        key=object()
        with self.lock:
            cancelled=self.cancelled.is_set()
            if not cancelled:self.callbacks[key]=callback
        if cancelled:self._invoke(callback)
        try:self.check();yield
        finally:
            with self.lock:self.callbacks.pop(key,None)

    def _invoke(self,callback):
        try:
            evidence=callback()
            result=dict(status='requested',evidence=evidence)
        except Exception as exc:result=dict(status='failed',error_type=type(exc).__name__,error=str(exc))
        with self.lock:self.receipts.append(result)

    def cancel(self):
        with self.lock:
            self.cancelled.set();callbacks=list(self.callbacks.values());self.callbacks.clear()
        for callback in callbacks:self._invoke(callback)


def controlled_call(control,call,*args):
    token=current_control.set(control)
    try:return call(*args)
    finally:current_control.reset(token)


@contextmanager
def cancel_on_error(control):
    try:yield
    except BaseException:
        control.cancel()
        raise
