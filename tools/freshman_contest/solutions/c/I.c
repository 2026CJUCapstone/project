#include <stdio.h>

int main(void) {
    enum { MAX_CELLS = 1000000 };
    static int cells[MAX_CELLS];
    static int queue[MAX_CELLS];
    int columns;
    int rows;
    int head = 0;
    int tail = 0;
    int remaining = 0;
    const int row_change[4] = {-1, 1, 0, 0};
    const int column_change[4] = {0, 0, -1, 1};

    if (scanf("%d %d", &columns, &rows) != 2) {
        return 1;
    }
    int cell_count = rows * columns;
    for (int position = 0; position < cell_count; ++position) {
        if (scanf("%d", &cells[position]) != 1) {
            return 1;
        }
        if (cells[position] == 1) {
            queue[tail++] = position;
        } else if (cells[position] == 0) {
            ++remaining;
        }
    }
    if (remaining == 0) {
        puts("0");
        return 0;
    }
    int days = 0;
    while (head < tail && remaining > 0) {
        int today_end = tail;
        while (head < today_end) {
            int current = queue[head++];
            int row = current / columns;
            int column = current % columns;
            for (int direction = 0; direction < 4; ++direction) {
                int next_row = row + row_change[direction];
                int next_column = column + column_change[direction];
                if (next_row < 0 || next_row >= rows || next_column < 0 || next_column >= columns) {
                    continue;
                }
                int next = next_row * columns + next_column;
                if (cells[next] == 0) {
                    cells[next] = 1;
                    --remaining;
                    queue[tail++] = next;
                }
            }
        }
        ++days;
    }
    printf("%d\n", remaining == 0 ? days : -1);
    return 0;
}
