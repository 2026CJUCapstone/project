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
        int[] counts = new int[26];
        String word = next();
        for (int index = 0; index < word.length(); index++) {
            char character = word.charAt(index);
            if (character >= 'a' && character <= 'z') {
                character -= 'a' - 'A';
            }
            counts[character - 'A']++;
        }
        int bestCount = -1;
        int bestLetter = -1;
        boolean tied = false;
        for (int index = 0; index < counts.length; index++) {
            if (counts[index] > bestCount) {
                bestCount = counts[index];
                bestLetter = index;
                tied = false;
            } else if (counts[index] == bestCount) {
                tied = true;
            }
        }
        System.out.println(tied ? "?" : (char) ('A' + bestLetter));
    }
}
