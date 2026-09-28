import java.io.BufferedInputStream;
import java.util.Arrays;

public class Main {
    private static final BufferedInputStream INPUT = new BufferedInputStream(System.in);

    private static final class Fenwick {
        private final int[] tree;

        Fenwick(int size) {
            tree = new int[size + 1];
        }

        void add(int index) {
            for (index++; index < tree.length; index += index & -index) {
                tree[index]++;
            }
        }

        long before(int index) {
            long result = 0;
            for (; index > 0; index -= index & -index) {
                result += tree[index];
            }
            return result;
        }
    }

    private static long nextLong() throws Exception {
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
        return sign * value;
    }

    private static int lowerBound(long[] values, int length, long target) {
        int low = 0;
        int high = length;
        while (low < high) {
            int middle = (low + high) >>> 1;
            if (values[middle] < target) {
                low = middle + 1;
            } else {
                high = middle;
            }
        }
        return low;
    }

    private static int uniqueInPlace(long[] values) {
        if (values.length == 0) {
            return 0;
        }
        int uniqueCount = 1;
        for (int index = 1; index < values.length; index++) {
            if (values[index] != values[uniqueCount - 1]) {
                values[uniqueCount++] = values[index];
            }
        }
        return uniqueCount;
    }

    public static void main(String[] args) throws Exception {
        int count = (int) nextLong();
        long[] prefixes = new long[count];
        long total = 0;
        for (int index = 0; index < count; index++) {
            prefixes[index] = total;
            total += nextLong();
        }

        long[] remainders = new long[count];
        for (int index = 0; index < count; index++) {
            remainders[index] = Math.floorMod(prefixes[index], total);
        }
        Arrays.sort(remainders);
        int remainderCount = uniqueInPlace(remainders);

        long[] sortedPrefixes = prefixes.clone();
        Arrays.sort(sortedPrefixes);
        Fenwick residueCounts = new Fenwick(remainderCount);
        long quotientSum = 0;
        long answer = 0;
        for (int index = 0; index < count; index++) {
            long value = sortedPrefixes[index];
            long quotient = Math.floorDiv(value, total);
            long remainder = Math.floorMod(value, total);
            int rank = lowerBound(remainders, remainderCount, remainder);
            answer += (long) index * quotient - quotientSum + residueCounts.before(rank);
            quotientSum += quotient;
            residueCounts.add(rank);
        }

        int prefixValueCount = uniqueInPlace(sortedPrefixes);
        Fenwick increasingCounts = new Fenwick(prefixValueCount);
        for (long value : prefixes) {
            int rank = lowerBound(sortedPrefixes, prefixValueCount, value);
            answer -= increasingCounts.before(rank);
            increasingCounts.add(rank);
        }
        System.out.println(answer);
    }
}
