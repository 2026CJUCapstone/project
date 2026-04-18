#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void) {
    int i;

    for (i = 0; i < 128; i++) {
        pid_t pid = fork();

        if (pid < 0) {
            perror("fork");
            return 1;
        }

        if (pid == 0) {
            sleep(5);
            return 0;
        }
    }

    while (wait(NULL) > 0) {
    }

    return 0;
}
