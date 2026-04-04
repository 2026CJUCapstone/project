#include <stdio.h>

int main(void) {
    int *ptr = NULL;
    fputs("about to segfault\n", stderr);
    *ptr = 42;
    return 0;
}
