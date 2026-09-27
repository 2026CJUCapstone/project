#include <iostream>
#include <queue>
#include <vector>

int main() {
    int columns, rows;
    std::cin >> columns >> rows;

    std::vector<int> cells(rows * columns);
    std::queue<int> queue;
    int remaining = 0;
    for (int position = 0; position < rows * columns; ++position) {
        std::cin >> cells[position];
        if (cells[position] == 1) {
            queue.push(position);
        } else if (cells[position] == 0) {
            ++remaining;
        }
    }

    if (remaining == 0) {
        std::cout << "0\n";
        return 0;
    }

    const int row_change[4] = {-1, 1, 0, 0};
    const int column_change[4] = {0, 0, -1, 1};
    int days = 0;
    while (!queue.empty() && remaining > 0) {
        int today_count = static_cast<int>(queue.size());
        while (today_count--) {
            int current = queue.front();
            queue.pop();
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
                    queue.push(next);
                }
            }
        }
        ++days;
    }

    std::cout << (remaining == 0 ? days : -1) << '\n';
}
