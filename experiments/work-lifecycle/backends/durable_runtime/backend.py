"""Stateless transport adapter; all lifecycle state lives in Restate."""
import hashlib
import json
import urllib.request


class Backend:
    def __init__(self, root):
        self.namespace = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]

    def command(self, request):
        key = self.namespace + "-" + hashlib.sha256(str(request.get("work_id", "")).encode()).hexdigest()[:24]
        url = f"http://127.0.0.1:18080/Assignment/{key}/command"
        call = urllib.request.Request(url, data=json.dumps(request).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(call, timeout=30) as result:
            return json.load(result)
