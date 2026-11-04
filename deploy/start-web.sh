#!/bin/sh
# web konteinera palaišana. Parasti tikai uvicorn.
# Dev versijā ar LOGIN_LIVE=1 (un image ar DEBUG_TOOLS=1) papildus palaiž virtuālu ekrānu, uz kura
# atveras RTU pieteikšanās pārlūks, un noVNC (ports 6080), lai to logu varētu redzēt un lietot pārlūkā.
set -e

if [ "${LOGIN_LIVE:-}" = "1" ] && command -v Xvfb >/dev/null 2>&1; then
  if [ -z "${VNC_PASSWORD:-}" ]; then
    echo "LOGIN_LIVE=1, bet VNC_PASSWORD nav iestatīts .env — live logs netiek palaists." >&2
  else
    export DISPLAY=:99
    Xvfb :99 -screen 0 1280x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    sleep 1
    mkdir -p "$HOME/.vnc"
    x11vnc -storepasswd "$VNC_PASSWORD" "$HOME/.vnc/passwd" >/dev/null 2>&1
    x11vnc -display :99 -rfbauth "$HOME/.vnc/passwd" -localhost -forever -shared -quiet -bg -o /tmp/x11vnc.log
    websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
    echo "Live pieteikšanās logs: noVNC uz :6080 (DISPLAY=$DISPLAY)"
  fi
fi

exec uvicorn server.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
