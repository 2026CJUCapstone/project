#include <iostream>
#include <string>

int main() {
    int cases;
    std::cin >> cases;
    while (cases--) {
        int repeats;
        std::string phrase;
        std::cin >> repeats >> phrase;
        for (char character : phrase) {
            for (int count = 0; count < repeats; ++count) {
                std::cout << character;
            }
        }
        std::cout << '\n';
    }
}
