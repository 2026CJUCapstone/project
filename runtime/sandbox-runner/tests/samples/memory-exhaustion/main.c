#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    const size_t chunk_size = 16 * 1024 * 1024;
    void **blocks = NULL;
    size_t count = 0;

    for (;;) {
        void *block = malloc(chunk_size);
        void **next_blocks;

        if (block == NULL) {
            fprintf(stderr, "allocation failed after %zu chunks\n", count);
            return 1;
        }

        memset(block, 0xA5, chunk_size);

        next_blocks = realloc(blocks, sizeof(void *) * (count + 1));
        if (next_blocks == NULL) {
            fprintf(stderr, "tracking allocation failed after %zu chunks\n", count);
            return 1;
        }

        blocks = next_blocks;
        blocks[count] = block;
        count++;
    }
}
