"""Build and verify a draft, content-addressed A--J authoring corpus.

This is offline source material, not an approved contest package or a judge run.
The checked-in manifest deliberately contains hashes and byte counts, not hidden
test contents. Re-generating it after a source change requires explicit review.
"""

from __future__ import annotations

import argparse
import hashlib
from itertools import chain
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.freshman_contest.a_i import validate as validate_a_i
from tools.freshman_contest.banks import validate as validate_j
from tools.freshman_contest.banks_stress_cases import iter_cases as iter_j_stress
from tools.freshman_contest.stress_cases import iter_cases as iter_a_i_stress
from verify_freshman_contest_examples import DOCUMENT, EXPECTED_COUNTS, calculate


MANIFEST = ROOT / "tools" / "freshman_contest" / "corpus-manifest-draft-v2.json"
MAX_CASE_BYTES = 16 * 1024**2
MAX_EXPECTED_BYTES = 512 * 1024
MAX_SUITE_BYTES = 256 * 1024**2
# B's 216 ordered triples are checked exhaustively offline. The judge's
# per-problem suite has a 200-case ceiling, so retain representative branches
# here rather than silently claiming all 216 as submitted hidden cases.
B_MEASURED_COVERAGE = frozenset({
    "b-exhaustive-triple-1-6-1",  # equal first/third
    "b-exhaustive-triple-6-1-1",  # equal second/third
    "b-exhaustive-triple-1-2-3",  # distinct, maximum last
    "b-exhaustive-triple-3-2-1",  # distinct, maximum first
    "b-exhaustive-triple-2-3-1",  # distinct, maximum middle
    "b-exhaustive-triple-1-2-6",  # distinct, far maximum
})


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _statement_samples() -> dict[str, list[tuple[str, str, str]]]:
    document = DOCUMENT.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ([A-J])\. .+$", document)
    if sections[1::2] != list(EXPECTED_COUNTS):
        raise ValueError("Statement headings changed; review sample extraction")
    result: dict[str, list[tuple[str, str, str]]] = {}
    for letter, content in zip(sections[1::2], sections[2::2]):
        blocks = re.findall(r"~~~text\n(.*?)\n~~~", content, flags=re.S)
        if len(blocks) != 2 * EXPECTED_COUNTS[letter]:
            raise ValueError(f"{letter}: statement sample count changed")
        samples = []
        for index in range(0, len(blocks), 2):
            input_text = blocks[index] + "\n"
            expected = blocks[index + 1]
            if calculate(letter, input_text) != expected:
                raise ValueError(f"{letter}: sample oracle disagrees with statement")
            samples.append((f"{letter.lower()}-statement-sample-{index // 2 + 1}", input_text, expected))
        result[letter] = samples
    return result


def case_material(letter: str):
    """Yield reviewed-by-code candidates, preserving public/hidden membership."""
    samples = _statement_samples()[letter]
    for name, input_text, expected in samples:
        yield name, "sample", "statement-example-v1", input_text, expected
    if letter == "J":
        hidden = ((case, "banks-stress-v1") for case in iter_j_stress())
    else:
        from tools.freshman_contest.coverage_cases import iter_coverage_cases

        hidden = chain(
            ((case, "stress-v1") for case in iter_a_i_stress(letter)),
            ((case, "coverage-v1") for case in iter_coverage_cases(letter)
             if letter != "B" or case.name in B_MEASURED_COVERAGE),
        )
    for case, provenance in hidden:
        yield case.name, "hidden", provenance, case.input_text, case.expected_output


def _case_row(letter: str, name: str, visibility: str, provenance: str, input_text: str, expected: str):
    (validate_j(input_text) if letter == "J" else validate_a_i(letter, input_text))
    input_data = input_text.encode("utf-8")
    expected_data = expected.encode("utf-8")
    if len(input_data) > MAX_CASE_BYTES or len(expected_data) > MAX_EXPECTED_BYTES:
        raise ValueError(f"{letter}/{name}: case byte budget exceeded")
    return dict(name=name, visibility=visibility, provenance=provenance,
                inputBytes=len(input_data), inputHash=sha256(input_data),
                expectedBytes=len(expected_data), expectedHash=sha256(expected_data))


def build_manifest() -> dict:
    source_dir = ROOT / "tools" / "freshman_contest"
    sources = {path.name: sha256(path.read_bytes()) for path in (
        DOCUMENT, source_dir / "a_i.py", source_dir / "banks.py",
        source_dir / "stress_cases.py", source_dir / "coverage_cases.py",
        source_dir / "banks_stress_cases.py", ROOT / "scripts" / "verify_freshman_contest_examples.py",
        Path(__file__).resolve(),
    )}
    # Only public statement samples are embedded; hidden candidate contents
    # remain generator-derived and are bound by hashes below.
    sample_data = {
        letter: [dict(name=name, input=input_text, expected_output=expected)
                 for name, input_text, expected in samples]
        for letter, samples in _statement_samples().items()
    }
    problems = {}
    for letter in "ABCDEFGHIJ":
        rows = [_case_row(letter, *item) for item in case_material(letter)]
        names = [row["name"] for row in rows]
        if len(names) != len(set(names)) or not 1 <= len(rows) <= 200:
            raise ValueError(f"{letter}: duplicate or invalid case count")
        if sum(row["inputBytes"] + row["expectedBytes"] for row in rows) > MAX_SUITE_BYTES:
            raise ValueError(f"{letter}: decoded suite budget exceeded")
        problems[letter] = rows
    payload = dict(version=1, status="draft-unapproved", sampleData=sample_data,
                   sources=sources, problems=problems)
    payload["manifestHash"] = sha256(json.dumps(payload, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return payload


def verify_frozen(path: Path = MANIFEST) -> dict:
    stored = json.loads(path.read_text(encoding="utf-8"))
    current = build_manifest()
    if stored != current:
        raise ValueError("Frozen freshman corpus differs from current statement/generator sources")
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Compare with the checked-in draft manifest")
    parser.add_argument("--write", action="store_true", help="Create the fixed v2 draft manifest once; never overwrite")
    args = parser.parse_args()
    if args.verify and args.write:
        parser.error("--verify and --write are mutually exclusive")
    result = verify_frozen() if args.verify else build_manifest()
    if args.write:
        with MANIFEST.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps(result if not args.verify else {
        "manifestHash": result["manifestHash"],
        "caseCounts": {letter: len(rows) for letter, rows in result["problems"].items()},
        "status": result["status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
