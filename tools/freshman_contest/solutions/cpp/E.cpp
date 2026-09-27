#include <iostream>
#include <string>

int main() {
    std::string text;
    std::cin >> text;

    int counts[26] = {};
    for (char character : text) {
        if (character >= 'a' && character <= 'z') {
            character = static_cast<char>(character - 'a' + 'A');
        }
        ++counts[character - 'A'];
    }

    int winner = 0;
    bool tied = false;
    for (int letter = 1; letter < 26; ++letter) {
        if (counts[letter] > counts[winner]) {
            winner = letter;
            tied = false;
        } else if (counts[letter] == counts[winner]) {
            tied = true;
        }
    }

    if (tied) {
        std::cout << "?\n";
    } else {
        std::cout << static_cast<char>('A' + winner) << '\n';
    }
}
