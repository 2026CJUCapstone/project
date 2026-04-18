#include <errno.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    FILE *fp = fopen("/etc/passwd", "r");

    if (fp == NULL) {
        fprintf(stderr, "fopen failed: %s\n", strerror(errno));
        return 1;
    }

    puts("unexpectedly opened forbidden file");
    fclose(fp);
    return 0;
}
