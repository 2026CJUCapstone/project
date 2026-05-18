#!/usr/bin/env python3
"""Seed the canonical 20 sample problems through the public API."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict


BASE = os.getenv("WEBCOMPILER_BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_USERNAME = os.getenv("WEBCOMPILER_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("WEBCOMPILER_ADMIN_PASSWORD", "admin1234")


def request(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as res:
            data = res.read()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        print(f"Error {exc.code}: {exc.read().decode()}", file=sys.stderr)
        sys.exit(1)


def get(path: str, token: str | None = None):
    return request("GET", path, token=token)


def post(path: str, body: dict, token: str | None = None):
    return request("POST", path, body=body, token=token)


def put(path: str, body: dict, token: str):
    return request("PUT", path, body=body, token=token)


def delete(path: str, token: str):
    return request("DELETE", path, token=token)


PROBLEMS = [
    {
        "title": "Hello, World!",
        "difficulty": "iron5",
        "tags": ["io"],
        "description": "## 문제\n\n화면에 `Hello, World!`를 출력하는 프로그램을 작성하세요.\n\n## 입력\n없음\n\n## 출력\n`Hello, World!`를 출력합니다.",
        "testCases": [{"input": "", "expectedOutput": "Hello, World!"}],
        "hiddenTestCases": [{"input": "", "expectedOutput": "Hello, World!"}],
    },
    {
        "title": "두 수의 합",
        "difficulty": "iron4",
        "tags": ["io"],
        "description": "## 문제\n\n두 정수 A와 B를 입력받아 합을 출력하세요.\n\n## 입력\n첫째 줄에 두 정수 A, B가 공백으로 구분되어 주어집니다.\n\n## 출력\nA + B를 출력합니다.",
        "testCases": [{"input": "1 2", "expectedOutput": "3"}, {"input": "100 200", "expectedOutput": "300"}],
        "hiddenTestCases": [{"input": "999 1", "expectedOutput": "1000"}],
    },
    {
        "title": "두 수의 차",
        "difficulty": "iron3",
        "tags": ["io"],
        "description": "## 문제\n\n두 정수 A와 B를 입력받아 A-B를 출력하세요.\n\n## 입력\n첫째 줄에 두 정수 A, B가 공백으로 구분되어 주어집니다.\n\n## 출력\nA-B를 출력합니다.",
        "testCases": [{"input": "7 3", "expectedOutput": "4"}, {"input": "10 20", "expectedOutput": "-10"}],
        "hiddenTestCases": [{"input": "1000 1", "expectedOutput": "999"}],
    },
    {
        "title": "두 수의 곱",
        "difficulty": "iron2",
        "tags": ["io"],
        "description": "## 문제\n\n두 정수 A와 B를 입력받아 곱을 출력하세요.\n\n## 입력\n첫째 줄에 두 정수 A, B가 공백으로 구분되어 주어집니다.\n\n## 출력\nA x B를 출력합니다.",
        "testCases": [{"input": "3 4", "expectedOutput": "12"}, {"input": "-2 5", "expectedOutput": "-10"}],
        "hiddenTestCases": [{"input": "0 999", "expectedOutput": "0"}],
    },
    {
        "title": "몫과 나머지",
        "difficulty": "iron1",
        "tags": ["io"],
        "description": "## 문제\n\n정수 A와 B가 주어질 때, A를 B로 나눈 몫과 나머지를 공백으로 구분해 출력하세요.\n\n## 입력\n첫째 줄에 두 정수 A, B가 주어집니다. 단, B는 0이 아닙니다.\n\n## 출력\n몫과 나머지를 공백으로 구분해 출력합니다.",
        "testCases": [{"input": "7 3", "expectedOutput": "2 1"}, {"input": "20 5", "expectedOutput": "4 0"}],
        "hiddenTestCases": [{"input": "100 9", "expectedOutput": "11 1"}],
    },
    {
        "title": "짝수와 홀수",
        "difficulty": "bronze5",
        "tags": ["control"],
        "description": "## 문제\n\n정수 N이 주어졌을 때, 짝수면 `Even`, 홀수면 `Odd`를 출력하세요.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\n짝수면 `Even`, 홀수면 `Odd`를 출력합니다.",
        "testCases": [{"input": "2", "expectedOutput": "Even"}, {"input": "7", "expectedOutput": "Odd"}],
        "hiddenTestCases": [{"input": "100", "expectedOutput": "Even"}],
    },
    {
        "title": "세 수의 최댓값",
        "difficulty": "bronze4",
        "tags": ["control"],
        "description": "## 문제\n\n세 정수 A, B, C가 주어질 때 가장 큰 값을 출력하세요.\n\n## 입력\n첫째 줄에 세 정수 A, B, C가 공백으로 구분되어 주어집니다.\n\n## 출력\n세 수 중 최댓값을 출력합니다.",
        "testCases": [{"input": "1 2 3", "expectedOutput": "3"}, {"input": "9 4 7", "expectedOutput": "9"}],
        "hiddenTestCases": [{"input": "-1 -5 -3", "expectedOutput": "-1"}],
    },
    {
        "title": "구구단 출력",
        "difficulty": "bronze3",
        "tags": ["control"],
        "description": "## 문제\n\n정수 N이 주어질 때 N단을 1부터 9까지 한 줄에 하나씩 출력하세요. 각 줄은 `N * i = 결과` 형식을 따릅니다.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\nN단을 출력합니다.",
        "testCases": [
            {
                "input": "2",
                "expectedOutput": "2 * 1 = 2\n2 * 2 = 4\n2 * 3 = 6\n2 * 4 = 8\n2 * 5 = 10\n2 * 6 = 12\n2 * 7 = 14\n2 * 8 = 16\n2 * 9 = 18",
            }
        ],
        "hiddenTestCases": [
            {
                "input": "3",
                "expectedOutput": "3 * 1 = 3\n3 * 2 = 6\n3 * 3 = 9\n3 * 4 = 12\n3 * 5 = 15\n3 * 6 = 18\n3 * 7 = 21\n3 * 8 = 24\n3 * 9 = 27",
            }
        ],
    },
    {
        "title": "1부터 N까지의 합",
        "difficulty": "bronze2",
        "tags": ["control"],
        "description": "## 문제\n\n정수 N이 주어질 때, 1부터 N까지의 합을 출력하세요.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\n1 + 2 + ... + N의 값을 출력합니다.",
        "testCases": [{"input": "1", "expectedOutput": "1"}, {"input": "10", "expectedOutput": "55"}],
        "hiddenTestCases": [{"input": "100", "expectedOutput": "5050"}],
    },
    {
        "title": "윤년 판별",
        "difficulty": "bronze1",
        "tags": ["control"],
        "description": "## 문제\n\n연도 Y가 주어질 때 윤년이면 `Yes`, 아니면 `No`를 출력하세요. 윤년의 조건은 400의 배수이거나, 4의 배수이면서 100의 배수가 아닌 경우입니다.\n\n## 입력\n첫째 줄에 연도 Y가 주어집니다.\n\n## 출력\n윤년이면 `Yes`, 아니면 `No`를 출력합니다.",
        "testCases": [{"input": "2000", "expectedOutput": "Yes"}, {"input": "1900", "expectedOutput": "No"}],
        "hiddenTestCases": [{"input": "2024", "expectedOutput": "Yes"}],
    },
    {
        "title": "팩토리얼",
        "difficulty": "silver5",
        "tags": ["func", "control"],
        "description": "## 문제\n\n정수 N이 주어질 때 N!을 출력하세요.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다. (0 <= N <= 12)\n\n## 출력\nN!을 출력합니다.",
        "testCases": [{"input": "0", "expectedOutput": "1"}, {"input": "5", "expectedOutput": "120"}],
        "hiddenTestCases": [{"input": "10", "expectedOutput": "3628800"}],
    },
    {
        "title": "피보나치 수열",
        "difficulty": "silver4",
        "tags": ["func", "control"],
        "description": "## 문제\n\nN번째 피보나치 수를 출력하세요. 피보나치 수열은 F(1)=1, F(2)=1, F(n)=F(n-1)+F(n-2) 입니다.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\nN번째 피보나치 수를 출력합니다.",
        "testCases": [{"input": "1", "expectedOutput": "1"}, {"input": "10", "expectedOutput": "55"}],
        "hiddenTestCases": [{"input": "20", "expectedOutput": "6765"}],
    },
    {
        "title": "소수 판별",
        "difficulty": "silver3",
        "tags": ["func", "control"],
        "description": "## 문제\n\n정수 N이 주어질 때 소수이면 `Yes`, 아니면 `No`를 출력하세요.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\n소수이면 `Yes`, 아니면 `No`를 출력합니다.",
        "testCases": [{"input": "2", "expectedOutput": "Yes"}, {"input": "10", "expectedOutput": "No"}],
        "hiddenTestCases": [{"input": "97", "expectedOutput": "Yes"}],
    },
    {
        "title": "약수의 개수",
        "difficulty": "silver2",
        "tags": ["func", "control"],
        "description": "## 문제\n\n정수 N이 주어질 때, N의 양의 약수 개수를 출력하세요.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\nN의 양의 약수 개수를 출력합니다.",
        "testCases": [{"input": "1", "expectedOutput": "1"}, {"input": "12", "expectedOutput": "6"}],
        "hiddenTestCases": [{"input": "36", "expectedOutput": "9"}],
    },
    {
        "title": "문자열 뒤집기",
        "difficulty": "silver1",
        "tags": ["io", "func"],
        "description": "## 문제\n\n문자열 S가 주어질 때 뒤집은 문자열을 출력하세요.\n\n## 입력\n첫째 줄에 공백 없는 문자열 S가 주어집니다.\n\n## 출력\n문자열 S를 뒤집은 결과를 출력합니다.",
        "testCases": [{"input": "abcde", "expectedOutput": "edcba"}, {"input": "level", "expectedOutput": "level"}],
        "hiddenTestCases": [{"input": "compiler", "expectedOutput": "relipmoc"}],
    },
    {
        "title": "문자열 길이",
        "difficulty": "gold5",
        "tags": ["io", "func"],
        "description": "## 문제\n\n공백 없는 문자열 S가 주어질 때 길이를 출력하세요.\n\n## 입력\n첫째 줄에 문자열 S가 주어집니다.\n\n## 출력\n문자열의 길이를 출력합니다.",
        "testCases": [{"input": "hello", "expectedOutput": "5"}, {"input": "a", "expectedOutput": "1"}],
        "hiddenTestCases": [{"input": "algorithm", "expectedOutput": "9"}],
    },
    {
        "title": "모음 개수",
        "difficulty": "gold4",
        "tags": ["io", "func"],
        "description": "## 문제\n\n영문 소문자 문자열 S가 주어질 때, 포함된 모음(a, e, i, o, u)의 개수를 출력하세요.\n\n## 입력\n첫째 줄에 문자열 S가 주어집니다.\n\n## 출력\n모음의 개수를 출력합니다.",
        "testCases": [{"input": "apple", "expectedOutput": "2"}, {"input": "sky", "expectedOutput": "0"}],
        "hiddenTestCases": [{"input": "beautiful", "expectedOutput": "5"}],
    },
    {
        "title": "회문 판별",
        "difficulty": "gold3",
        "tags": ["io", "control"],
        "description": "## 문제\n\n문자열 S가 주어질 때 앞에서 읽으나 뒤에서 읽으나 같으면 `Yes`, 아니면 `No`를 출력하세요.\n\n## 입력\n첫째 줄에 공백 없는 문자열 S가 주어집니다.\n\n## 출력\n회문이면 `Yes`, 아니면 `No`를 출력합니다.",
        "testCases": [{"input": "level", "expectedOutput": "Yes"}, {"input": "hello", "expectedOutput": "No"}],
        "hiddenTestCases": [{"input": "abba", "expectedOutput": "Yes"}],
    },
    {
        "title": "최대공약수와 최소공배수",
        "difficulty": "gold2",
        "tags": ["func", "control"],
        "description": "## 문제\n\n두 정수 A와 B가 주어질 때 최대공약수와 최소공배수를 공백으로 구분해 출력하세요.\n\n## 입력\n첫째 줄에 두 정수 A, B가 주어집니다.\n\n## 출력\n최대공약수와 최소공배수를 공백으로 구분해 출력합니다.",
        "testCases": [{"input": "6 8", "expectedOutput": "2 24"}, {"input": "12 18", "expectedOutput": "6 36"}],
        "hiddenTestCases": [{"input": "21 14", "expectedOutput": "7 42"}],
    },
    {
        "title": "약수의 합",
        "difficulty": "gold1",
        "tags": ["func", "control"],
        "description": "## 문제\n\n정수 N이 주어질 때, N의 양의 약수 합을 출력하세요.\n\n## 입력\n첫째 줄에 정수 N이 주어집니다.\n\n## 출력\nN의 양의 약수 합을 출력합니다.",
        "testCases": [{"input": "1", "expectedOutput": "1"}, {"input": "6", "expectedOutput": "12"}],
        "hiddenTestCases": [{"input": "12", "expectedOutput": "28"}],
    },
]


def main() -> None:
    token_response = post(
        "/api/v1/auth/login",
        {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    token = token_response.get("accessToken") or token_response.get("access_token")
    if not token:
        print("Login succeeded but no access token was returned.", file=sys.stderr)
        sys.exit(1)

    existing = get("/api/v1/problems/")
    by_title: dict[str, list[dict]] = defaultdict(list)
    for problem in existing:
        by_title[problem["title"]].append(problem)

    desired_titles = {problem["title"] for problem in PROBLEMS}
    removed = 0
    for title, problems in list(by_title.items()):
        keep_first = title in desired_titles
        for problem in problems[1 if keep_first else 0 :]:
            delete(f"/api/v1/problems/{problem['id']}", token)
            removed += 1
        if not keep_first:
            by_title.pop(title, None)
        else:
            by_title[title] = problems[:1]

    created = 0
    updated = 0
    for problem in PROBLEMS:
        current = by_title.get(problem["title"], [])
        if current:
            put(f"/api/v1/problems/{current[0]['id']}", problem, token)
            updated += 1
            print(f"  Updated: [{problem['difficulty']}] {problem['title']}")
        else:
            post("/api/v1/problems/", problem, token)
            created += 1
            print(f"  Created: [{problem['difficulty']}] {problem['title']}")

    final_count = len(get("/api/v1/problems/"))
    print(f"\nDone! created={created}, updated={updated}, removed={removed}, total={final_count}.")
    if final_count != len(PROBLEMS):
        print(f"Expected {len(PROBLEMS)} problems, found {final_count}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
