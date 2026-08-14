#!/usr/bin/env python3
"""Fetch and print open SonarQube maintainability (code smell) issues."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SonarIssue:
    key: str
    severity: str
    component: str
    line: int | None
    rule: str
    message: str


def _fetch_issues(host_url: str, token: str, project_key: str) -> list[SonarIssue]:
    page = 1
    page_size = 100
    issues: list[SonarIssue] = []

    while True:
        query = urlencode(
            {
                "componentKeys": project_key,
                "types": "CODE_SMELL",
                "resolved": "false",
                "ps": page_size,
                "p": page,
            }
        )
        url = f"{host_url.rstrip('/')}/api/issues/search?{query}"
        payload = _request_json(url, token)

        for item in payload.get("issues", []):
            issues.append(
                SonarIssue(
                    key=item.get("key", ""),
                    severity=item.get("severity", ""),
                    component=item.get("component", ""),
                    line=item.get("line"),
                    rule=item.get("rule", ""),
                    message=item.get("message", "").strip(),
                )
            )

        paging = payload.get("paging", {})
        total = int(paging.get("total", 0))
        fetched = page * page_size
        if fetched >= total:
            break

        page += 1

    return issues


def _request_json(url: str, token: str) -> dict:
    auth = base64.b64encode(f"{token}:".encode("utf-8")).decode("ascii")
    request = Request(url)
    request.add_header("Authorization", f"Basic {auth}")
    request.add_header("Accept", "application/json")

    with urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _format_component_path(component: str, project_key: str) -> str:
    prefix = f"{project_key}:"
    if component.startswith(prefix):
        return component[len(prefix) :]
    return component


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-url", required=True, help="SonarQube base URL")
    parser.add_argument("--token", required=True, help="SonarQube user token")
    parser.add_argument("--project-key", required=True, help="SonarQube project key")
    args = parser.parse_args()

    try:
        issues = _fetch_issues(args.host_url, args.token, args.project_key)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch Sonar issues: {exc}", file=sys.stderr)
        return 1

    print(f"Open maintainability issues (CODE_SMELL): {len(issues)}")
    if not issues:
        return 0

    for issue in issues:
        path = _format_component_path(issue.component, args.project_key)
        line = issue.line if issue.line is not None else "-"
        print(f"- [{issue.severity}] {path}:{line} | {issue.rule} | {issue.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
