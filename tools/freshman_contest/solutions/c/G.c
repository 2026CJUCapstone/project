#include <stdio.h>
#include <stdlib.h>

static int compare_int(const void *left, const void *right) {
    int first = *(const int *)left;
    int second = *(const int *)right;
    return (first > second) - (first < second);
}

int main(void) {
    int count;
    int processing_times[1000];
    if (scanf("%d", &count) != 1) {
        return 1;
    }
    for (int index = 0; index < count; ++index) {
        if (scanf("%d", &processing_times[index]) != 1) {
            return 1;
        }
    }
    qsort(processing_times, (size_t)count, sizeof(processing_times[0]), compare_int);
    long long elapsed = 0;
    long long total = 0;
    for (int index = 0; index < count; ++index) {
        elapsed += processing_times[index];
        total += elapsed;
    }
    printf("%lld\n", total);
    return 0;
}
