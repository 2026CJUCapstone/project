#include <algorithm>
#include <iostream>
#include <vector>

int main() {
    int registration_count;
    std::cin >> registration_count;

    std::vector<long long> registrations(registration_count);
    for (int index = 0; index < registration_count; ++index) {
        std::cin >> registrations[index];
    }
    std::sort(registrations.begin(), registrations.end());

    int query_count;
    std::cin >> query_count;
    for (int index = 0; index < query_count; ++index) {
        long long number;
        std::cin >> number;
        std::cout << (std::binary_search(registrations.begin(), registrations.end(), number) ? 1 : 0) << '\n';
    }
}
