"""Opt-in, low-overhead CAD performance measurements; no user model data stored."""
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter


class PerformanceRecorder:
    def __init__(self, enabled=False):
        self.enabled=enabled
        self._lock=Lock()
        self._samples=defaultdict(list)

    def record(self, name, seconds):
        if not self.enabled:
            return
        with self._lock:
            self._samples[name].append(float(seconds)*1000)

    @contextmanager
    def measure(self, name):
        if not self.enabled:
            yield
            return
        started=perf_counter()
        try:
            yield
        finally:
            self.record(name,perf_counter()-started)

    def snapshot(self):
        with self._lock:
            result={}
            for name,values in sorted(self._samples.items()):
                ordered=sorted(values)
                n=len(ordered)
                result[name]={
                    "count":n,
                    "total_ms":round(sum(values),3),
                    "mean_ms":round(sum(values)/n,3),
                    "median_ms":round(ordered[n//2],3),
                    "p95_ms":round(ordered[min(n-1,int((n-1)*.95))],3),
                    "max_ms":round(ordered[-1],3)
                }
            return result

    def write(self,path):
        target=Path(path)
        target.parent.mkdir(parents=True,exist_ok=True)
        payload={"schema":1,"units":"milliseconds","stages":self.snapshot()}
        temp=target.with_name(target.name+".tmp")
        temp.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
        os.replace(temp,target)
        return target


def profiled(recorder,name):
    """Decorator for expensive GUI operations, with timing disabled by default."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            with recorder.measure(name):
                return fn(*args,**kwargs)
        return wrapped
    return decorate


_DEFAULT_RECORDER=None


def from_environment():
    global _DEFAULT_RECORDER
    if _DEFAULT_RECORDER is None:
        _DEFAULT_RECORDER=PerformanceRecorder(
            os.environ.get("ICR2_CAD_PROFILE","").strip()=="1")
    return _DEFAULT_RECORDER
