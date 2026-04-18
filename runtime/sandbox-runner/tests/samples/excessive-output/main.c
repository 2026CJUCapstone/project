#include <stdio.h>

int main(void) {
    int i;

    for (i = 0; i < 200000; i++) {
        puts("sandbox-output-line");
    }

    return 0;
}
