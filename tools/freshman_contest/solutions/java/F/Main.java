import java.io.BufferedInputStream;
import java.util.HashSet;
import java.util.Set;

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
        long value = 0;
        while (character > ' ') {
            value = value * 10 + character - '0';
            character = INPUT.read();
        }
        return (int) (sign * value);
    }

    public static void main(String[] args) throws Exception {
        int registrationCount = nextInt();
        Set<Integer> registrations = new HashSet<>(registrationCount * 2);
        for (int index = 0; index < registrationCount; index++) {
            registrations.add(nextInt());
        }
        int queryCount = nextInt();
        StringBuilder output = new StringBuilder(queryCount * 2);
        for (int index = 0; index < queryCount; index++) {
            output.append(registrations.contains(nextInt()) ? '1' : '0').append('\n');
        }
        System.out.print(output);
    }
}
