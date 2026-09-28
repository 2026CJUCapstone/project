"""Opt-in, bounded isolated-container check; never touches service DBs or queues.

Run with --ssh-host user@host --ssh-port port --image <verified sandbox image>.
Requires key authentication and Docker on the selected host; creates only two
ephemeral containers with capped resources, no mounts, secrets or network.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.compiler_graphs import build_bpp_pipeline_from_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ssh-host", required=True)
parser.add_argument("--ssh-port", type=int, required=True)
parser.add_argument("--image", required=True)
parser.add_argument("--production-limits", action="store_true",
                    help="Use the production 1 CPU / 256 MiB / 30 second per-mode contract")
args = parser.parse_args()
source_lines = ["import emitln from std.io;", "// 한글 😀", "func main() -> u64 {",
                '    emitln("안녕 😀");', "    return 0;", "}", ""]
reports = []
for newline, optimize in [("\n", "0"), ("\r\n", "1")]:
    source = newline.join(source_lines)
    # The generated source is written only inside a disposable container tmpfs.
    container_script = """
import json, pathlib, subprocess, tempfile
with tempfile.TemporaryDirectory(dir='/tmp') as directory:
    path = pathlib.Path(directory) / 'main.bpp'
    path.write_bytes(SOURCE.encode('utf-8'))
    results = {}
    for mode in ('json', 'dump-ir-json'):
        result = subprocess.run(['/usr/local/bin/run.sh', mode, 'bpp', str(path)],
                                capture_output=True, text=True, timeout=MODE_TIMEOUT)
        if result.returncode:
            raise RuntimeError(mode + ': ' + result.stderr[:1000])
        results[mode] = json.loads(result.stdout)
    print(json.dumps(results))
""".replace("SOURCE", repr(source)).replace("MODE_TIMEOUT", str(30 if args.production_limits else 35))
    remote_script = """
import subprocess, sys
command = COMMAND
result = subprocess.run(command, input=SCRIPT, text=True, capture_output=True, timeout=90)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
sys.exit(result.returncode)
""".replace("COMMAND", repr([
        "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
        "--cpus", "1" if args.production_limits else "0.5",
        "--memory", "256m" if args.production_limits else "512m",
        "--memory-swap", "256m" if args.production_limits else "512m",
        "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:rw,exec,nosuid,size=128m", "--user", "1000:1000",
        "--env", f"COMPILER_OPTIMIZE={optimize}", "--env", "HOME=/tmp",
        "--label", "webcompiler.test=source-mapping", "--entrypoint", "python3",
        args.image, "-c", container_script,
    ])).replace("SCRIPT", repr(""))
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                             "-p", str(args.ssh_port), args.ssh_host, "python3 -"],
                            input=remote_script, encoding="utf-8", capture_output=True, timeout=100)
    if result.returncode:
        raise RuntimeError(result.stderr[:2000])
    raw = json.loads(result.stdout)
    unified = build_bpp_pipeline_from_json(json.dumps(raw["json"]), source, "main.bpp") or {}
    ir = build_bpp_pipeline_from_json(json.dumps(raw["dump-ir-json"]), source, "main.bpp", {"ir"})
    assert ir and ir["ir"]["instructions"], "Dedicated IR JSON must not fall back to unmapped text"
    unified["ir"] = ir["ir"]
    ranges = {
        "AST": [r for n in unified["ast"]["nodes"] for r in n.get("sourceRanges", [])],
        "SSA": [r for b in unified["ssa"]["blocks"] for rs in b.get("instructionSourceRanges", []) for r in rs],
        "IR": [r for n in unified["ir"]["instructions"] for r in n.get("sourceRanges", [])],
        "ASM": [r for n in unified["asm"]["lines"] for r in n.get("sourceRanges", [])],
    }
    for stage, entries in ranges.items():
        assert entries, f"{stage}: missing ranges"
        selected = [source.encode("utf-8")[r["startOffset"]:r["endOffset"]].decode("utf-8") for r in entries]
        assert any("return 0" in text or 'emitln("안녕' in text for text in selected), (stage, selected)
    reports.append({"newline": repr(newline), "optimize": optimize, "mappedRanges": {k: len(v) for k, v in ranges.items()}})
print(json.dumps(reports, ensure_ascii=True, indent=2))
