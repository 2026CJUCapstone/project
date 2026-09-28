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

    public static void main(String[] args) throws Exception {
        int columns = nextInt();
        int rows = nextInt();
        int cellCount = rows * columns;
        int[] cells = new int[cellCount];
        int[] queue = new int[cellCount];
        int head = 0;
        int tail = 0;
        int remaining = 0;
        for (int position = 0; position < cellCount; position++) {
            cells[position] = nextInt();
            if (cells[position] == 1) {
                queue[tail++] = position;
            } else if (cells[position] == 0) {
                remaining++;
            }
        }
        if (remaining == 0) {
            System.out.println(0);
            return;
        }
        int[] rowChange = {-1, 1, 0, 0};
        int[] columnChange = {0, 0, -1, 1};
        int days = 0;
        while (head < tail && remaining > 0) {
            int todayEnd = tail;
            while (head < todayEnd) {
                int current = queue[head++];
                int row = current / columns;
                int column = current % columns;
                for (int direction = 0; direction < 4; direction++) {
                    int nextRow = row + rowChange[direction];
                    int nextColumn = column + columnChange[direction];
                    if (nextRow < 0 || nextRow >= rows || nextColumn < 0 || nextColumn >= columns) {
                        continue;
                    }
                    int next = nextRow * columns + nextColumn;
                    if (cells[next] == 0) {
                        cells[next] = 1;
                        remaining--;
                        queue[tail++] = next;
                    }
                }
            }
            days++;
        }
        System.out.println(remaining == 0 ? days : -1);
    }
}
