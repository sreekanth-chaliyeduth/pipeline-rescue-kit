#!/usr/bin/env python3
"""Current-stack verification for the six-job Jenkins setup.

Checks Docker isolation, Java 21 controller/agent runtime, JDK 8/17 and Maven
3.9.16 toolchains, the six JCasC jobs, shared-library wiring, plugin pins and
secret handling. Runs a no-change incremental Train-Ticket pipeline before and
after a real stack restart. Writes evidence under evidence/task-1.3a/verify by
default. Set PRK_VERIFY_EVID to another evidence/<task-id>/verify directory.
Refuses to replace an existing verification.json unless --overwrite is given.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jenkins_api as api  # noqa: E402

DEFAULT_EVID = os.path.join(ROOT, "evidence", "task-1.3a", "verify")
EVID = os.environ.get("PRK_VERIFY_EVID", DEFAULT_EVID)
if not os.path.isabs(EVID):
    EVID = os.path.join(ROOT, EVID)
EVID = os.path.normpath(EVID)
CONTROLLER = "prk-m1-controller"
AGENT = "prk-m1-agent"
JOBS = ["petclinic", "petclinic-baseline", "train-ticket", "train-ticket-baseline",
        "train-ticket-prgate", "train-ticket-prgate-baseline"]
MULTIBRANCH = "petclinic-pr"
JOB_CONFIG = {
    "train-ticket-baseline": {
        "path": "harness/pipelines/train-ticket/Jenkinsfile.baseline",
        "markers": ["FULL_SCOPE", "PRK_MAVEN_EXIT"],
        "params": ["FULL_SCOPE"],
        "library": False,
    },
    "train-ticket": {
        "path": "harness/pipelines/train-ticket/Jenkinsfile",
        "markers": ["INCREMENTAL", "PRK_SELECTION_MISSING", "PRK_SKIP_MAVEN"],
        "params": ["INCREMENTAL", "SOURCE_REPO", "SOURCE_COMMIT",
                   "REFERENCE_COMMIT", "REACTOR_THREADS"],
        "library": False,
    },
    "train-ticket-prgate": {
        "path": "harness/pipelines/train-ticket/Jenkinsfile.prgate",
        "markers": ["PRK_SOURCE_COMMIT", "SCOPE_MODULES", "prgate-summary.md"],
        "params": ["ENFORCE", "BASELINE", "SOURCE_REPO", "SOURCE_COMMIT",
                   "REFERENCE_COMMIT", "SCOPE_MODULES", "REPORT_MODULE",
                   "COVERAGE_THRESHOLD", "STATIC_NEW_ISSUE_THRESHOLD"],
        "library": True,
    },
    "train-ticket-prgate-baseline": {
        "path": "harness/pipelines/train-ticket/Jenkinsfile.prgate",
        "markers": ["PRK_SOURCE_COMMIT", "SCOPE_MODULES", "prgate-summary.md"],
        "params": ["BASELINE", "ENFORCE", "SOURCE_REPO", "SOURCE_COMMIT",
                   "REFERENCE_COMMIT", "SCOPE_MODULES", "REPORT_MODULE",
                   "COVERAGE_THRESHOLD", "STATIC_NEW_ISSUE_THRESHOLD"],
        "library": True,
    },
    "petclinic": {
        "path": "harness/pipelines/petclinic/Jenkinsfile.prgate",
        "markers": ["PRK_SOURCE_COMMIT", "petclinic-test-gap.md",
                    "prgate-summary.md"],
        "params": ["ENFORCE", "BASELINE", "SOURCE_REPO", "SOURCE_COMMIT",
                   "REFERENCE_COMMIT", "COVERAGE_THRESHOLD",
                   "STATIC_NEW_ISSUE_THRESHOLD"],
        "library": True,
    },
    "petclinic-baseline": {
        "path": "harness/pipelines/petclinic/Jenkinsfile.prgate",
        "markers": ["PRK_SOURCE_COMMIT", "petclinic-test-gap.md",
                    "prgate-summary.md"],
        "params": ["BASELINE", "ENFORCE", "SOURCE_REPO", "SOURCE_COMMIT",
                   "REFERENCE_COMMIT", "COVERAGE_THRESHOLD",
                   "STATIC_NEW_ISSUE_THRESHOLD"],
        "library": True,
    },
}
NO_CHANGE_PARAMS = {
    "INCREMENTAL": "true",
    "SOURCE_REPO": "/src/train-ticket",
    "SOURCE_COMMIT": "313886e99befb94be6cd45f085c98e0019f59829",
    "REFERENCE_COMMIT": "313886e99befb94be6cd45f085c98e0019f59829",
    "REACTOR_THREADS": "2",
}
PLUGINS = [
    "configuration-as-code", "job-dsl", "workflow-aggregator", "git",
    "junit", "jacoco", "coverage", "warnings-ng", "git-forensics",
    "maven-plugin", "pipeline-stage-view", "timestamper",
]

checks = []
builds = {}
details = {}


def add(name, ok, detail):
    checks.append({"check": name, "pass": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + ": " + str(detail))


def read_secret(name):
    path = os.path.join(ROOT, ".secrets", name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


ADMIN_PASSWORD = read_secret("admin-password")
AGENT_SECRET = read_secret("agent-secret")


def redact(text):
    for secret in (ADMIN_PASSWORD, AGENT_SECRET):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def run(cmd, timeout=300):
    import subprocess
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # subprocess.TimeoutExpired or OSError
        return 124, str(exc)


def docker(*args, timeout=120):
    return run(["docker", *args], timeout=timeout)


def inspect(name):
    rc, out = docker("inspect", name)
    if rc != 0:
        return None
    try:
        return json.loads(out)[0]
    except (json.JSONDecodeError, IndexError):
        return None


def save(path, text):
    os.makedirs(EVID, exist_ok=True)
    with open(os.path.join(EVID, path), "w", encoding="utf-8") as fh:
        fh.write(redact(text))


def dump_json(path, value):
    save(path, json.dumps(value, indent=2) + "\n")


def first_version_line(text):
    for line in text.splitlines():
        if "version" in line.lower():
            return line.strip()
    return text.strip().splitlines()[0] if text.strip() else "(no output)"


def plugin_pins():
    pins = {}
    with open(os.path.join(ROOT, "harness", "jenkins", "plugins.txt"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                name, version = line.split(":", 1)
                pins[name] = version
    return pins


def mounts(info):
    return info.get("Mounts", []) if info else []


def host_bindings(info):
    result = []
    for container_port, binds in ((info or {}).get("HostConfig", {})
                                  .get("PortBindings", {}) or {}).items():
        for bind in binds or []:
            result.append({
                "container_port": container_port,
                "host_ip": bind.get("HostIp"),
                "host_port": bind.get("HostPort"),
            })
    return result


def scan_secret(secret):
    if not secret:
        return []
    hits = []
    skip_dirs = {".git", ".secrets", "work", "target", "node_modules"}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            try:
                if os.path.getsize(path) > 2_000_000:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    if secret in fh.read():
                        hits.append(os.path.relpath(path, ROOT))
            except OSError:
                continue
    return hits


def initial_docker_checks():
    controller = inspect(CONTROLLER)
    agent = inspect(AGENT)
    details["controller_image"] = (controller or {}).get("Config", {}).get("Image")
    details["agent_image"] = (agent or {}).get("Config", {}).get("Image")
    details["controller_image_id"] = (controller or {}).get("Image")
    details["agent_image_id"] = (agent or {}).get("Image")
    details["controller_user"] = (controller or {}).get("Config", {}).get("User")
    details["agent_user"] = (agent or {}).get("Config", {}).get("User")

    add("controller_running", bool(controller and controller["State"]["Running"]),
        (controller or {}).get("State", {}).get("Status"))
    health = (controller or {}).get("State", {}).get("Health", {}).get("Status")
    add("controller_healthy", health == "healthy", health)
    add("agent_running", bool(agent and agent["State"]["Running"]),
        (agent or {}).get("State", {}).get("Status"))

    for name, container, info in (("controller", CONTROLLER, controller),
                                   ("agent", AGENT, agent)):
        priv = (info or {}).get("HostConfig", {}).get("Privileged")
        add(f"{name}_not_privileged", priv is False, f"Privileged={priv}")
        net_mode = (info or {}).get("HostConfig", {}).get("NetworkMode")
        add(f"{name}_not_host_network", net_mode != "host", str(net_mode))
        dests = [m.get("Destination", "") for m in mounts(info)]
        sources = [m.get("Source", "") for m in mounts(info)]
        socket_mount = [p for p in dests + sources if "docker.sock" in p]
        add(f"{name}_no_docker_socket_mount", not socket_mount,
            f"socket mounts={socket_mount or 'none'}")
        rc, out = docker("exec", container, "sh", "-c",
                         "test ! -S /var/run/docker.sock")
        add(f"{name}_no_docker_socket_in_container", rc == 0,
            "no /var/run/docker.sock" if rc == 0 else out.strip())
        rc, out = docker("exec", container, "sh", "-c", "command -v sudo || true")
        add(f"{name}_no_sudo", out.strip() == "", out.strip() or "sudo absent")

    c_binds = host_bindings(controller)
    a_binds = host_bindings(agent)
    details["controller_port_bindings"] = c_binds
    details["agent_port_bindings"] = a_binds
    add("controller_only_configured_localhost",
        len(c_binds) == 1
        and c_binds[0]["container_port"] == "8080/tcp"
        and c_binds[0]["host_ip"] == "127.0.0.1"
        and c_binds[0]["host_port"] == os.environ.get("JENKINS_PORT", "8080"),
        json.dumps(c_binds))
    add("agent_no_published_ports", not a_binds, json.dumps(a_binds))

    save("docker-security.txt", json.dumps({
        "controller": {
            "image": details["controller_image"],
            "image_id": details["controller_image_id"],
            "user": details["controller_user"],
            "privileged": (controller or {}).get("HostConfig", {}).get("Privileged"),
            "network_mode": (controller or {}).get("HostConfig", {}).get("NetworkMode"),
            "port_bindings": c_binds,
            "mounts": [{"type": m.get("Type"), "source": m.get("Source"),
                        "destination": m.get("Destination")} for m in mounts(controller)],
        },
        "agent": {
            "image": details["agent_image"],
            "image_id": details["agent_image_id"],
            "user": details["agent_user"],
            "privileged": (agent or {}).get("HostConfig", {}).get("Privileged"),
            "network_mode": (agent or {}).get("HostConfig", {}).get("NetworkMode"),
            "port_bindings": a_binds,
            "mounts": [{"type": m.get("Type"), "source": m.get("Source"),
                        "destination": m.get("Destination")} for m in mounts(agent)],
        },
    }, indent=2) + "\n")


def toolchain_checks():
    rc, out = docker("exec", CONTROLLER, "java", "-version")
    add("controller_java_21", rc == 0 and "21." in out, first_version_line(out))

    rc, out = docker("exec", CONTROLLER, "java", "-jar",
                     "/usr/share/jenkins/jenkins.war", "--version", timeout=120)
    details["jenkins_version"] = out.strip().splitlines()[-1] if out.strip() else ""
    add("jenkins_core_version", "2.580.2" in out, details["jenkins_version"])

    rc, out = docker("exec", AGENT, "java", "-version")
    add("agent_java_21", rc == 0 and "21." in out, first_version_line(out))
    rc, out = docker("exec", AGENT, "/opt/java/jdk8/bin/java", "-version")
    add("agent_jdk8", rc == 0 and "1.8.0" in out, first_version_line(out))
    rc, out = docker("exec", AGENT, "/opt/java/jdk17/bin/java", "-version")
    add("agent_jdk17", rc == 0 and "17." in out, first_version_line(out))
    rc, out = docker("exec", AGENT, "sh", "-c",
                     "JAVA_HOME=/opt/java/jdk17 /opt/maven/bin/mvn -v")
    add("agent_maven_3916_on_jdk17",
        rc == 0 and "Apache Maven 3.9.16" in out and "Java version: 17." in out,
        " / ".join(line for line in out.splitlines()
                   if line.startswith(("Apache Maven", "Java version"))))
    rc, out = docker("exec", AGENT, "sh", "-c",
                     "JAVA_HOME=/opt/java/jdk8 /opt/maven/bin/mvn -v")
    add("agent_maven_3916_on_jdk8",
        rc == 0 and "Apache Maven 3.9.16" in out and "Java version: 1.8.0" in out,
        " / ".join(line for line in out.splitlines()
                   if line.startswith(("Apache Maven", "Java version"))))


def jenkins_state_checks():
    state = api.get_json("/api/json?tree=numExecutors,useSecurity")
    add("controller_zero_executors", state.get("numExecutors") == 0,
        f"numExecutors={state.get('numExecutors')}")
    add("jenkins_security_enabled", state.get("useSecurity") is True,
        f"useSecurity={state.get('useSecurity')}")

    status, _, _ = api.request("/api/json", auth=False, allow_redirects=False)
    add("anonymous_api_denied", status in (401, 403), f"anonymous /api/json -> {status}")

    node = api.get_json("/computer/linux-agent/api/json"
                        "?tree=offline,numExecutors,assignedLabels[name]")
    add("agent_online", node.get("offline") is False, f"offline={node.get('offline')}")
    add("agent_two_executors", node.get("numExecutors") == 2,
        f"numExecutors={node.get('numExecutors')}")
    labels = sorted(label.get("name") for label in node.get("assignedLabels", []))
    details["agent_labels"] = labels
    add("agent_labels", all(label in labels
                            for label in ("linux", "amd64", "java8", "java17", "maven")),
        ",".join(labels))

    jobs = sorted(job["name"] for job in
                  api.get_json("/api/json?tree=jobs[name]").get("jobs", []))
    details["jobs"] = jobs
    add("existing_six_jobs_present", all(job in jobs for job in JOBS),
        ",".join(JOBS))
    add("multibranch_job_present", MULTIBRANCH in jobs, MULTIBRANCH)
    add("expected_job_count", len(jobs) == len(JOBS) + 1, f"{len(jobs)} jobs")

    for job, spec in JOB_CONFIG.items():
        status, body, _ = api.request(f"/job/{job}/config.xml")
        config = body.decode("utf-8", errors="replace")
        save(f"job-config-{job}.xml", config)
        missing_markers = [marker for marker in spec["markers"]
                           if marker not in config]
        add(f"job_{job}_current_pipeline",
            status == 200 and not missing_markers,
            f"{spec['path']} missing={missing_markers or 'none'}")
        missing_params = [param for param in spec["params"]
                          if f"<name>{param}</name>" not in config]
        add(f"job_{job}_parameters",
            status == 200 and not missing_params,
            f"missing={missing_params or 'none'}")
        if spec["library"]:
            add(f"job_{job}_shared_library",
                status == 200 and "@Library" in config and "prk@lib-v1.0.0" in config,
                "loads prk@lib-v1.0.0")

    status, body, _ = api.request(f"/job/{MULTIBRANCH}/config.xml")
    config = body.decode("utf-8", errors="replace")
    save(f"job-config-{MULTIBRANCH}.xml", config)
    add("multibranch_source_remote",
        status == 200 and "file:///src/pr-flow/petclinic-demo.git" in config,
        "file:///src/pr-flow/petclinic-demo.git")
    add("multibranch_script_path",
        status == 200 and "<scriptPath>examples/Jenkinsfile.multibranch</scriptPath>"
        in config, "examples/Jenkinsfile.multibranch")
    add("multibranch_branch_discovery",
        status == 200 and "BranchDiscoveryTrait" in config,
        "BranchDiscoveryTrait present")

    manager = api.get_json("/pluginManager/api/json?depth=1")
    dump_json("plugins.json", manager)
    installed = {p["shortName"]: p for p in manager.get("plugins", [])}
    missing = [p for p in PLUGINS
               if p not in installed
               or installed[p].get("enabled") is False
               or installed[p].get("active") is False]
    add("required_plugins_active", not missing,
        "missing/inactive=" + (",".join(missing) if missing else "none"))
    pins = plugin_pins()
    mismatched = [f"{p}:{pins[p]}!={installed.get(p, {}).get('version')}"
                  for p in pins
                  if installed.get(p, {}).get("version") != pins[p]]
    add("top_level_plugin_versions_pinned", not mismatched,
        ",".join(mismatched) if mismatched else f"{len(pins)} pinned plugins match")
    details["installed_plugin_count"] = len(installed)


def secret_checks():
    rc, status = run(["git", "status", "--porcelain"])
    add("no_secrets_in_git_status", ".secrets" not in status,
        "git status clean of .secrets" if ".secrets" not in status else "FAILED")
    ignored = True
    for name in ("admin-password", "agent-secret", "jenkins.env"):
        rc, out = run(["git", "check-ignore", "-q", f".secrets/{name}"])
        if rc != 0:
            ignored = False
    add("secrets_files_gitignored", ignored, ".secrets/{admin-password,agent-secret,jenkins.env}")

    modes = {}
    for name, expected in (("admin-password", 0o600), ("jenkins.env", 0o600),
                           ("agent-secret", 0o644)):
        path = os.path.join(ROOT, ".secrets", name)
        try:
            modes[name] = oct(os.stat(path).st_mode & 0o777)
        except OSError:
            modes[name] = "missing"
    add("secrets_file_permissions",
        all(modes[n] == oct(m) for n, m in
            (("admin-password", 0o600), ("jenkins.env", 0o600),
             ("agent-secret", 0o644))),
        json.dumps(modes))
    rc, out = docker("exec", AGENT, "sh", "-c",
                     "test -s /run/secrets/agent-secret && test -r /run/secrets/agent-secret")
    add("agent_secret_mounted_readable", rc == 0,
        "secret file is present and readable in the agent" if rc == 0 else out.strip())

    hits = sorted(set(scan_secret(ADMIN_PASSWORD) + scan_secret(AGENT_SECRET)))
    add("secret_values_not_in_project_files", not hits,
        "no matches" if not hits else ",".join(hits))


def pipeline_smoke_checks(label, build):
    if build is None:
        add(f"{label}_build", False, "build did not complete")
        return
    console = build["console"]
    save(f"pipeline-smoke-{label}.log", console)
    running_line = next((line.strip() for line in console.splitlines()
                         if "Running on linux-agent in " in line), "")
    add(f"{label}_build_result", build["result"] == "SUCCESS",
        f"#{build['number']} {build['result']} in {build['duration_ms']} ms")
    add(f"{label}_ran_on_agent",
        bool(running_line) and "SOURCE_COMMIT=313886e99befb94be6cd45f085c98e0019f59829" in console,
        running_line or build.get("built_on") or "no agent evidence")
    add(f"{label}_jdk8_visible",
        'openjdk version "1.8.0' in console,
        "JDK 8 version printed by the real pipeline")
    add(f"{label}_maven_visible",
        "Apache Maven 3.9.16" in console and "Java version: 1.8.0" in console,
        "Maven 3.9.16 on JDK 8 printed")
    add(f"{label}_incremental_no_change",
        "PRK_MODE=none" in console and "PRK_SKIP_MAVEN" in console
        and "PRK_MAVEN_COMMAND" not in console,
        "no-change selector skipped Maven")
    builds[label] = {
        "number": build["number"],
        "result": build["result"],
        "duration_ms": build["duration_ms"],
        "built_on": build.get("built_on"),
        "agent_line": running_line,
        "params": NO_CHANGE_PARAMS,
        "log": os.path.relpath(os.path.join(EVID, f"pipeline-smoke-{label}.log"), ROOT),
    }


def pipeline_smoke():
    try:
        build = api.trigger_and_wait("train-ticket", timeout=300,
                                     params=NO_CHANGE_PARAMS)
    except Exception as exc:  # noqa: BLE001
        build = None
        add("pipeline_smoke_trigger", False, str(exc))
    pipeline_smoke_checks("1", build)


def restart_checks():
    started = time.time()
    rc, out = run(["make", "down"], timeout=180)
    add("make_down", rc == 0, "containers removed" if rc == 0 else out.strip()[-300:])
    rc, out = run(["make", "up"], timeout=900)
    save("restart-up.log", out)
    add("make_up_after_down", rc == 0,
        f"restart took {int(time.time() - started)} s" if rc == 0 else out.strip()[-300:])
    details["restart_seconds"] = int(time.time() - started)

    try:
        api.wait_controller(120)
        api.wait_agent_online("linux-agent", 120)
        state = api.get_json("/api/json?tree=numExecutors")
        jobs = sorted(job["name"] for job in
                      api.get_json("/api/json?tree=jobs[name]").get("jobs", []))
        add("restart_controller_ready", True, "controller and agent ready")
        add("restart_zero_executors", state.get("numExecutors") == 0,
            f"numExecutors={state.get('numExecutors')}")
        add("restart_six_jobs", all(job in jobs for job in JOBS), ",".join(JOBS))
        add("restart_multibranch_job", MULTIBRANCH in jobs, MULTIBRANCH)
    except Exception as exc:  # noqa: BLE001
        add("restart_controller_ready", False, str(exc))
        return

    try:
        build = api.trigger_and_wait("train-ticket", timeout=300,
                                     params=NO_CHANGE_PARAMS)
    except Exception as exc:  # noqa: BLE001
        build = None
        add("restart_pipeline_smoke_trigger", False, str(exc))
    pipeline_smoke_checks("2", build)


def write_evidence():
    os.makedirs(EVID, exist_ok=True)
    dump_json("verification.json", {
        "milestone": "current-stack verification",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": checks,
        "passed": sum(1 for c in checks if c["pass"]),
        "failed": sum(1 for c in checks if not c["pass"]),
        "builds": builds,
        "details": details,
    })
    rc, ps = docker("compose", "-f", os.path.join(ROOT, "harness", "docker-compose.yml"), "ps")
    save("compose-ps.txt", ps)
    rc, out = docker("logs", "--timestamps", CONTROLLER)
    save("controller.log", out)
    rc, out = docker("logs", "--timestamps", AGENT)
    save("agent.log", out)
    env_lines = [
        "M1 environment snapshot",
        "date UTC: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    ]
    for cmd in (
        ["docker", "--version"],
        ["docker", "info", "--format",
         "CPUs={{.NCPU}} MemTotal={{.MemTotal}} Arch={{.Architecture}}"],
        ["docker", "image", "inspect", "jenkins/jenkins:lts-jdk21",
         "--format", "{{index .RepoDigests 0}}"],
        ["docker", "image", "inspect", "jenkins/inbound-agent:jdk21",
         "--format", "{{index .RepoDigests 0}}"],
        ["docker", "image", "inspect", "eclipse-temurin:8-jdk",
         "--format", "{{index .RepoDigests 0}}"],
        ["docker", "image", "inspect", "eclipse-temurin:17-jdk",
         "--format", "{{index .RepoDigests 0}}"],
        ["docker", "image", "inspect", "maven:3.9-eclipse-temurin-21",
         "--format", "{{index .RepoDigests 0}}"],
        ["docker", "image", "inspect", "prk-m1-controller:local", "--format", "{{.Id}}"],
        ["docker", "image", "inspect", "prk-m1-agent:local", "--format", "{{.Id}}"],
    ):
        rc, out = run(cmd)
        env_lines.append(f"$ {' '.join(cmd)}")
        env_lines.append(out.strip())
    save("environment.txt", "\n".join(env_lines) + "\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify the local Jenkins stack and write evidence.")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="replace an existing verification.json in the evidence directory")
    return parser.parse_args(argv)


def overwrite_refusal(target, overwrite):
    if os.path.exists(target) and not overwrite:
        return ("refusing to overwrite existing evidence: "
                + os.path.relpath(target, ROOT) + "\n"
                + "rerun with --overwrite to replace it intentionally")
    return None


def historical_evidence_changes(root=ROOT):
    """Return tracked historical evidence paths that differ from HEAD."""
    proc = subprocess.run(
        ["git", "-C", root, "diff", "--name-only", "HEAD", "--",
         ":(glob)evidence/M[0-9]*/**"],
        text=True, capture_output=True)
    if proc.returncode != 0:
        return [], (proc.stderr.strip() or proc.stdout.strip()
                    or "git diff exited " + str(proc.returncode))
    return [line for line in proc.stdout.splitlines() if line.strip()], None


def main(argv=None):
    args = parse_args(argv)
    target = os.path.join(EVID, "verification.json")
    refusal = overwrite_refusal(target, args.overwrite)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    changes, err = historical_evidence_changes()
    if err:
        print("cannot check historical evidence: " + err, file=sys.stderr)
        return 3
    if changes:
        print("historical evidence differs from HEAD:", file=sys.stderr)
        for path in changes:
            print("  " + path, file=sys.stderr)
        return 3
    print("historical evidence matches HEAD")
    os.makedirs(EVID, exist_ok=True)
    print("current-stack verification starting")
    print("evidence: " + os.path.relpath(EVID, ROOT))
    initial_docker_checks()
    toolchain_checks()
    try:
        jenkins_state_checks()
    except Exception as exc:  # noqa: BLE001
        add("jenkins_api_available", False, str(exc))
    secret_checks()
    pipeline_smoke()
    restart_checks()
    write_evidence()

    failed = [c for c in checks if not c["pass"]]
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    print("evidence: " + os.path.relpath(os.path.join(EVID, "verification.json"), ROOT))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
