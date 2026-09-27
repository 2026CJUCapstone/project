// Independently derived periodic inversion solution; see banks-reference-proof.
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { MAX_BANKS = 9999 };

static int64_t prefixes[MAX_BANKS];
static int64_t sorted_prefixes[MAX_BANKS];
static int64_t remainders[MAX_BANKS];

static int compare_int64(const void *left, const void *right) {
    int64_t first = *(const int64_t *)left;
    int64_t second = *(const int64_t *)right;
    return (first > second) - (first < second);
}

static int lower_bound(const int64_t *values, int length, int64_t target) {
    int low = 0;
    int high = length;
    while (low < high) {
        int middle = low + (high - low) / 2;
        if (values[middle] < target) {
            low = middle + 1;
        } else {
            high = middle;
        }
    }
    return low;
}

static int unique_in_place(int64_t *values, int length) {
    if (length == 0) {
        return 0;
    }
    int unique_count = 1;
    for (int index = 1; index < length; ++index) {
        if (values[index] != values[unique_count - 1]) {
            values[unique_count++] = values[index];
        }
    }
    return unique_count;
}

static int64_t floor_divide(int64_t value, int64_t divisor) {
    int64_t quotient = value / divisor;
    int64_t remainder = value % divisor;
    return remainder < 0 ? quotient - 1 : quotient;
}

static int64_t floor_remainder(int64_t value, int64_t divisor) {
    int64_t remainder = value % divisor;
    return remainder < 0 ? remainder + divisor : remainder;
}

static void fenwick_add(int *tree, int size, int index) {
    for (++index; index <= size; index += index & -index) {
        ++tree[index];
    }
}

static int64_t fenwick_before(const int *tree, int index) {
    int64_t result = 0;
    for (; index > 0; index -= index & -index) {
        result += tree[index];
    }
    return result;
}

int main(void) {
    int count;
    if (scanf("%d", &count) != 1 || count < 1 || count > MAX_BANKS) {
        return 1;
    }
    int64_t total = 0;
    for (int index = 0; index < count; ++index) {
        int64_t value;
        if (scanf("%" SCNd64, &value) != 1) {
            return 1;
        }
        prefixes[index] = total;
        total += value;
    }
    if (total <= 0) {
        return 1;
    }

    for (int index = 0; index < count; ++index) {
        remainders[index] = floor_remainder(prefixes[index], total);
    }
    qsort(remainders, (size_t)count, sizeof(remainders[0]), compare_int64);
    int remainder_count = unique_in_place(remainders, count);

    memcpy(sorted_prefixes, prefixes, (size_t)count * sizeof(prefixes[0]));
    qsort(sorted_prefixes, (size_t)count, sizeof(sorted_prefixes[0]), compare_int64);
    int counts[MAX_BANKS + 1] = {0};
    int64_t quotient_sum = 0;
    int64_t answer = 0;
    for (int index = 0; index < count; ++index) {
        int64_t value = sorted_prefixes[index];
        int64_t quotient = floor_divide(value, total);
        int64_t remainder = floor_remainder(value, total);
        int rank = lower_bound(remainders, remainder_count, remainder);
        answer += (int64_t)index * quotient - quotient_sum + fenwick_before(counts, rank);
        quotient_sum += quotient;
        fenwick_add(counts, remainder_count, rank);
    }

    int prefix_value_count = unique_in_place(sorted_prefixes, count);
    memset(counts, 0, sizeof(counts));
    for (int index = 0; index < count; ++index) {
        int rank = lower_bound(sorted_prefixes, prefix_value_count, prefixes[index]);
        answer -= fenwick_before(counts, rank);
        fenwick_add(counts, prefix_value_count, rank);
    }
    printf("%" PRId64 "\n", answer);
    return 0;
}
