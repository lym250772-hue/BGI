#!/bin/bash
set -e
ROLE=${DORIS_ROLE:-fe}
echo "=== Starting Doris ${ROLE} ==="

if [ "$ROLE" = "fe" ]; then
  grep -q "^#* *priority_networks" /opt/doris/fe/conf/fe.conf \
    && sed -i "s|^#* *priority_networks.*|priority_networks = 0.0.0.0/0|" /opt/doris/fe/conf/fe.conf \
    || echo "priority_networks = 0.0.0.0/0" >> /opt/doris/fe/conf/fe.conf

  # Disable pipeline engine to avoid bRPC port issues in Docker
  echo "enable_pipeline_engine = false" >> /opt/doris/fe/conf/fe.conf
  echo "enable_nereids_dml = false" >> /opt/doris/fe/conf/fe.conf
  echo "experimental_enable_nereids_dml_with_pipeline = false" >> /opt/doris/fe/conf/fe.conf

  exec /opt/doris/fe/bin/start_fe.sh --console

elif [ "$ROLE" = "be" ]; then
  grep -q "^#* *priority_networks" /opt/doris/be/conf/be.conf \
    && sed -i "s|^#* *priority_networks.*|priority_networks = 0.0.0.0/0|" /opt/doris/be/conf/be.conf \
    || echo "priority_networks = 0.0.0.0/0" >> /opt/doris/be/conf/be.conf

  # Docker Desktop often cannot persist these host-level checks. Try the real
  # setting first, then patch the local startup guard for a single-node demo.
  sysctl -w vm.max_map_count=2000000 >/dev/null 2>&1 || true
  ulimit -n 655350 >/dev/null 2>&1 || true
  sed -i 's|MAX_MAP_COUNT="$(cat /proc/sys/vm/max_map_count)"|MAX_MAP_COUNT="2000000"|' /opt/doris/be/bin/start_be.sh
  sed -i 's|MAX_FILE_COUNT="$(ulimit -n)"|MAX_FILE_COUNT="655350"|' /opt/doris/be/bin/start_be.sh

  # Bypass swap check — replace swapon count with 0 so condition is always false
  sed -i 's#$(swapon -s | wc -l)" -gt 1#0" -gt 1#' /opt/doris/be/bin/start_be.sh

  exec /opt/doris/be/bin/start_be.sh --console

else
  echo "Unknown DORIS_ROLE: $ROLE"
  exit 1
fi
