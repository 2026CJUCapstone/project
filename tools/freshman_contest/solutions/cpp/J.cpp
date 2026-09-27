// Independently derived periodic inversion solution; see banks-reference-proof.
#include <algorithm>
#include <iostream>
#include <vector>

using i64 = long long;

struct Fenwick {
    std::vector<int> tree;
    explicit Fenwick(int size) : tree(size + 1, 0) {}
    void add(int index) {
        for (++index; index < static_cast<int>(tree.size()); index += index & -index)
            ++tree[index];
    }
    i64 before(int index) const {
        i64 count = 0;
        for (; index > 0; index -= index & -index) count += tree[index];
        return count;
    }
};

int main() {
    int n;
    if (!(std::cin >> n)) return 1;
    std::vector<i64> prefixes;
    i64 total = 0;
    for (int i = 0; i < n; ++i) {
        i64 value;
        std::cin >> value;
        prefixes.push_back(total);
        total += value;
    }
    if (n < 1 || total <= 0) return 1;
    auto residue = [total](i64 value) {
        i64 result = value % total;
        return result < 0 ? result + total : result;
    };
    std::vector<i64> residues;
    for (auto value : prefixes) residues.push_back(residue(value));
    std::sort(residues.begin(), residues.end());
    residues.erase(std::unique(residues.begin(), residues.end()), residues.end());
    auto sorted = prefixes;
    std::sort(sorted.begin(), sorted.end());
    Fenwick counts(static_cast<int>(residues.size()));
    i64 answer = 0, quotient_sum = 0;
    for (int i = 0; i < n; ++i) {
        i64 remainder = residue(sorted[i]);
        // C++ division truncates toward zero; subtract the nonnegative residue
        // first so this is floor division even for negative prefixes.
        i64 quotient = (sorted[i] - remainder) / total;
        int rank = static_cast<int>(std::lower_bound(residues.begin(), residues.end(), remainder) - residues.begin());
        answer += static_cast<i64>(i) * quotient - quotient_sum + counts.before(rank);
        quotient_sum += quotient;
        counts.add(rank);
    }
    sorted.erase(std::unique(sorted.begin(), sorted.end()), sorted.end());
    Fenwick increasing(static_cast<int>(sorted.size()));
    for (auto value : prefixes) {
        int rank = static_cast<int>(std::lower_bound(sorted.begin(), sorted.end(), value) - sorted.begin());
        answer -= increasing.before(rank);
        increasing.add(rank);
    }
    std::cout << answer << '\n';
}
