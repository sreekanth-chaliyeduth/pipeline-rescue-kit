#!/usr/bin/env python3
"""Small Jenkins API client for the local setup.

Standard library only. Credentials are read from .secrets/admin-password and
are never printed or written to evidence.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECRETS = os.path.join(ROOT, ".secrets")
BASE = os.environ.get("JENKINS_URL", "http://127.0.0.1:8080").rstrip("/")
USER = "admin"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def password():
    with open(os.path.join(SECRETS, "admin-password"), encoding="utf-8") as fh:
        value = fh.read().strip()
    if not value:
        raise RuntimeError("admin password file is empty")
    return value


def _auth_header():
    token = base64.b64encode(f"{USER}:{password()}".encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + token}


def request(path, method="GET", data=None, headers=None, timeout=30, auth=True,
            allow_redirects=True):
    url = BASE + path
    req = urllib.request.Request(url, data=data, method=method)
    if auth:
        for key, value in _auth_header().items():
            req.add_header(key, value)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    handlers = [] if allow_redirects else [NoRedirect()]
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def get_json(path):
    status, body, _ = request(path)
    if status != 200:
        raise RuntimeError(f"GET {path} returned {status}")
    return json.loads(body.decode("utf-8"))


def post(path):
    # Jenkins ties the CSRF crumb to the web session, so the crumb request and
    # the POST must share a cookie jar. Basic auth alone is not enough.
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    crumb_req = urllib.request.Request(BASE + "/crumbIssuer/api/json")
    for key, value in _auth_header().items():
        crumb_req.add_header(key, value)
    with opener.open(crumb_req, timeout=30) as resp:
        crumb = json.loads(resp.read().decode("utf-8"))

    req = urllib.request.Request(BASE + path, data=b"", method="POST")
    for key, value in _auth_header().items():
        req.add_header(key, value)
    req.add_header(crumb["crumbRequestField"], crumb["crumb"])
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise RuntimeError(f"POST {path} returned {exc.code}: {body[:300]!r}")


def post_form(path, fields):
    """POST a parameterized build with a CSRF crumb and session cookie."""
    import http.cookiejar
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    crumb_req = urllib.request.Request(BASE + "/crumbIssuer/api/json")
    for key, value in _auth_header().items():
        crumb_req.add_header(key, value)
    with opener.open(crumb_req, timeout=30) as resp:
        crumb = json.loads(resp.read().decode("utf-8"))

    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    for key, value in _auth_header().items():
        req.add_header(key, value)
    req.add_header(crumb["crumbRequestField"], crumb["crumb"])
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise RuntimeError(f"POST {path} returned {exc.code}: {body[:300]!r}")


def wait_controller(timeout=300):
    deadline = time.monotonic() + timeout
    last = "not ready"
    while time.monotonic() < deadline:
        try:
            status, _, _ = request("/login", auth=False, timeout=5)
            if status == 200:
                auth_status, _, _ = request("/api/json", timeout=5)
                if auth_status == 200:
                    return True
                last = f"login 200, authenticated api {auth_status}"
            else:
                last = f"login {status}"
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(3)
    raise RuntimeError(f"controller not ready after {timeout}s: {last}")


def wait_node(name, timeout=180):
    quoted = urllib.parse.quote(name, safe="")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body, _ = request(f"/computer/{quoted}/api/json", timeout=10)
        if status == 200:
            return json.loads(body.decode("utf-8"))
        time.sleep(2)
    raise RuntimeError(f"node {name} not created after {timeout}s")


def wait_agent_online(name, timeout=180):
    quoted = urllib.parse.quote(name, safe="")
    deadline = time.monotonic() + timeout
    last = "not created"
    while time.monotonic() < deadline:
        status, body, _ = request(f"/computer/{quoted}/api/json", timeout=10)
        if status == 200:
            node = json.loads(body.decode("utf-8"))
            if node.get("offline") is False:
                return node
            last = f"offline={node.get('offline')}"
        else:
            last = f"http {status}"
        time.sleep(2)
    raise RuntimeError(f"agent {name} not online after {timeout}s: {last}")


def fetch_agent_secret(name):
    quoted = urllib.parse.quote(name, safe="")
    wait_node(name)
    body = None
    for path in (f"/computer/{quoted}/slave-agent.jnlp",
                 f"/computer/{quoted}/jenkins-agent.jnlp"):
        status, payload, _ = request(path, timeout=15)
        if status == 200:
            body = payload.decode("utf-8", errors="replace")
            break
    if body is None:
        raise RuntimeError("Jenkins did not return a JNLP descriptor for the agent")

    candidates = re.findall(r"<argument>([0-9a-fA-F]{32,})</argument>", body)
    if not candidates:
        candidates = re.findall(r"<secret>([0-9a-fA-F]{32,})</secret>", body)
    if not candidates:
        raise RuntimeError("JNLP descriptor did not contain a hex agent secret")
    secret = max(candidates, key=len)

    target = os.path.join(SECRETS, "agent-secret")
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(secret)
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)
    return len(secret)


def trigger_and_wait(job, timeout=240, params=None):
    before = get_json(f"/job/{job}/api/json?tree=lastBuild[number]")
    before_number = (before.get("lastBuild") or {}).get("number", 0)
    if params:
        post_form(f"/job/{job}/buildWithParameters",
                  {k: str(v) for k, v in params.items()})
    else:
        post(f"/job/{job}/build")

    deadline = time.monotonic() + timeout
    last = "queued"
    while time.monotonic() < deadline:
        data = get_json(f"/job/{job}/api/json?tree=lastBuild[number,building,result]")
        last_build = data.get("lastBuild") or {}
        number = last_build.get("number", 0)
        if number > before_number and not last_build.get("building", False):
            build = get_json(
                f"/job/{job}/{number}/api/json"
                "?tree=number,result,building,duration,builtOn"
            )
            status, console, _ = request(f"/job/{job}/{number}/consoleText", timeout=30)
            if status != 200:
                raise RuntimeError(f"console log for {job} #{number} returned {status}")
            built_on = build.get("builtOn")
            if isinstance(built_on, dict):
                built_on = built_on.get("displayName") or built_on.get("name")
            return {
                "job": job,
                "number": number,
                "result": build.get("result"),
                "duration_ms": build.get("duration"),
                "built_on": built_on,
                "console": console.decode("utf-8", errors="replace"),
            }
        last = f"lastBuild={number} building={last_build.get('building')}"
        time.sleep(2)
    raise RuntimeError(f"build of {job} did not finish after {timeout}s: {last}")


def _arg(argv, flag, default=None):
    if flag in argv:
        index = argv.index(flag)
        if index + 1 < len(argv):
            return argv[index + 1]
    return default


def main(argv):
    if len(argv) < 2:
        print("usage: jenkins_api.py <wait-controller|wait-node|wait-agent-online|"
              "fetch-agent-secret|trigger|status> [--timeout N] [name]", file=sys.stderr)
        return 2
    command = argv[1]
    timeout = int(_arg(argv, "--timeout", "180"))
    try:
        if command == "wait-controller":
            wait_controller(timeout)
            print("controller ready")
        elif command == "wait-node":
            name = _arg(argv, "--name", "linux-agent")
            wait_node(name, timeout)
            print(f"node {name} exists")
        elif command == "wait-agent-online":
            name = _arg(argv, "--name", "linux-agent")
            wait_agent_online(name, timeout)
            print(f"agent {name} online")
        elif command == "fetch-agent-secret":
            name = _arg(argv, "--name", "linux-agent")
            length = fetch_agent_secret(name)
            print(f"agent secret written to .secrets/agent-secret ({length} chars)")
        elif command == "trigger":
            job = _arg(argv, "--job", "train-ticket")
            build = trigger_and_wait(job, timeout)
            print(json.dumps({k: build[k] for k in
                              ("job", "number", "result", "duration_ms", "built_on")}))
        elif command == "reload":
            deadline = time.monotonic() + timeout
            last = None
            while time.monotonic() < deadline:
                try:
                    status, _ = post("/reload")
                    time.sleep(5)
                    print(f"reload returned {status}")
                    break
                except RuntimeError as exc:
                    if "returned 503" not in str(exc):
                        raise
                    last = exc
                    time.sleep(3)
            else:
                raise RuntimeError(
                    f"reload not ready after {timeout}s: {last}")
        elif command == "status":
            print(json.dumps({
                "controller": get_json("/api/json?tree=numExecutors,useSecurity"),
                "node": get_json("/computer/linux-agent/api/json"
                                 "?tree=offline,numExecutors"),
                "jobs": get_json("/api/json?tree=jobs[name]"),
            }, indent=2))
        else:
            print(f"unknown command: {command}", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - CLI should print a clean failure
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
