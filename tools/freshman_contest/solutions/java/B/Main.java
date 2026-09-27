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
        int first = nextInt();
        int second = nextInt();
        int third = nextInt();
        if (first == second && second == third) {
            System.out.println(10_000 + first * 1_000);
        } else if (first == second || first == third) {
            System.out.println(1_000 + first * 100);
        } else if (second == third) {
            System.out.println(1_000 + second * 100);
        } else {
            System.out.println(Math.max(first, Math.max(second, third)) * 100);
        }
    }
}
