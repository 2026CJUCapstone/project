"""Trusted, append-only execution recipes for measured receipt replay.

Existing profile entries must not be edited when a compiler recipe changes.
Add a new profile and make it current only after its image and tests exist.
No recipe is read from a problem, receipt, or operator JSON.
"""
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType


@dataclass(frozen=True)
class ToolchainAdapter:
    language: str
    profile: str
    source_name: str
    compile_command: tuple[str, ...]
    run_command: tuple[str, ...]
    artifact_contract: str
    scratch_layout: str
    container_contract: str = 'measured-container-v1'

    def fingerprint(self):
        data=(self.language,self.profile,self.source_name,self.compile_command,
            self.run_command,self.artifact_contract,self.scratch_layout,
            self.container_contract)
        return 'sha256:'+hashlib.sha256(json.dumps(data,ensure_ascii=False,
            separators=(',',':')).encode('utf-8')).hexdigest()


_HISTORICAL = (
    ToolchainAdapter('c','c17-o2-v1','main.c',
        ('/usr/bin/gcc','-std=c17','-O2','/source/main.c','-o','/work/artifact/program'),
        ('/artifact/program',),'bounded-tar-v1','work-v1'),
    ToolchainAdapter('cpp','cpp17-o2-v1','main.cpp',
        ('/usr/bin/g++','-std=c++17','-O2','/source/main.cpp','-o','/work/artifact/program'),
        ('/artifact/program',),'bounded-tar-v1','work-v1'),
    ToolchainAdapter('python','cpython-pyc-v1','main.py',
        ('/usr/bin/python3','-I','-c',
         "import py_compile;py_compile.compile('/source/main.py',cfile='/work/artifact/main.pyc',doraise=True)"),
        ('/usr/bin/python3','-I','/artifact/main.pyc'),'bounded-tar-v1','work-v1'),
    ToolchainAdapter('java','java-main-v1','Main.java',
        ('/usr/bin/javac','-encoding','UTF-8','-d','/work/artifact','/source/Main.java'),
        ('/usr/bin/java','-cp','/artifact','Main'),'bounded-tar-v1','work-v1'),
    ToolchainAdapter('javascript','node-check-v1','main.js',
        ('/usr/local/bin/node','--check','/source/main.js'),
        ('/usr/local/bin/node','/artifact/main.js'),'bounded-tar-v1','work-v1'),
    ToolchainAdapter('bpp','bpp-native-o1-v2-tmp-split','main.bpp',
        ('/bin/sh','-c',
         'bpp -O1 -asm /source/main.bpp > /work/program.asm && nasm -f elf64 -O1 /work/program.asm -o /work/program.o && ld /work/program.o -o /work/artifact/program'),
        ('/artifact/program',),'bounded-tar-v1','bpp-split-v1'),
)

_CURRENT = tuple(ToolchainAdapter(
    entry.language,
    {
        'c': 'c17-o2-pids-v2',
        'cpp': 'cpp17-o2-pids-v2',
        'python': 'cpython-pyc-pids-v2',
        'java': 'java-main-pids-v2',
        'javascript': 'node-check-pids-v2',
        'bpp': 'bpp-native-o1-v3-pids',
    }[entry.language],
    entry.source_name, entry.compile_command, entry.run_command,
    entry.artifact_contract, entry.scratch_layout, 'measured-container-v2',
) for entry in _HISTORICAL)

# Keep all historical entries here even after a new profile becomes current.
ADAPTERS = MappingProxyType({(entry.language,entry.profile):entry for entry in (*_HISTORICAL, *_CURRENT)})
CURRENT_TOOLCHAINS = MappingProxyType({entry.language:entry.profile for entry in _CURRENT})
SOURCE_NAMES = MappingProxyType({entry.language:entry.source_name for entry in _CURRENT})
EXPECTED_FINGERPRINTS = MappingProxyType({
    ('c','c17-o2-v1'):'sha256:9095a51e2e3ac6ef51c7e8a3b6427f7118046980214dd85bbaba22a97c76da1f',
    ('cpp','cpp17-o2-v1'):'sha256:27ca9c9770ff41e7f4aab594e16e71216fb7f706a2f4c28d9c6c8389e87f7c87',
    ('python','cpython-pyc-v1'):'sha256:ef1ed3e3140e4fe81c9ce9190fb86268966fbf7841be95d86996238579d5457b',
    ('java','java-main-v1'):'sha256:01f305decdf56dd27b421afa1ceaa69da9b92f13f9c625079d6532c55a98b4ca',
    ('javascript','node-check-v1'):'sha256:1863b3cae6fef7de7c01137a9fae847a7598859c02bc73302225539ce6b8f4ac',
    ('bpp','bpp-native-o1-v2-tmp-split'):'sha256:372146b142845757e177f7f7eade377e2280c12d1023b6b50b901f9837a7d4ec',
    ('c','c17-o2-pids-v2'):'sha256:6871b380e29e9eb0e5d9e49d1ce322cb58af09bd026bab4d8269d5caf46a7c67',
    ('cpp','cpp17-o2-pids-v2'):'sha256:79d7083c85c138b2e4955e1f809089042de1a5c0da6844f5ef2f96ac59ce162a',
    ('python','cpython-pyc-pids-v2'):'sha256:c773df0952dc6c9a38298a01c03d7d358c37242c4cb6df60c99fe5f54a1272f3',
    ('java','java-main-pids-v2'):'sha256:676e383fbd56ae5cc61653aa56cfd93addabe39549508f2ffb795e4fbe4f28b9',
    ('javascript','node-check-pids-v2'):'sha256:bf8bc2758df2f92ec7946066e91ed613c57952f9b4d9d9aff9c53516d093058b',
    ('bpp','bpp-native-o1-v3-pids'):'sha256:5aba1f945380de99c8e952b0a50220ab1259757f1c4e39a30716294ccc58f1ae',
})


def trusted_adapter(language, profile):
    if not isinstance(language,str) or not isinstance(profile,str):
        raise ValueError('Trusted toolchain identity required')
    try:
        entry=ADAPTERS[(language,profile)]
    except KeyError:
        raise ValueError('Unknown trusted toolchain profile') from None
    if entry.fingerprint()!=EXPECTED_FINGERPRINTS.get((language,profile)):
        raise ValueError('Trusted toolchain recipe changed without a new profile')
    return entry
