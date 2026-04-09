FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb libx11-6 libgl1-mesa-glx libgl1-mesa-dri mesa-utils \
    dbus libpulse0 alsa-utils openbox \
    libxcursor1 libxrandr2 libxinerama1 libxi6 libxss1 libxtst6 \
    libfontconfig1 libxrender1 libsdl2-2.0-0 \
    curl netcat-openbsd procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN printf 'pcm.!default {\n  type null\n}\nctl.!default {\n  type null\n}\n' > /etc/asound.conf

ENV DISPLAY=:99 \
    SDL_AUDIODRIVER=dummy \
    AUDIODEV=null \
    PULSE_SERVER=

RUN mkdir -p /opt/mods/HeadlessRimPatch /opt/mods/RIMAPI /opt/saves

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=60s \
    CMD curl -sf http://localhost:8765/api/v1/game/state || exit 1

ENTRYPOINT ["/entrypoint.sh"]
