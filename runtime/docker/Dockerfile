# 기본 샌드박스 이미지 – 다중 언어 지원
FROM ubuntu:22.04

# 기본 패키지 설치
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    g++ \
    default-jdk \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# 샌드박스 작업 디렉토리
WORKDIR /sandbox

# 실행 스크립트 복사
COPY sandbox/run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# 보안: 비권한 사용자로 실행
RUN useradd -ms /bin/bash sandboxuser
USER sandboxuser

ENTRYPOINT ["/usr/local/bin/run.sh"]
