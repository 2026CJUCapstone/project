#include <stdio.h>

int main(void) {
    static char word[1000001];
    int counts[26] = {0};
    if (scanf("%1000000s", word) != 1) {
        return 1;
    }
    for (int index = 0; word[index] != '\0'; ++index) {
        unsigned char character = (unsigned char)word[index];
        if (character >= 'a' && character <= 'z') {
            character = (unsigned char)(character - ('a' - 'A'));
        }
        counts[character - 'A']++;
    }
    int best_count = -1;
    int best_letter = -1;
    int tied = 0;
    for (int index = 0; index < 26; ++index) {
        if (counts[index] > best_count) {
            best_count = counts[index];
            best_letter = index;
            tied = 0;
        } else if (counts[index] == best_count) {
            tied = 1;
        }
    }
    if (tied) {
        puts("?");
    } else {
        printf("%c\n", 'A' + best_letter);
    }
    return 0;
}
