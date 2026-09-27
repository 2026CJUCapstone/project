#include <iostream>

int main() {
    int counts[7] = {};
    for (int index = 0; index < 3; ++index) {
        int value;
        std::cin >> value;
        ++counts[value];
    }

    int repeated_value = 1;
    int highest_count = 0;
    for (int value = 1; value <= 6; ++value) {
        if (counts[value] >= highest_count) {
            highest_count = counts[value];
            repeated_value = value;
        }
    }

    if (highest_count == 3) {
        std::cout << 10000 + repeated_value * 1000 << '\n';
    } else if (highest_count == 2) {
        std::cout << 1000 + repeated_value * 100 << '\n';
    } else {
        std::cout << repeated_value * 100 << '\n';
    }
}
