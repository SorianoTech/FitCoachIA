FROM grafana/alloy:v1.5.1

COPY --chmod=755 config.alloy /etc/alloy/config.alloy

CMD ["run", "--server.http.listen-addr=0.0.0.0:12345", "--storage.path=/var/lib/alloy/data", "/etc/alloy/config.alloy"]

# Expose port 4317 for OTLP HTTP receiver (used by Tempo)
EXPOSE 4317
