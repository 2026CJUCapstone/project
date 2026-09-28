#include <stdio.h>

int main(void) {
    int count;
    int minimum;
    int maximum;
    if (scanf("%d", &count) != 1 || scanf("%d", &minimum) != 1) {
        return 1;
    }
    maximum = minimum;
    for (int index = 1; index < count; ++index) {
        int value;
        if (scanf("%d", &value) != 1) {
            return 1;
        }
        if (value < minimum) {
            minimum = value;
        }
        if (value > maximum) {
            maximum = value;
        }
    }
    printf("%d %d\n", minimum, maximum);
    return 0;
}
