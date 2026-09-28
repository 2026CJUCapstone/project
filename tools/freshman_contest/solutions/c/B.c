#include <stdio.h>

int main(void) {
    int first;
    int second;
    int third;
    if (scanf("%d %d %d", &first, &second, &third) != 3) {
        return 1;
    }
    if (first == second && second == third) {
        printf("%d\n", 10000 + first * 1000);
    } else if (first == second || first == third) {
        printf("%d\n", 1000 + first * 100);
    } else if (second == third) {
        printf("%d\n", 1000 + second * 100);
    } else {
        int largest = first > second ? first : second;
        if (third > largest) {
            largest = third;
        }
        printf("%d\n", largest * 100);
    }
    return 0;
}
