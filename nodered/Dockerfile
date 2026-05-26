FROM nodered/node-red:4.0

# Install kafkajs in /data (Node-RED's userDir) so the function-node
# `libs` field can resolve it at runtime without triggering an in-flow
# install (which would need network + write access to /data/.npm).
USER root
WORKDIR /data
RUN echo '{"name":"node-red-data","version":"1.0.0","private":true}' > package.json && \
    npm install --no-audit --no-fund kafkajs && \
    chown -R node-red:node-red /data
USER node-red
WORKDIR /usr/src/node-red
