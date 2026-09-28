#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static int compare_int64(const void *left, const void *right) {
    int64_t first = *(const int64_t *)left;
    int64_t second = *(const int64_t *)right;
    return (first > second) - (first < second);
}

int main(void) {
    enum { MAX_NUMBERS = 100000 };
    static int64_t registrations[MAX_NUMBERS];
    int count;
    if (scanf("%d", &count) != 1) {
        return 1;
    }
    for (int index = 0; index < count; ++index) {
        if (scanf("%" SCNd64, &registrations[index]) != 1) {
            return 1;
        }
    }
    qsort(registrations, (size_t)count, sizeof(registrations[0]), compare_int64);

    int query_count;
    if (scanf("%d", &query_count) != 1) {
        return 1;
    }
    for (int index = 0; index < query_count; ++index) {
        int64_t value;
        if (scanf("%" SCNd64, &value) != 1) {
            return 1;
        }
        printf("%d\n", bsearch(&value, registrations, (size_t)count, sizeof(registrations[0]), compare_int64) != NULL);
    }
    return 0;
}
