FROM clamav/clamav:1.4

USER root
RUN apk add --no-cache python3

WORKDIR /opt/edoc-av
COPY scanner.py /opt/edoc-av/scanner.py
COPY start.sh /opt/edoc-av/start.sh
RUN chmod 0555 /opt/edoc-av/scanner.py /opt/edoc-av/start.sh

ENV PORT=8080 \
    CLAMD_HOST=127.0.0.1 \
    CLAMD_PORT=3310 \
    CLAMD_TIMEOUT_SECONDS=60 \
    EDOC_AV_INLINE_MAX_MB=4 \
    EDOC_AV_MAX_FILE_SIZE_MB=50 \
    FRESHCLAM_CHECKS=6

EXPOSE 8080
ENTRYPOINT ["/opt/edoc-av/start.sh"]
