import java.io.BufferedInputStream;

public class Main {
    private static final BufferedInputStream INPUT = new BufferedInputStream(System.in);

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
        int cases = Integer.parseInt(next());
        StringBuilder output = new StringBuilder();
        for (int testCase = 0; testCase < cases; testCase++) {
            int repeats = Integer.parseInt(next());
            String phrase = next();
            for (int index = 0; index < phrase.length(); index++) {
                for (int repeat = 0; repeat < repeats; repeat++) {
                    output.append(phrase.charAt(index));
                }
            }
            output.append('\n');
        }
        System.out.print(output);
    }
}
