import java.io.BufferedInputStream;
import java.util.Arrays;

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
        int count = nextInt();
        int[] processingTimes = new int[count];
        for (int index = 0; index < count; index++) {
            processingTimes[index] = nextInt();
        }
        Arrays.sort(processingTimes);
        long elapsed = 0;
        long total = 0;
        for (int processingTime : processingTimes) {
            elapsed += processingTime;
            total += elapsed;
        }
        System.out.println(total);
    }
}
