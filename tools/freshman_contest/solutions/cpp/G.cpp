#include <algorithm>
#include <iostream>
#include <vector>

int main() {
    int count;
    std::cin >> count;
    std::vector<int> times(count);
    for (int& time : times) {
        std::cin >> time;
    }

    std::sort(times.begin(), times.end());
    long long elapsed = 0;
    long long total = 0;
    for (int time : times) {
        elapsed += time;
        total += elapsed;
    }
    std::cout << total << '\n';
}
