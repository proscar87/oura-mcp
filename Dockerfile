# oura-mcp as a container, for people who would rather not have a Python on
# their machine at all.
#
# IT SPEAKS STDIO, NOT HTTP, because that is what an MCP server is. There is no
# port to publish and `-i` is not optional: without it the container has no
# stdin, the handshake never arrives, and the client reports a server that
# "doesn't show up" — the exact failure mode this repository keeps a smoke test
# for.
#
#   docker run -i --rm -e OURA_SANDBOX=1 ghcr.io/proscar87/oura-mcp
#
# Sample data by default in that line, so it runs with no account. For real
# data, pass a credential instead:
#
#   docker run -i --rm -e OURA_PAT=... ghcr.io/proscar87/oura-mcp
#
# OAuth2 is deliberately NOT the containerized path. Authorizing opens a
# browser and listens on a loopback port for the callback, and neither of those
# survives a container boundary without more flags than the whole thing is
# worth. Authorize on the host with `oura-mcp --authorize` and mount the
# credentials read-only:
#
#   docker run -i --rm -v ~/.config/oura-mcp:/home/oura/.config/oura-mcp:ro \
#     ghcr.io/proscar87/oura-mcp

FROM python:3.13-slim

# The version is passed in rather than read here: the image is built from a tag,
# and a Dockerfile that re-derives it is one more of the ten places it can drift.
ARG VERSION=0.0.0

LABEL org.opencontainers.image.title="oura-mcp" \
      org.opencontainers.image.description="The Oura v2 API as an MCP server. Paginates, fixes the date range, warns when data is missing." \
      org.opencontainers.image.source="https://github.com/proscar87/oura-mcp" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# No wheel cache and no build artifacts left behind: this image is a pipe, and
# every megabyte in it is a megabyte someone downloads to run three tools.
RUN pip install --no-cache-dir . && rm -rf /src

# NOT ROOT. It reads a credential file and talks to one API; there is nothing
# here that needs it, and an MCP server runs whatever a model asks it to run.
RUN useradd --create-home --shell /usr/sbin/nologin oura
USER oura
WORKDIR /home/oura

# Unbuffered, because stdout IS the protocol. A buffered line is a handshake
# that arrives late or not at all, and from the client that looks identical to
# a server that never started.
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["oura-mcp"]
