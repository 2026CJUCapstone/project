#include <stdio.h>

int main(void) {
    fputs("intentional runtime error\n", stderr);
    return 1;
}
