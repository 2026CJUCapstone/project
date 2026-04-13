FROM ubuntu:22.04

ARG BPP_REPO=https://github.com/Creeper0809/Bpp
ARG BPP_REF=main
ARG BPP_BOOTSTRAP_TAG=bootstrap-v12
ARG BPP_BOOTSTRAP_URL
ARG BPP_BOOTSTRAP_SHA256

LABEL org.opencontainers.image.source="${BPP_REPO}"
LABEL io.bpp.repo="${BPP_REPO}"
LABEL io.bpp.ref="${BPP_REF}"
LABEL io.bpp.bootstrap.tag="${BPP_BOOTSTRAP_TAG}"
LABEL io.bpp.bootstrap.url="${BPP_BOOTSTRAP_URL}"
LABEL io.bpp.bootstrap.sha256="${BPP_BOOTSTRAP_SHA256}"

ENV BPP_REPO="${BPP_REPO}"
ENV BPP_REF="${BPP_REF}"
ENV BPP_BOOTSTRAP_TAG="${BPP_BOOTSTRAP_TAG}"
ENV BPP_BOOTSTRAP_URL="${BPP_BOOTSTRAP_URL}"
ENV BPP_BOOTSTRAP_SHA256="${BPP_BOOTSTRAP_SHA256}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils \
    ca-certificates \
    cmake \
    python3 \
    python3-pip \
    git \
    gcc \
    g++ \
    default-jdk-headless \
    nasm \
    make \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN git clone "$BPP_REPO" /opt/Bpp \
    && cd /opt/Bpp \
    && git checkout "$BPP_REF" \
    && cmake -S . -B build-linux \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
      -DBPP_BOOTSTRAP_RELEASE_TAG="$BPP_BOOTSTRAP_TAG" \
      -DBPP_BOOTSTRAP_SHA256_LINUX="$BPP_BOOTSTRAP_SHA256" \
    && TEST_FAST_IO=0 TEST_QUIET=1 TEST_JOBS=4 cmake --build build-linux --target bpp-selfhost-fast \
    && cmake --install build-linux \
    && printf 'repo=%s\nref=%s\nbootstrap_tag=%s\nbootstrap_url=%s\nbootstrap_sha256=%s\n' \
      "$BPP_REPO" "$BPP_REF" "$BPP_BOOTSTRAP_TAG" "$BPP_BOOTSTRAP_URL" "$BPP_BOOTSTRAP_SHA256" > /usr/local/share/bpp-build-info.txt \
    && rm -rf /opt/Bpp/.git

WORKDIR /sandbox

COPY sandbox/run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

RUN useradd -ms /bin/bash sandboxuser
USER sandboxuser

ENTRYPOINT ["/usr/local/bin/run.sh"]
