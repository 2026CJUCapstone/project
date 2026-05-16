FROM ubuntu:24.04

ARG BPP_REPO=https://github.com/Creeper0809/Bpp
ARG BPP_REF=main
ARG BPP_BOOTSTRAP_TAG=bootstrap-v12
ARG BPP_BOOTSTRAP_URL
ARG BPP_BOOTSTRAP_SHA256
ARG BPP_USE_RELEASE_BINARY=1
ARG BPP_RELEASE_TAG
ARG BPP_RELEASE_BINARY_URL
ARG BPP_RELEASE_BINARY_SHA256
ARG TEST_SKIP_LLVM_BUILD=1
ARG TEST_FAST_IO=0
ARG RUNTIME_BUILD_SIGNATURE=unknown

LABEL org.opencontainers.image.source="${BPP_REPO}"
LABEL io.bpp.repo="${BPP_REPO}"
LABEL io.bpp.ref="${BPP_REF}"
LABEL io.bpp.bootstrap.tag="${BPP_BOOTSTRAP_TAG}"
LABEL io.bpp.bootstrap.url="${BPP_BOOTSTRAP_URL}"
LABEL io.bpp.bootstrap.sha256="${BPP_BOOTSTRAP_SHA256}"
LABEL io.bpp.release.tag="${BPP_RELEASE_TAG}"
LABEL io.bpp.release.binary.url="${BPP_RELEASE_BINARY_URL}"
LABEL io.bpp.test_skip_llvm_build="${TEST_SKIP_LLVM_BUILD}"
LABEL io.bpp.test_fast_io="${TEST_FAST_IO}"
LABEL io.bpp.runtime_build_signature="${RUNTIME_BUILD_SIGNATURE}"

ENV BPP_REPO="${BPP_REPO}"
ENV BPP_REF="${BPP_REF}"
ENV BPP_BOOTSTRAP_TAG="${BPP_BOOTSTRAP_TAG}"
ENV BPP_BOOTSTRAP_URL="${BPP_BOOTSTRAP_URL}"
ENV BPP_BOOTSTRAP_SHA256="${BPP_BOOTSTRAP_SHA256}"
ENV BPP_USE_RELEASE_BINARY="${BPP_USE_RELEASE_BINARY}"
ENV BPP_RELEASE_TAG="${BPP_RELEASE_TAG}"
ENV BPP_RELEASE_BINARY_URL="${BPP_RELEASE_BINARY_URL}"
ENV BPP_RELEASE_BINARY_SHA256="${BPP_RELEASE_BINARY_SHA256}"
ENV TEST_SKIP_LLVM_BUILD="${TEST_SKIP_LLVM_BUILD}"
ENV TEST_FAST_IO="${TEST_FAST_IO}"
ENV RUNTIME_BUILD_SIGNATURE="${RUNTIME_BUILD_SIGNATURE}"

RUN set -eux; \
    if ! (apt-get update -o Acquire::Retries=3 && apt-get install -y --no-install-recommends \
      binutils \
      ca-certificates \
      clang \
      curl \
      cmake \
      coreutils \
      python3 \
      python3-pip \
      git \
      gcc \
      g++ \
      default-jdk-headless \
      nasm \
      make); then \
      rm -rf /var/lib/apt/lists/*; \
      apt-get update -o Acquire::Retries=3; \
      apt-get install -y --no-install-recommends \
        binutils \
        ca-certificates \
        clang \
        curl \
        cmake \
        coreutils \
        python3 \
        python3-pip \
        git \
        gcc \
        g++ \
        default-jdk-headless \
        nasm \
        make; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# Node.js 20.x via NodeSource
RUN set -eux; \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; \
    if ! apt-get install -y --no-install-recommends nodejs; then \
      rm -rf /var/lib/apt/lists/*; \
      apt-get update -o Acquire::Retries=3; \
      apt-get install -y --no-install-recommends nodejs; \
    fi; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    if [[ "$BPP_USE_RELEASE_BINARY" == "1" ]]; then \
      if [[ -z "$BPP_RELEASE_BINARY_URL" ]]; then \
        echo "BPP_RELEASE_BINARY_URL is required when BPP_USE_RELEASE_BINARY=1" >&2; \
        exit 1; \
      fi; \
      curl -fsSL "$BPP_RELEASE_BINARY_URL" -o /tmp/bpp; \
      if [[ -n "$BPP_RELEASE_BINARY_SHA256" ]]; then \
        echo "$BPP_RELEASE_BINARY_SHA256  /tmp/bpp" | sha256sum -c -; \
      fi; \
      install -m 0755 /tmp/bpp /usr/local/bin/bpp; \
      rm -f /tmp/bpp; \
      printf 'install_mode=release\nrelease_tag=%s\nrelease_binary_url=%s\nrelease_binary_sha256=%s\nrepo=%s\nref=%s\nbootstrap_tag=%s\nbootstrap_url=%s\nbootstrap_sha256=%s\ntest_skip_llvm_build=%s\ntest_fast_io=%s\nruntime_build_signature=%s\n' \
        "$BPP_RELEASE_TAG" "$BPP_RELEASE_BINARY_URL" "$BPP_RELEASE_BINARY_SHA256" "$BPP_REPO" "$BPP_REF" "$BPP_BOOTSTRAP_TAG" "$BPP_BOOTSTRAP_URL" "$BPP_BOOTSTRAP_SHA256" "$TEST_SKIP_LLVM_BUILD" "$TEST_FAST_IO" "$RUNTIME_BUILD_SIGNATURE" > /usr/local/share/bpp-build-info.txt; \
    else \
      git clone "$BPP_REPO" /opt/Bpp; \
      cd /opt/Bpp; \
      git checkout "$BPP_REF"; \
      cmake -S . -B build-linux \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DBPP_BOOTSTRAP_RELEASE_TAG="$BPP_BOOTSTRAP_TAG" \
        -DBPP_BOOTSTRAP_SHA256_LINUX="$BPP_BOOTSTRAP_SHA256"; \
      cmake --build build-linux --target bpp-selfhost-fast; \
      cmake --install build-linux; \
      printf 'install_mode=source\nrepo=%s\nref=%s\nbootstrap_tag=%s\nbootstrap_url=%s\nbootstrap_sha256=%s\ntest_skip_llvm_build=%s\ntest_fast_io=%s\nruntime_build_signature=%s\n' \
        "$BPP_REPO" "$BPP_REF" "$BPP_BOOTSTRAP_TAG" "$BPP_BOOTSTRAP_URL" "$BPP_BOOTSTRAP_SHA256" "$TEST_SKIP_LLVM_BUILD" "$TEST_FAST_IO" "$RUNTIME_BUILD_SIGNATURE" > /usr/local/share/bpp-build-info.txt; \
      rm -rf /opt/Bpp/.git; \
    fi

WORKDIR /sandbox

COPY sandbox/run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

RUN useradd -ms /bin/bash sandboxuser
USER sandboxuser

ENTRYPOINT ["/usr/local/bin/run.sh"]
