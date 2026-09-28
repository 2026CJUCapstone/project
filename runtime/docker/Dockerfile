FROM node:24-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS node-runtime
FROM ubuntu:26.04@sha256:513c074113a871b51a8d16ab445c88779d6452d937a164fb5cc479f32668a41d AS bpp-build

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
      libatomic1 \
      libstdc++6 \
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
        libatomic1 \
        libstdc++6 \
        default-jdk-headless \
        nasm \
        make; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# Use the pinned glibc build, not Alpine's musl binary or a mutable setup script.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
# The Node24 image bundles npm12 with vulnerable transitive packages. Install
# the compatible npm11 release whose complete bundled tree includes the fixes.
# Verify the exact upstream artifact before extracting or executing anything.
RUN curl --fail --silent --show-error --location --retry 3 \
      https://registry.npmjs.org/npm/-/npm-11.19.1.tgz -o /tmp/npm.tgz \
    && printf '%s  %s\n' 9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0 /tmp/npm.tgz | sha256sum --check --strict \
    && mkdir -p /usr/local/lib/node_modules/npm \
    && tar -xzf /tmp/npm.tgz --strip-components=1 -C /usr/local/lib/node_modules/npm \
    && rm /tmp/npm.tgz
RUN set -eux; \
    ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm; \
    ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx; \
    ln -s node /usr/local/bin/nodejs; \
    test "$(node --version)" = v24.21.0; \
    ldd /usr/local/bin/node > /tmp/node-libraries.txt; \
    ! grep -q 'not found' /tmp/node-libraries.txt; \
    rm /tmp/node-libraries.txt; \
    test "$(npm --version)" = 11.19.1; \
    printf '40 2\n' | node -e 'const fs=require("node:fs"); const values=fs.readFileSync(0,"utf8").trim().split(/\s+/).map(Number); if(values[0]+values[1]!==42) process.exit(1)'

ARG BPP_REPO=https://github.com/Creeper0809/Bpp
ARG BPP_REF=main
ARG BPP_BOOTSTRAP_TAG
ARG BPP_BOOTSTRAP_URL
ARG BPP_BOOTSTRAP_SHA256
ARG TEST_SKIP_LLVM_BUILD=1
ARG TEST_FAST_IO=0
ARG BPP_TEST_NAME_FILTER="14_print_anything_success|43_language_feature_runtime_bundle_success"
ARG RUNTIME_BUILD_SIGNATURE=unknown
ARG RUNTIME_SOURCE_DIGEST=unknown
ARG WEB_SOURCE_SHA=unknown

LABEL org.opencontainers.image.source="${BPP_REPO}"
LABEL io.bpp.repo="${BPP_REPO}"
LABEL io.bpp.ref="${BPP_REF}"
LABEL io.bpp.bootstrap.tag="${BPP_BOOTSTRAP_TAG}"
LABEL io.bpp.bootstrap.url="${BPP_BOOTSTRAP_URL}"
LABEL io.bpp.bootstrap.sha256="${BPP_BOOTSTRAP_SHA256}"
LABEL io.bpp.test_skip_llvm_build="${TEST_SKIP_LLVM_BUILD}"
LABEL io.bpp.test_fast_io="${TEST_FAST_IO}"
LABEL io.bpp.test_name_filter="${BPP_TEST_NAME_FILTER}"
LABEL io.bpp.runtime_build_signature="${RUNTIME_BUILD_SIGNATURE}"
LABEL io.bpp.runtime_source_digest="${RUNTIME_SOURCE_DIGEST}"
LABEL io.webcompiler.source-sha="${WEB_SOURCE_SHA}"
LABEL io.webcompiler.image-role="sandbox"

ENV BPP_REPO="${BPP_REPO}"
ENV BPP_REF="${BPP_REF}"
ENV BPP_BOOTSTRAP_TAG="${BPP_BOOTSTRAP_TAG}"
ENV BPP_BOOTSTRAP_URL="${BPP_BOOTSTRAP_URL}"
ENV BPP_BOOTSTRAP_SHA256="${BPP_BOOTSTRAP_SHA256}"
ENV TEST_SKIP_LLVM_BUILD="${TEST_SKIP_LLVM_BUILD}"
ENV TEST_FAST_IO="${TEST_FAST_IO}"
ENV BPP_TEST_NAME_FILTER="${BPP_TEST_NAME_FILTER}"
ENV RUNTIME_BUILD_SIGNATURE="${RUNTIME_BUILD_SIGNATURE}"

COPY compiler-patches /opt/compiler-patches
RUN set -eux; \
    git clone "$BPP_REPO" /opt/Bpp; \
    cd /opt/Bpp; \
    git checkout "$BPP_REF"; \
    python3 /opt/compiler-patches/apply_exploration.py /opt/Bpp; \
    cmake_args="-DCMAKE_INSTALL_PREFIX=/usr/local"; \
    if [ -n "$BPP_BOOTSTRAP_TAG" ]; then \
      cmake_args="$cmake_args -DBPP_BOOTSTRAP_RELEASE_TAG=$BPP_BOOTSTRAP_TAG"; \
    fi; \
    if [ -n "$BPP_BOOTSTRAP_SHA256" ]; then \
      cmake_args="$cmake_args -DBPP_BOOTSTRAP_SHA256_LINUX=$BPP_BOOTSTRAP_SHA256"; \
    fi; \
    cmake -S . -B build-linux $cmake_args; \
    TEST_NAME_FILTER="$BPP_TEST_NAME_FILTER" cmake --build build-linux --target bpp-selfhost-fast; \
    cmake --install build-linux; \
    printf 'install_mode=source\nrepo=%s\nref=%s\nbootstrap_tag=%s\nbootstrap_url=%s\nbootstrap_sha256=%s\ntest_skip_llvm_build=%s\ntest_fast_io=%s\ntest_name_filter=%s\nruntime_build_signature=%s\n' \
      "$BPP_REPO" "$BPP_REF" "$BPP_BOOTSTRAP_TAG" "$BPP_BOOTSTRAP_URL" "$BPP_BOOTSTRAP_SHA256" "$TEST_SKIP_LLVM_BUILD" "$TEST_FAST_IO" "$BPP_TEST_NAME_FILTER" "$RUNTIME_BUILD_SIGNATURE" > /usr/local/share/bpp-build-info.txt; \
    rm -rf /opt/Bpp/.git

# B++ is a freestanding ELF. Keep its bootstrap/build dependencies out of the
# submitted-code runtime; never copy glibc executables into the musl image.
RUN readelf -l /usr/local/libexec/bpp/v13_stage1 > /tmp/bpp-elf.txt \
    && ! grep -q INTERP /tmp/bpp-elf.txt \
    && rm /tmp/bpp-elf.txt

# Submission runtime: this stage is also exercised by the bounded Node probe.
FROM node:24.21.0-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS sandbox-runtime
RUN apk add --no-cache bash binutils ca-certificates coreutils python3 \
      gcc g++ musl-dev linux-headers openjdk25-jdk nasm make \
    && rm -rf /usr/local/lib/node_modules/npm
COPY --from=bpp-build /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=bpp-build /usr/local/bin/bpp /usr/local/bin/bpp
COPY --from=bpp-build /usr/local/libexec/bpp /usr/local/libexec/bpp
COPY --from=bpp-build /usr/local/share/bpp /usr/local/share/bpp
COPY --from=bpp-build /usr/local/share/bpp-build-info.txt /usr/local/share/bpp-build-info.txt

ARG BPP_REPO=https://github.com/Creeper0809/Bpp
ARG BPP_REF=main
ARG BPP_BOOTSTRAP_TAG
ARG BPP_BOOTSTRAP_URL
ARG BPP_BOOTSTRAP_SHA256
ARG TEST_SKIP_LLVM_BUILD=1
ARG TEST_FAST_IO=0
ARG BPP_TEST_NAME_FILTER="14_print_anything_success|43_language_feature_runtime_bundle_success"
ARG RUNTIME_BUILD_SIGNATURE=unknown
ARG RUNTIME_SOURCE_DIGEST=unknown
ARG WEB_SOURCE_SHA=unknown

LABEL org.opencontainers.image.source="${BPP_REPO}"
LABEL io.bpp.repo="${BPP_REPO}"
LABEL io.bpp.ref="${BPP_REF}"
LABEL io.bpp.bootstrap.tag="${BPP_BOOTSTRAP_TAG}"
LABEL io.bpp.bootstrap.url="${BPP_BOOTSTRAP_URL}"
LABEL io.bpp.bootstrap.sha256="${BPP_BOOTSTRAP_SHA256}"
LABEL io.bpp.test_skip_llvm_build="${TEST_SKIP_LLVM_BUILD}"
LABEL io.bpp.test_fast_io="${TEST_FAST_IO}"
LABEL io.bpp.test_name_filter="${BPP_TEST_NAME_FILTER}"
LABEL io.bpp.runtime_build_signature="${RUNTIME_BUILD_SIGNATURE}"
LABEL io.bpp.runtime_source_digest="${RUNTIME_SOURCE_DIGEST}"
LABEL io.webcompiler.source-sha="${WEB_SOURCE_SHA}"
LABEL io.webcompiler.image-role="sandbox"

ENV BPP_REPO="${BPP_REPO}" BPP_REF="${BPP_REF}" \
    BPP_BOOTSTRAP_TAG="${BPP_BOOTSTRAP_TAG}" BPP_BOOTSTRAP_URL="${BPP_BOOTSTRAP_URL}" \
    BPP_BOOTSTRAP_SHA256="${BPP_BOOTSTRAP_SHA256}" TEST_SKIP_LLVM_BUILD="${TEST_SKIP_LLVM_BUILD}" \
    TEST_FAST_IO="${TEST_FAST_IO}" RUNTIME_BUILD_SIGNATURE="${RUNTIME_BUILD_SIGNATURE}"

WORKDIR /sandbox

COPY sandbox/run.sh /usr/local/bin/run.sh
COPY sandbox/verify_bpp_runtime.py /usr/local/share/verify_bpp_runtime.py
COPY sandbox/verify_bpp_exploration.py /usr/local/share/verify_bpp_exploration.py
COPY sandbox/verify_bpp_latency.py /usr/local/share/verify_bpp_latency.py
RUN chmod +x /usr/local/bin/run.sh

RUN deluser node \
    && addgroup -g 1000 sandboxuser \
    && adduser -D -u 1000 -G sandboxuser -s /bin/bash sandboxuser
USER sandboxuser

# These installed-compiler checks are mandatory even when the bootstrap test
# filter is customized. They reproduce the G/J failures found in Linux testing.
RUN python3 -I /usr/local/share/verify_bpp_runtime.py
RUN python3 -I /usr/local/share/verify_bpp_exploration.py
RUN python3 -I /usr/local/share/verify_bpp_latency.py

# Check executable/read permissions as the actual submission user as well.
RUN test "$(nodejs --version)" = v24.21.0 \
    && npm --version \
    && npx --version \
    && printf '40 2\n' | node -e 'const fs=require("node:fs"); const values=fs.readFileSync(0,"utf8").trim().split(/\s+/).map(Number); if(values[0]+values[1]!==42) process.exit(1)'

ENTRYPOINT ["/usr/local/bin/run.sh"]
