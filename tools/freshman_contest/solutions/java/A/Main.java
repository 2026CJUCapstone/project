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
        System.out.println(nextInt() + nextInt());
    }
}
