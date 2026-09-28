"""Native, graph-equivalence and uncached ordinary-example latency checks.

Run inside a resource-bounded isolated runtime with an explicit compiler.
Does not benchmark production queues or claim browser paint latency.
"""
import copy
import json
import re
from pathlib import Path
import subprocess
import time
import tempfile


CASES = {
    "hello": ('import std.io;\nfunc main()->u64 { emitln("안녕 😀"); return 0; }\n', "안녕 😀\n".encode()),
    "branch": ('import std.io;\nfunc main()->u64 { var n:u64=7; if(n%2==1){emitln("odd");}else{emitln("even");} return 0; }\n', b"odd\n"),
    "loop": ('import std.io;\nfunc main()->u64 { var sum:u64=0; for(var i:u64=1;i<=10;i++){sum+=i;} print_u64(sum); emitln(""); return 0; }\n', b"55\n"),
    "nested_loop": ('import std.io;\nfunc main()->u64 { var sum:u64=0; for(var i:u64=1;i<=4;i++){for(var j:u64=1;j<=3;j++){sum+=i*j;}} print_u64(sum); emitln(""); return 0; }\n', b"60\n"),
    "array": ('import std.io;\nfunc main()->u64 { var a:[5]u64; for(var i:u64=0;i<5;i++){a[i]=i*i;} print_u64(a[4]); emitln(""); return 0; }\n', b"16\n"),
    "calls": ('import std.io;\nfunc twice(x:u64)->u64{return x*2;}\nfunc unused(x:u64)->u64{return x+3;}\nfunc main()->u64{print_u64(twice(21));emitln("");return 0;}\n', b"42\n"),
    "recursion": ('import std.io;\nfunc fact(n:u64)->u64{if(n<=1){return 1;}return n*fact(n-1);}\nfunc main()->u64{print_u64(fact(6));emitln("");return 0;}\n', b"720\n"),
    "pointer": ('import std.io;\nfunc add(p:*u64)->u64{*p=*p+1;return *p;}\nfunc main()->u64{var n:u64=41;print_u64(add(&n));emitln("");return 0;}\n', b"42\n"),
    "binary_search": ('import std.io;\nfunc main()->u64{var a:[8]u64;for(var i:u64=0;i<8;i++){a[i]=2*i+1;}var l:u64=0;var r:u64=8;while(l<r){var m:u64=(l+r)/2;if(a[m]<7){l=m+1;}else{r=m;}}print_u64(l);emitln("");return 0;}\n', b"3\n"),
    "bubble_sort": ('import std.io;\nfunc main()->u64{var a:[5]u64;for(var i:u64=0;i<5;i++){a[i]=5-i;}for(var i:u64=0;i<5;i++){for(var j:u64=0;j+1<5-i;j++){if(a[j]>a[j+1]){var t:u64=a[j];a[j]=a[j+1];a[j+1]=t;}}}print_u64(a[0]);print_u64(a[4]);emitln("");return 0;}\n', b"15\n"),
    "gcd": ('import std.io;\nfunc gcd(a:u64,b:u64)->u64{while(b!=0){var t:u64=a%b;a=b;b=t;}return a;}\nfunc main()->u64{print_u64(gcd(84,30));emitln("");return 0;}\n', b"6\n"),
    "dynamic_programming": ('import std.io;\nfunc main()->u64{var dp:[11]u64;dp[0]=0;dp[1]=1;for(var i:u64=2;i<=10;i++){dp[i]=dp[i-1]+dp[i-2];}print_u64(dp[10]);emitln("");return 0;}\n', b"55\n"),
}

GC_SOURCE = '''import std.io;
import std.mem;
func main()->u64 {
    bpp_gc_set_auto(0,0);
    var raw:u64=heap_alloc(32);
    if(bpp_gc_find_block(raw)!=0){return 11;}
    var tagged_ptr:u64=bpp_gc_alloc_tagged(32,0);
    var block:*BppGcBlock=bpp_gc_find_block(tagged_ptr);
    if(block==0 || bpp_gc_find_block(bpp_gc_block_raw(block))!=block){return 12;}
    if(bpp_gc_find_block(raw)!=0 || bpp_gc_find_block(0)!=0){return 13;}
    // Simulate an unindexed live block after index-allocation failure.
    bpp_gc_block_index_remove(block);
    g_bpp_gc_block_index_incomplete=1;
    if(bpp_gc_find_block(tagged_ptr)!=block){return 14;}
    bpp_gc_block_index_insert(block);
    if(g_bpp_gc_block_index_incomplete!=1){return 15;}
    bpp_gc_set_root_slot_tracking(1);
    bpp_gc_root_slot_push(&tagged_ptr);
    bpp_gc_set_moving_enabled(1);
    var previous:u64=bpp_gc_block_raw(block);
    if(bpp_gc_move_block(block)!=1){return 16;}
    if(bpp_gc_find_block(previous)!=0 || bpp_gc_find_block(tagged_ptr)!=block){return 17;}
    bpp_gc_root_slot_pop();
    bpp_gc_forget_live(tagged_ptr);
    if(bpp_gc_find_block(tagged_ptr)!=0){return 18;}
    heap_free(tagged_ptr);
    heap_free(raw);
    bpp_gc_reset();
    if(g_bpp_gc_block_index_incomplete!=0 || bpp_gc_live_count()!=0){return 19;}
    var again:u64=bpp_gc_alloc_raw(16,0);
    if(bpp_gc_find_block(again)==0){return 20;}
    bpp_gc_reset();
    emitln("GC OK");
    return 0;
}
'''

ROBUSTNESS_CASES = {
    'indirect-call': ('''import std.io;
func twice(n:u64)->u64{return n*2;}
func main()->u64{var fp:u64=&twice;print_u64(fp(21));emitln("");return 0;}
''', b'42\n'),
    'user-assembly': ('''import std.io;
func value()->u64{var n:u64=0;asm { mov rax, 7
mov [rbp-8], rax
} return n;}
func main()->u64{print_u64(value());emitln("");return 0;}
''', b'7\n'),
    'gc-index': (GC_SOURCE, b'GC OK\n'),
    'capture-boundaries': ('''import std.io;
import std.str;
func main()->u64 {
    asm_source_capture_start(1);
    asm_source_capture_write("ab",2);
    asm_source_capture_write("c\\n\\n",3);
    asm_source_capture_write("de",2);
    asm_source_capture_stop();
    if(g_asm_source_line_len!=3){return 11;}
    if(g_asm_source_line_text_lens[0]!=3 || g_asm_source_line_text_lens[1]!=0 || g_asm_source_line_text_lens[2]!=2){return 12;}
    if(str_eq(slice(g_asm_source_line_text_ptrs[0],3),slice("abc",3))==0){return 13;}
    if(str_eq(slice(g_asm_source_line_text_ptrs[2],2),slice("de",2))==0){return 14;}
    asm_source_capture_start(1);
    asm_source_capture_write("x",1);
    asm_source_capture_stop();
    if(g_asm_source_line_len!=1 || g_asm_source_line_text_lens[0]!=1){return 15;}
    emitln("capture OK");return 0;
}
''', b'capture OK\n'),
}


def canonical_graphs(payload):
    """Only allocation-derived function/instruction IDs may change.

    Keep block edges, registers, opcodes, constants, source offsets/AST links,
    optimization counters and generated markers byte-for-byte comparable.
    """
    result = copy.deepcopy(payload)
    for stage in ("ir", "ssa"):
        for function in result["views"][stage]["ssa"]["functions"]:
            function.pop("id", None)
            for block in function["blocks"]:
                for instruction in block["instructions"]:
                    instruction.pop("id", None)
                    instruction.pop("numericId", None)
    # Removing unrelated native library bodies renumbers compiler-generated
    # labels, not their uses. Alpha-rename consistently, never erase operands.
    symbols = {}
    def relabel(value):
        if isinstance(value, dict):
            return {key: relabel(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relabel(item) for item in value]
        if isinstance(value, str):
            return re.sub(r'(?<![\w])(?:_str\d+|\.L\d+)(?!\w)',
                          lambda match: symbols.setdefault(match[0], f'__generated_{len(symbols)}'), value)
        return value
    result['views']['asm'] = relabel(result['views']['asm'])
    return result


def compile_graphs(root: Path, compiler: str, source: str, level: str):
    path = root / "main.bpp"
    path.write_bytes(source.encode())
    assembly, obj, binary = (root / name for name in ("native.asm", "native.o", "native"))
    started = time.monotonic()
    # The shell owns fd3. Arguments are positional, never interpolated source.
    result = subprocess.run([
        "sh", "-c", 'exec "$1" "$2" --emit-json --views ast,ir,ssa,asm '
        '--source-map-user-only --ast-no-std --native-asm-fd3 "$3" 3>"$4"',
        "probe", compiler, "-" + level, str(path), str(assembly),
    ], cwd=root, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert 0 < len(result.stdout) <= 1048576
    for argv in (["nasm", "-felf64", "-O1", str(assembly), "-o", str(obj)], ["ld", str(obj), "-o", str(binary)]):
        native = subprocess.run(argv, capture_output=True, timeout=5)
        if native.returncode:
            diagnostic = native.stderr.decode(errors="replace")
            line = re.search(r'native.asm:(\d+):', diagnostic)
            context = assembly.read_text().splitlines()[max(0, int(line[1])-2):int(line[1])+1] if line else []
            raise AssertionError((argv, diagnostic, context))
    elapsed = time.monotonic() - started
    return json.loads(result.stdout), elapsed, binary, assembly


def main():
    """Small installed-image correctness gate, not a build-host speed claim."""
    import os
    count = 0
    with tempfile.TemporaryDirectory(prefix='bpp-json-gate-') as directory:
        root = Path(directory)
        for name in ('hello', 'pointer'):
            source, expected = CASES[name]
            for level in ('O0', 'O1'):
                payload, _, binary, _ = compile_graphs(root, 'bpp', source, level)
                assert all(view in payload['views'] for view in ('ast', 'ir', 'ssa', 'asm'))
                result = subprocess.run([str(binary)], capture_output=True, timeout=3)
                assert result.returncode == 0 and result.stdout == expected, (name, level)
                count += 1
        for name in ('gc-index', 'capture-boundaries'):
            source, expected = ROBUSTNESS_CASES[name]
            _, _, binary, _ = compile_graphs(root, 'bpp', source, 'O1')
            result = subprocess.run([str(binary)], capture_output=True, timeout=3)
            assert result.returncode == 0 and result.stdout == expected, name
            count += 1
        path = root / 'main.bpp'
        for bad in ('invalid_bpp_instruction', 'call missing_native_label'):
            path.write_text('func main()->u64 { asm { ' + bad + '\n } return 0; }\n')
            result = subprocess.run(['/usr/local/bin/run.sh', 'compile-json', 'bpp', str(path)],
                                    env={**os.environ, 'COMPILER_OPTIMIZE': '0'},
                                    capture_output=True, timeout=30)
            assert result.returncode != 0 and not result.stdout, 'Native failure published graph success'
    print(json.dumps({'compileJsonNativeCases': count, 'nativeFailureCases': 2, 'passed': True}))


if __name__ == '__main__':
    main()
