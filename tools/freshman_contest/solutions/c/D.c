#include <stdio.h>

int main(void) {
    int cases;
    if (scanf("%d", &cases) != 1) {
        return 1;
    }
    for (int test_case = 0; test_case < cases; ++test_case) {
        int repeats;
        char phrase[21];
        if (scanf("%d %20s", &repeats, phrase) != 2) {
            return 1;
        }
        for (int index = 0; phrase[index] != '\0'; ++index) {
            for (int repeat = 0; repeat < repeats; ++repeat) {
                putchar((unsigned char)phrase[index]);
            }
        }
        putchar('\n');
    }
    return 0;
}
