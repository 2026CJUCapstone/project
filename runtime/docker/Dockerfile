# B++ runtime sandbox image
FROM ubuntu:22.04

# B++ runtime requirements
RUN apt-get update && apt-get install -y \
    bash \
    binutils \
    ca-certificates \
    nasm \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Runtime working directory
WORKDIR /sandbox

# Runtime scripts and sandbox-runner
COPY sandbox-runner /opt/project/runtime/sandbox-runner
COPY sandbox/run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/project/runtime/sandbox-runner
ENV BPP_EXECUTABLE=/usr/local/bin/bpp

# The actual B++ compiler launcher/binary should be provided by a higher-level image
# stage or mounted into the container at runtime.

# Non-root execution
RUN useradd -ms /bin/bash sandboxuser
USER sandboxuser

ENTRYPOINT ["/usr/local/bin/run.sh"]
