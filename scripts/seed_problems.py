#!/usr/bin/env python3
"""Seed sample problems into the database via API."""
import urllib.request
import json
import sys

BASE = "http://localhost:8000"


def post(path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers=headers,
    )
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read())
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}")
        sys.exit(1)


# 1. 로그인
result = post("/api/v1/auth/login", {"username": "admin", "password": "admin1234"})
token = result["accessToken"]
print(f"Logged in as admin")

# 2. 문제 목록
PROBLEMS = [
    {
        "title": "Hello, World!",
        "difficulty": "iron5",
        "tags": ["io"],
        "description": (
            "## 문제\n\n"
            "화면에 `Hello, World!`를 출력하는 프로그램을 작성하세요.\n\n"
            "## 입력\n없음\n\n"
            "## 출력\n`Hello, World!`"
        ),
        "testCases": [
            {"input": "", "expectedOutput": "Hello, World!"}
        ],
        "hiddenTestCases": [
            {"input": "", "expectedOutput": "Hello, World!"}
        ],
    },
    {
        "title": "두 수의 합",
        "difficulty": "iron4",
        "tags": ["io"],
        "description": (
            "## 문제\n\n"
            "두 정수 A와 B를 입력받아 합을 출력하세요.\n\n"
            "## 입력\n첫째 줄에 두 정수 A, B가 공백으로 구분되어 주어집니다. (1 ≤ A, B ≤ 1000)\n\n"
            "## 출력\nA + B를 출력합니다."
        ),
        "testCases": [
            {"input": "1 2", "expectedOutput": "3"},
            {"input": "100 200", "expectedOutput": "300"},
            {"input": "999 1", "expectedOutput": "1000"},
        ],
        "hiddenTestCases": [
            {"input": "0 0", "expectedOutput": "0"},
            {"input": "123 456", "expectedOutput": "579"},
        ],
    },
    {
        "title": "짝수와 홀수",
        "difficulty": "iron3",
        "tags": ["control"],
        "description": (
            "## 문제\n\n"
            "정수 N이 주어졌을 때, 짝수면 `Even`, 홀수면 `Odd`를 출력하세요.\n\n"
            "## 입력\n첫째 줄에 정수 N이 주어집니다. (1 ≤ N ≤ 1000)\n\n"
            "## 출력\n짝수면 `Even`, 홀수면 `Odd`를 출력합니다."
        ),
        "testCases": [
            {"input": "2", "expectedOutput": "Even"},
            {"input": "7", "expectedOutput": "Odd"},
            {"input": "100", "expectedOutput": "Even"},
        ],
        "hiddenTestCases": [
            {"input": "1", "expectedOutput": "Odd"},
            {"input": "1000", "expectedOutput": "Even"},
        ],
    },
    {
        "title": "1부터 N까지의 합",
        "difficulty": "iron2",
        "tags": ["control"],
        "description": (
            "## 문제\n\n"
            "정수 N이 주어졌을 때, 1부터 N까지의 합을 출력하세요.\n\n"
            "## 입력\n첫째 줄에 정수 N이 주어집니다. (1 ≤ N ≤ 100)\n\n"
            "## 출력\n1 + 2 + ... + N을 출력합니다."
        ),
        "testCases": [
            {"input": "1", "expectedOutput": "1"},
            {"input": "10", "expectedOutput": "55"},
            {"input": "100", "expectedOutput": "5050"},
        ],
        "hiddenTestCases": [
            {"input": "2", "expectedOutput": "3"},
            {"input": "50", "expectedOutput": "1275"},
        ],
    },
    {
        "title": "팩토리얼",
        "difficulty": "bronze3",
        "tags": ["func"],
        "description": (
            "## 문제\n\n"
            "정수 N이 주어졌을 때, N! (N 팩토리얼)을 출력하세요.\n\n"
            "## 입력\n첫째 줄에 정수 N이 주어집니다. (0 ≤ N ≤ 12)\n\n"
            "## 출력\nN!을 출력합니다."
        ),
        "testCases": [
            {"input": "0", "expectedOutput": "1"},
            {"input": "5", "expectedOutput": "120"},
            {"input": "10", "expectedOutput": "3628800"},
            {"input": "12", "expectedOutput": "479001600"},
        ],
        "hiddenTestCases": [
            {"input": "1", "expectedOutput": "1"},
            {"input": "7", "expectedOutput": "5040"},
        ],
    },
    {
        "title": "피보나치 수열",
        "difficulty": "bronze2",
        "tags": ["func", "control"],
        "description": (
            "## 문제\n\n"
            "N번째 피보나치 수를 출력하세요.\n\n"
            "피보나치 수열: F(1)=1, F(2)=1, F(N)=F(N-1)+F(N-2) (N≥3)\n\n"
            "## 입력\n첫째 줄에 정수 N이 주어집니다. (1 ≤ N ≤ 20)\n\n"
            "## 출력\nN번째 피보나치 수를 출력합니다."
        ),
        "testCases": [
            {"input": "1", "expectedOutput": "1"},
            {"input": "5", "expectedOutput": "5"},
            {"input": "10", "expectedOutput": "55"},
            {"input": "20", "expectedOutput": "6765"},
        ],
        "hiddenTestCases": [
            {"input": "2", "expectedOutput": "1"},
            {"input": "15", "expectedOutput": "610"},
        ],
    },
    {
        "title": "소수 판별",
        "difficulty": "bronze1",
        "tags": ["func", "control"],
        "description": (
            "## 문제\n\n"
            "정수 N이 주어졌을 때, 소수이면 `Yes`, 아니면 `No`를 출력하세요.\n\n"
            "## 입력\n첫째 줄에 정수 N이 주어집니다. (2 ≤ N ≤ 10000)\n\n"
            "## 출력\nN이 소수면 `Yes`, 아니면 `No`를 출력합니다."
        ),
        "testCases": [
            {"input": "2", "expectedOutput": "Yes"},
            {"input": "7", "expectedOutput": "Yes"},
            {"input": "10", "expectedOutput": "No"},
            {"input": "9973", "expectedOutput": "Yes"},
        ],
        "hiddenTestCases": [
            {"input": "9", "expectedOutput": "No"},
            {"input": "97", "expectedOutput": "Yes"},
        ],
    },
    {
        "title": "숫자 배열 정렬",
        "difficulty": "silver5",
        "tags": ["func", "control"],
        "description": (
            "## 문제\n\n"
            "N개의 정수를 오름차순으로 정렬하여 출력하세요.\n\n"
            "## 입력\n"
            "첫째 줄에 N이 주어집니다. (1 ≤ N ≤ 100)\n"
            "둘째 줄에 N개의 정수가 공백으로 구분되어 주어집니다.\n\n"
            "## 출력\n정렬된 수를 공백으로 구분하여 출력합니다."
        ),
        "testCases": [
            {"input": "5\n3 1 4 1 5", "expectedOutput": "1 1 3 4 5"},
            {"input": "3\n10 2 7", "expectedOutput": "2 7 10"},
            {"input": "1\n42", "expectedOutput": "42"},
        ],
        "hiddenTestCases": [
            {"input": "6\n9 8 7 6 5 4", "expectedOutput": "4 5 6 7 8 9"},
            {"input": "4\n1 1 1 1", "expectedOutput": "1 1 1 1"},
        ],
    },
]

for p in PROBLEMS:
    result = post("/api/v1/problems/", p, token)
    print(f"  Created: [{result['difficulty']}] {result['title']}")

print(f"\nDone! {len(PROBLEMS)} problems inserted.")
