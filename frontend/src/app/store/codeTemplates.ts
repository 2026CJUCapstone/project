import type { CompilerLanguage } from '../services/compilerApi';

export const CODE_TEMPLATES: Record<CompilerLanguage, string> = {
  bpp: `import emitln from std.io;

func main() -> u64 {
    emitln("Hello, World!");
    return 0;
}
`,
  cpp: `#include <iostream>

int main() {
    std::cout << "Hello, World!" << std::endl;
    return 0;
}
`,
  c: `#include <stdio.h>

int main(void) {
    printf("Hello, World!\\n");
    return 0;
}
`,
  python: `print("Hello, World!")
`,
  java: `public class Main {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}
`,
  javascript: `console.log("Hello, World!");
`,
};
