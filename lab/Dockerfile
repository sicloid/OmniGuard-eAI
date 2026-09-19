FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash iproute2 nftables conntrack iputils-ping util-linux python3 procps \
    coreutils gawk grep && rm -rf /var/lib/apt/lists/*
COPY core /opt/omniguard/core
COPY gateway /opt/omniguard/gateway
COPY stubs /opt/omniguard/stubs
COPY lab /opt/omniguard/lab
WORKDIR /opt/omniguard
ENV PYTHONPATH=/opt/omniguard
CMD ["bash", "lab/container_smoke.sh"]
