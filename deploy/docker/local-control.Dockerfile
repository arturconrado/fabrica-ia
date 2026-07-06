FROM docker:27-cli

ARG TARGETARCH
ARG KIND_VERSION=v0.32.0
ARG KUBECTL_VERSION=v1.31.4

RUN apk add --no-cache \
    bash \
    ca-certificates \
    coreutils \
    curl \
    docker-cli-buildx \
    docker-cli-compose \
    git \
    jq \
    make \
    openssl \
    python3 \
  && case "$TARGETARCH" in \
      amd64|arm64) tool_arch="$TARGETARCH" ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
  && curl -fsSL -o /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${tool_arch}" \
  && chmod +x /usr/local/bin/kind \
  && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${tool_arch}/kubectl" \
  && chmod +x /usr/local/bin/kubectl

WORKDIR /workspace

ENTRYPOINT ["/bin/bash", "-lc"]
