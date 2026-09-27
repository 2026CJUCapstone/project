#include <stdio.h>

int main(void) {
    int first_group;
    int second_group;
    if (scanf("%d %d", &first_group, &second_group) != 2) {
        return 1;
    }
    printf("%d\n", first_group + second_group);
    return 0;
}
