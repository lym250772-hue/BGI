# Stage 1 — extract archive inside Linux to preserve symlinks
FROM openjdk:17-slim AS builder
COPY apache-doris-2.1.7-bin-x64.tar.gz /tmp/
RUN tar -xzf /tmp/apache-doris-2.1.7-bin-x64.tar.gz -C /tmp/

# Stage 2 — runtime
FROM openjdk:17-slim

LABEL org.apache.doris.version="2.1.7"

COPY --from=builder /tmp/apache-doris-2.1.7-bin-x64 /opt/doris
COPY entrypoint.sh /opt/doris/entrypoint.sh
RUN chmod +x /opt/doris/entrypoint.sh

WORKDIR /opt/doris
EXPOSE 8030 9030 9050 8040
ENTRYPOINT ["/opt/doris/entrypoint.sh"]
