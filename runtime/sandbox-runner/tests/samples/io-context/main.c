#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char cwd[4096];
    char input[128] = {0};

    if (getcwd(cwd, sizeof(cwd)) == NULL) {
        return 2;
    }

    if (fgets(input, sizeof(input), stdin) == NULL) {
        input[0] = '\0';
    }

    printf("cwd=%s\n", cwd);
    printf("argc=%d\n", argc);
    if (argc > 1) {
        printf("arg1=%s\n", argv[1]);
    }
    printf("stdin=%s", input);
    return 0;
}
