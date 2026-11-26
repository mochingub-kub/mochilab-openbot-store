# Select the host's primary IPv4 address without sending network traffic.
MOCHILAB_OPENTHAI_LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if ($i=="src") {print $(i+1); exit}}')" || MOCHILAB_OPENTHAI_LAN_IP=
case "${MOCHILAB_OPENTHAI_LAN_IP}" in
  10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) ;;
  *) MOCHILAB_OPENTHAI_LAN_IP=127.0.0.1 ;;
esac
export MOCHILAB_OPENTHAI_LAN_IP
