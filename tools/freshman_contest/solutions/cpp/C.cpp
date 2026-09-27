#include <algorithm>
#include <iostream>

int main() {
    int count;
    std::cin >> count;

    int value;
    std::cin >> value;
    int minimum = value;
    int maximum = value;
    for (int index = 1; index < count; ++index) {
        std::cin >> value;
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }

    std::cout << minimum << ' ' << maximum << '\n';
}
