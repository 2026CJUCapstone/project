#include <stdio.h>

int main(void) {
    int rows;
    int columns;
    static char grid[100][101];
    static int distances[100][100];
    int queue[10000];
    int head = 0;
    int tail = 0;
    const int row_change[4] = {-1, 1, 0, 0};
    const int column_change[4] = {0, 0, -1, 1};

    if (scanf("%d %d", &rows, &columns) != 2) {
        return 1;
    }
    for (int row = 0; row < rows; ++row) {
        if (scanf("%100s", grid[row]) != 1) {
            return 1;
        }
    }
    queue[tail++] = 0;
    distances[0][0] = 1;
    while (head < tail) {
        int current = queue[head++];
        int row = current / columns;
        int column = current % columns;
        if (current == rows * columns - 1) {
            break;
        }
        for (int direction = 0; direction < 4; ++direction) {
            int next_row = row + row_change[direction];
            int next_column = column + column_change[direction];
            if (next_row < 0 || next_row >= rows || next_column < 0 || next_column >= columns) {
                continue;
            }
            if (grid[next_row][next_column] == '1' && distances[next_row][next_column] == 0) {
                distances[next_row][next_column] = distances[row][column] + 1;
                queue[tail++] = next_row * columns + next_column;
            }
        }
    }
    printf("%d\n", distances[rows - 1][columns - 1]);
    return 0;
}
