import java.io.BufferedInputStream;

public class Main {
    private static final BufferedInputStream INPUT = new BufferedInputStream(System.in);

    private static int nextInt() throws Exception {
        int character;
        do {
            character = INPUT.read();
        } while (character <= ' ');
        int sign = 1;
        if (character == '-' || character == '+') {
            sign = character == '-' ? -1 : 1;
            character = INPUT.read();
        }
        int value = 0;
        while (character > ' ') {
            value = value * 10 + character - '0';
            character = INPUT.read();
        }
        return value * sign;
    }

    private static String next() throws Exception {
        int character;
        do {
            character = INPUT.read();
        } while (character <= ' ');
        StringBuilder token = new StringBuilder();
        while (character > ' ') {
            token.append((char) character);
            character = INPUT.read();
        }
        return token.toString();
    }

    public static void main(String[] args) throws Exception {
        int rows = nextInt();
        int columns = nextInt();
        char[][] grid = new char[rows][];
        for (int row = 0; row < rows; row++) {
            grid[row] = next().toCharArray();
        }
        int[] distances = new int[rows * columns];
        int[] queue = new int[rows * columns];
        int head = 0;
        int tail = 0;
        queue[tail++] = 0;
        distances[0] = 1;
        int[] rowChange = {-1, 1, 0, 0};
        int[] columnChange = {0, 0, -1, 1};
        while (head < tail) {
            int current = queue[head++];
            if (current == rows * columns - 1) {
                break;
            }
            int row = current / columns;
            int column = current % columns;
            for (int direction = 0; direction < 4; direction++) {
                int nextRow = row + rowChange[direction];
                int nextColumn = column + columnChange[direction];
                if (nextRow < 0 || nextRow >= rows || nextColumn < 0 || nextColumn >= columns) {
                    continue;
                }
                int next = nextRow * columns + nextColumn;
                if (grid[nextRow][nextColumn] == '1' && distances[next] == 0) {
                    distances[next] = distances[current] + 1;
                    queue[tail++] = next;
                }
            }
        }
        System.out.println(distances[rows * columns - 1]);
    }
}
