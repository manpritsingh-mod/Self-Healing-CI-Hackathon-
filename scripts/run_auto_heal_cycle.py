#!/usr/bin/env python3
"""
End-to-end demo automation for Jenkins -> Heal API -> Slack -> PR -> rerun.

This script:
1. Upserts the Jenkins demo job from the local Jenkinsfile.
2. Creates or refreshes a demo broken branch in Python_Test.
3. Triggers the Jenkins pipeline against that broken branch.
4. Polls the healing API result from the build artifact.
5. Reads the last Slack payload sent by the engine.
6. If confidence >= threshold, creates an AI fix branch, opens a PR, and reruns Jenkins.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.parse
import urllib.request
import xml.sax.saxutils
from http.cookiejar import CookieJar
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JENKINSFILE_PATH = ROOT / "jenkins-config" / "jobs" / "Jenkinsfile-python-test-failure"


def run(cmd: list[str], cwd: Path | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        stdout = result.stdout.strip() if result.stdout else ""
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{stderr or stdout}")
    return result.stdout if capture else ""


def get_github_auth() -> tuple[str, str]:
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git credential fill failed")
    raw = result.stdout
    username = ""
    password = ""
    for line in raw.splitlines():
        if line.startswith("username="):
            username = line.split("=", 1)[1]
        elif line.startswith("password="):
            password = line.split("=", 1)[1]
    if not username or not password:
        raise RuntimeError("GitHub credentials were not returned by git credential manager")
    return username, password


class HttpClient:
    def __init__(self):
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        req = urllib.request.Request(url=url, data=body, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with self.opener.open(req, timeout=60) as response:
                return response.status, response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers.items())

    def json(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        payload: dict | list | None = None,
    ) -> tuple[int, dict]:
        body = None
        merged_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            merged_headers["Content-Type"] = "application/json"
        status, raw, _ = self.request(url, method=method, headers=merged_headers, body=body)
        data = json.loads(raw.decode("utf-8")) if raw else {}
        return status, data


class JenkinsClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.http = HttpClient()

    def crumb_headers(self) -> dict[str, str]:
        status, data = self.http.json(f"{self.base_url}/crumbIssuer/api/json")
        if status != 200:
            raise RuntimeError(f"Failed to get Jenkins crumb: {status} {data}")
        return {data["crumbRequestField"]: data["crumb"]}

    def upsert_pipeline_job(self, job_name: str, jenkinsfile_text: str) -> None:
        escaped = xml.sax.saxutils.escape(jenkinsfile_text)
        config_xml = textwrap.dedent(
            f"""\
            <flow-definition plugin="workflow-job@1571.vb_423c255d6d9">
              <actions/>
              <description>Automated Jenkins to heal to PR demo job.</description>
              <keepDependencies>false</keepDependencies>
              <properties>
                <hudson.model.ParametersDefinitionProperty>
                  <parameterDefinitions>
                    <hudson.model.StringParameterDefinition>
                      <name>REPO_BRANCH</name>
                      <description>Git branch to build from Python_Test</description>
                      <defaultValue>master</defaultValue>
                      <trim>true</trim>
                    </hudson.model.StringParameterDefinition>
                    <hudson.model.BooleanParameterDefinition>
                      <name>SIMULATE_FAILURE</name>
                      <description>Create a temporary failing pytest test inside the workspace</description>
                      <defaultValue>false</defaultValue>
                    </hudson.model.BooleanParameterDefinition>
                    <hudson.model.BooleanParameterDefinition>
                      <name>AUTO_HEAL_ON_FAILURE</name>
                      <description>Call the healing API after a failed build</description>
                      <defaultValue>true</defaultValue>
                    </hudson.model.BooleanParameterDefinition>
                  </parameterDefinitions>
                </hudson.model.ParametersDefinitionProperty>
              </properties>
              <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps@4258.v55f7f1691526">
                <script>{escaped}</script>
                <sandbox>true</sandbox>
              </definition>
              <triggers/>
              <disabled>false</disabled>
            </flow-definition>
            """
        ).lstrip().encode("utf-8")
        encoded_name = urllib.parse.quote(job_name, safe="")
        headers = {"Content-Type": "application/xml", **self.crumb_headers()}
        status, _, _ = self.http.request(f"{self.base_url}/job/{encoded_name}/api/json")
        if status == 200:
            update_url = f"{self.base_url}/job/{encoded_name}/config.xml"
            status, raw, _ = self.http.request(update_url, method="POST", headers=headers, body=config_xml)
        else:
            create_url = f"{self.base_url}/createItem?name={urllib.parse.quote(job_name)}"
            status, raw, _ = self.http.request(create_url, method="POST", headers=headers, body=config_xml)
        if status not in (200, 201):
            raise RuntimeError(f"Failed to upsert Jenkins job: {status} {raw.decode('utf-8', 'ignore')}")

    def trigger_build(self, job_name: str, params: dict[str, str]) -> int:
        encoded_name = urllib.parse.quote(job_name, safe="")
        query = urllib.parse.urlencode(params)
        headers = self.crumb_headers()
        status, _, resp_headers = self.http.request(
            f"{self.base_url}/job/{encoded_name}/buildWithParameters?{query}",
            method="POST",
            headers=headers,
        )
        if status != 201:
            raise RuntimeError(f"Failed to trigger Jenkins build: {status}")
        queue_url = resp_headers.get("Location")
        if not queue_url:
            raise RuntimeError("Jenkins did not return a queue location")
        for _ in range(90):
            status, data = self.http.json(f"{queue_url}api/json")
            if status != 200:
                time.sleep(2)
                continue
            executable = data.get("executable")
            if executable and "number" in executable:
                return int(executable["number"])
            time.sleep(2)
        raise RuntimeError("Timed out waiting for Jenkins queue item to resolve")

    def wait_for_build(self, job_name: str, build_number: int, timeout_seconds: int = 900) -> dict:
        encoded_name = urllib.parse.quote(job_name, safe="")
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            status, data = self.http.json(f"{self.base_url}/job/{encoded_name}/{build_number}/api/json")
            if status == 200 and not data.get("building"):
                return data
            time.sleep(5)
        raise RuntimeError(f"Timed out waiting for Jenkins build #{build_number}")

    def get_console(self, job_name: str, build_number: int) -> str:
        encoded_name = urllib.parse.quote(job_name, safe="")
        status, raw, _ = self.http.request(
            f"{self.base_url}/job/{encoded_name}/{build_number}/consoleText"
        )
        if status != 200:
            raise RuntimeError(f"Failed to fetch console log for build #{build_number}")
        return raw.decode("utf-8", "replace")

    def get_artifact_json(self, job_name: str, build_number: int, artifact_name: str) -> dict:
        encoded_name = urllib.parse.quote(job_name, safe="")
        status, raw, _ = self.http.request(
            f"{self.base_url}/job/{encoded_name}/{build_number}/artifact/{artifact_name}"
        )
        if status != 200:
            raise RuntimeError(
                f"Failed to fetch Jenkins artifact {artifact_name} from build #{build_number}: {status}"
            )
        return json.loads(raw.decode("utf-8"))


class GitHubClient:
    def __init__(self, owner: str, repo: str):
        username, password = get_github_auth()
        pair = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
        self.headers = {
            "Authorization": f"Basic {pair}",
            "User-Agent": "codex-auto-heal-demo",
            "Accept": "application/vnd.github+json",
        }
        self.owner = owner
        self.repo = repo
        self.http = HttpClient()

    def create_pull_request(self, head: str, base: str, title: str, body: str) -> dict:
        status, data = self.http.json(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls",
            method="POST",
            headers=self.headers,
            payload={"title": title, "head": head, "base": base, "body": body},
        )
        if status not in (200, 201):
            raise RuntimeError(f"Failed to create PR: {status} {data}")
        return data


def write_demo_failure_test(repo_dir: Path) -> None:
    target = repo_dir / "tests" / "test_ci_demo_broken.py"
    target.write_text(
        textwrap.dedent(
            """\
            from src.calculator.calculator import Calculator


            def test_codex_demo_broken_assertion():
                result = Calculator().add(2, 2)
                assert result == 5
            """
        ),
        encoding="utf-8",
    )


def prepare_demo_branch(repo_url: str, branch_name: str, base_branch: str) -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="codex-demo-broken-"))
    try:
        run(["git", "clone", repo_url, str(temp_dir)], capture=True)
        run(["git", "checkout", base_branch], cwd=temp_dir)
        run(["git", "checkout", "-B", branch_name], cwd=temp_dir)
        write_demo_failure_test(temp_dir)
        run(["git", "add", "tests/test_ci_demo_broken.py"], cwd=temp_dir)
        if run(["git", "status", "--porcelain"], cwd=temp_dir).strip():
            run(
                ["git", "commit", "-m", "Add intentional pytest assertion failure for auto-heal demo"],
                cwd=temp_dir,
            )
        run(["git", "push", "-u", "origin", branch_name, "--force"], cwd=temp_dir, capture=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def create_fix_branch(
    repo_url: str,
    source_branch: str,
    target_branch: str,
    affected_file: str,
    affected_line: int,
    fix_code: str,
) -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="codex-ai-fix-"))
    try:
        run(["git", "clone", repo_url, str(temp_dir)], capture=True)
        run(["git", "checkout", source_branch], cwd=temp_dir)
        run(["git", "checkout", "-B", target_branch], cwd=temp_dir)
        file_path = temp_dir / affected_file
        if not file_path.exists():
            raise RuntimeError(f"Cannot apply fix; file not found: {affected_file}")
        lines = file_path.read_text(encoding="utf-8").splitlines()
        if affected_line < 1 or affected_line > len(lines):
            raise RuntimeError(
                f"Cannot apply fix; line {affected_line} is outside {affected_file}"
            )
        current_line = lines[affected_line - 1]
        indentation = current_line[: len(current_line) - len(current_line.lstrip())]
        lines[affected_line - 1] = indentation + fix_code.strip()
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run(["git", "add", affected_file], cwd=temp_dir)
        if run(["git", "status", "--porcelain"], cwd=temp_dir).strip():
            run(
                ["git", "commit", "-m", f"Apply AI fix for {Path(affected_file).name}:{affected_line}"],
                cwd=temp_dir,
            )
        run(["git", "push", "-u", "origin", target_branch, "--force"], cwd=temp_dir, capture=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def poll_healing_result(engine_url: str, healing_id: str, timeout_seconds: int = 300) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status, data = HttpClient().json(f"{engine_url.rstrip('/')}/api/heal/{healing_id}/result")
        if status != 200:
            time.sleep(3)
            continue
        if data.get("status") in ("done", "error"):
            return data
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for healing result {healing_id}")


def get_last_slack(engine_url: str) -> dict:
    status, data = HttpClient().json(f"{engine_url.rstrip('/')}/api/slack/last")
    if status != 200:
        raise RuntimeError(f"Failed to fetch last Slack payload: {status}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the auto-heal demo cycle.")
    parser.add_argument("--jenkins-url", default="http://localhost:9080")
    parser.add_argument("--engine-url", default="http://localhost:5000")
    parser.add_argument("--repo-url", default="https://github.com/manpritsingh-mod/Python_Test.git")
    parser.add_argument("--repo-owner", default="manpritsingh-mod")
    parser.add_argument("--repo-name", default="Python_Test")
    parser.add_argument("--job-name", default="Python-Test-Healing-Demo")
    parser.add_argument("--base-branch", default="master")
    parser.add_argument("--broken-branch", default="codex/demo-broken-assertion")
    args = parser.parse_args()

    jenkins = JenkinsClient(args.jenkins_url)
    github = GitHubClient(args.repo_owner, args.repo_name)

    jenkinsfile_text = JENKINSFILE_PATH.read_text(encoding="utf-8")
    jenkins.upsert_pipeline_job(args.job_name, jenkinsfile_text)
    print(f"Upserted Jenkins job: {args.job_name}")

    prepare_demo_branch(args.repo_url, args.broken_branch, args.base_branch)
    print(f"Prepared broken branch: {args.broken_branch}")

    build_number = jenkins.trigger_build(
        args.job_name,
        {
            "REPO_BRANCH": args.broken_branch,
            "SIMULATE_FAILURE": "false",
            "AUTO_HEAL_ON_FAILURE": "true",
        },
    )
    print(f"Triggered failing build: #{build_number}")

    build = jenkins.wait_for_build(args.job_name, build_number)
    print(f"Build #{build_number} result: {build.get('result')}")
    if build.get("result") != "FAILURE":
        raise RuntimeError("Expected the broken branch build to fail")

    heal_response = jenkins.get_artifact_json(args.job_name, build_number, "healing-response.json")
    healing_id = heal_response["healing_id"]
    print(f"Healing request queued: {healing_id}")

    healing_result = poll_healing_result(args.engine_url, healing_id)
    if healing_result.get("status") != "done":
        raise RuntimeError(f"Healing did not complete successfully: {healing_result}")

    result = healing_result["result"]
    print(json.dumps(result, indent=2))

    slack_info = get_last_slack(args.engine_url)
    print("Last Slack notification:")
    print(json.dumps(slack_info, indent=2))

    slack_incident = slack_info.get("incident") or {}
    slack_confidence = slack_incident.get("confidence")
    confidence = int(slack_confidence if slack_confidence is not None else (result.get("final_confidence") or 0))
    if slack_info.get("status") != "sent":
        raise RuntimeError(f"Slack notification was not sent successfully: {slack_info}")
    if confidence < 90:
        print(f"Confidence {confidence}% is below threshold. No PR created.")
        return 0

    affected_file = result.get("affected_file")
    affected_line = result.get("affected_line")
    fix_code = result.get("fix_code")
    if not affected_file or not affected_line or not fix_code:
        raise RuntimeError(
            "Healing result is missing affected_file, affected_line, or fix_code required for PR creation"
        )

    fix_branch = f"ai-fix/{result['id']}"
    create_fix_branch(
        args.repo_url,
        args.broken_branch,
        fix_branch,
        affected_file,
        int(affected_line),
        fix_code,
    )
    print(f"Pushed fix branch: {fix_branch}")

    pr = github.create_pull_request(
        head=fix_branch,
        base=args.broken_branch,
        title=f"AI fix for incident {result['id']}",
        body=(
            f"Automated fix created from Jenkins build #{build_number}.\n\n"
            f"- Confidence: {confidence}%\n"
            f"- Fix: {result.get('fix_description')}\n"
        ),
    )
    print(f"Created PR: {pr['html_url']}")

    verify_build = jenkins.trigger_build(
        args.job_name,
        {
            "REPO_BRANCH": fix_branch,
            "SIMULATE_FAILURE": "false",
            "AUTO_HEAL_ON_FAILURE": "false",
        },
    )
    print(f"Triggered verification build: #{verify_build}")

    verify_result = jenkins.wait_for_build(args.job_name, verify_build)
    print(f"Verification build #{verify_build} result: {verify_result.get('result')}")
    if verify_result.get("result") != "SUCCESS":
        console = jenkins.get_console(args.job_name, verify_build)
        raise RuntimeError(
            f"Verification build failed unexpectedly.\n{console[-3000:]}"
        )

    print("Auto-heal cycle completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
