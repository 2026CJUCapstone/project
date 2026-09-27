#include <iostream>
#include <queue>
#include <string>
#include <vector>

int main() {
    int rows, columns;
    std::cin >> rows >> columns;
    std::vector<std::string> grid(rows);
    for (std::string& row : grid) {
        std::cin >> row;
    }

    std::vector<int> distance(rows * columns, -1);
    std::queue<int> queue;
    distance[0] = 1;
    queue.push(0);

    const int row_change[4] = {-1, 1, 0, 0};
    const int column_change[4] = {0, 0, -1, 1};
    while (!queue.empty()) {
        int current = queue.front();
        queue.pop();
        if (current == rows * columns - 1) {
            break;
        }

        int row = current / columns;
        int column = current % columns;
        for (int direction = 0; direction < 4; ++direction) {
            int next_row = row + row_change[direction];
            int next_column = column + column_change[direction];
            if (next_row < 0 || next_row >= rows || next_column < 0 || next_column >= columns) {
                continue;
            }
            int next = next_row * columns + next_column;
            if (grid[next_row][next_column] == '1' && distance[next] == -1) {
                distance[next] = distance[current] + 1;
                queue.push(next);
            }
        }
    }

    std::cout << distance.back() << '\n';
}
