# Workload Split — Ryan & Rania (Security & PQC, 30%)

> **Reference:** [ARCHITECTURE.md](./ARCHITECTURE.md) — Section 4 (Security Layer) + Section 15 (Roles)
> **Overall team workload:** 30% of the project (15% each)

---

## Overview

The Security & PQC scope covers **4 major functional blocks**:

| Block | Description |
|-------|-------------|
| **Double Proxy** | Forward Proxy (Gateway side) + Reverse Proxy (Middleware side) with PQC termination |
| **TLS 1.3 Hybrid Handshake** | X25519MLKEM768 key exchange + Session Resumption PSK+DHE |
| **Certificates & mTLS** | Hybrid CA, ECC-hybrid-MLDSA5 certificate generation, mTLS allowlist |
| **Log Signing** | PQC log signing with ECC-hybrid-MLDSA5 + secure key storage |

The split separates **transport** (encrypted tunnel) from **identity** (certificates, authentication, signing).

---

## 🔧 Ryan Zerhouni — PQC Transport & Tunnel Lead (15%)

### Role
Responsible for setting up the **end-to-end PQC tunnel** between the IoT zone and the Middleware, via the Nginx/OQS double proxy.

### Detailed Missions

| # | Mission | Detail |
|---|---------|--------|
| 1 | **Forward Proxy (Gateway side)** | Nginx configuration compiled with OQS-provider. Intercepts local MQTT/HTTP flows and encapsulates them in the outgoing TLS/PQC tunnel. |
| 2 | **Reverse Proxy (Middleware side)** | Terminates the incoming PQC tunnel, verifies client identity, redirects decrypted traffic to Mosquitto Broker / Node-RED. |
| 3 | **TLS 1.3 Hybrid Handshake** | Configuration of the `X25519MLKEM768` key group in OpenSSL 3.x + OQS-provider. Validation of the full handshake (ClientHello → ServerHello → AES-256-GCM session). |
| 4 | **Session Resumption (PSK+DHE)** | Activation of the TLS 1.3 session resumption mechanism in hybrid mode: PSK derived from the initial ML-KEM-768 secret + ephemeral X25519 exchange on each reconnection. |
| 5 | **Docker Network Segmentation** | Configuration of isolated Docker Networks (`internal: true`) to ensure the PQC tunnel is the only authorised communication vector between the IoT perimeter and the Middleware perimeter. |
| 6 | **Performance Testing** | Measurement of full handshake latency vs. session resumption. Validation of the 90% overhead reduction stated in the architecture. |

### Files Under Responsibility

```
infra/
├── forward-proxy/
│   ├── Dockerfile            ← Nginx build with OQS-provider
│   └── nginx.conf            ← Outgoing proxy config + TLS/PQC (X25519MLKEM768)
├── reverse-proxy/
│   ├── Dockerfile
│   └── nginx.conf            ← Incoming proxy config + PQC termination
└── docker-compose.yml        ← forward-proxy, reverse-proxy sections + isolated networks
```

> **Note:** no Python scripts `tls_client.py` / `tls_server.py` — TLS/PQC is entirely handled by **Nginx compiled with OQS-provider**. Configuration is done in the `nginx.conf` files.

### Deliverables

- [ ] Working Forward Proxy (Nginx/OQS) with outgoing PQC tunnel
- [ ] Working Reverse Proxy with PQC termination and traffic redirection
- [ ] X25519MLKEM768 handshake validated (Wireshark capture or OpenSSL logs)
- [ ] PSK+DHE Session Resumption working (latency gain measured)
- [ ] Segmented Docker Networks (`internal: true`) operational
- [ ] Performance test documentation (full handshake vs. resumption latency)

---

## 🔐 Rania El haddaoui — PQC Identity & Integrity Lead (15%)

### Role
Responsible for the **cryptographic chain of trust**: hybrid certificate generation, mutual authentication, and PQC log signing.

### Detailed Missions

| # | Mission | Detail |
|---|---------|--------|
| 1 | **Hybrid CA (PKI-free)** | Generation of the root certificate and hybrid private key ECC-hybrid-MLDSA5 using `liboqs` + `oqs-python`. No external PKI: allow-list model. |
| 2 | **Gateway & Middleware Certificates** | Generation of identity certificates for the Gateway and the Middleware, signed by the hybrid CA. ECC-hybrid-MLDSA5 private keys. |
| 3 | **mTLS Allowlist** | Implementation of the mutual authentication mechanism without PKI: `allowlist.json` file listing authorised certificates. Cross-validation Gateway ↔ Middleware. |
| 4 | **Secure Key Storage** | Encryption of `.pem` files with AES-256 + passphrase. Permissions 600. Provisioning script on first startup. |
| 5 | **PQC Log Signing** | Implementation of `log_signer.py`: ECC-hybrid-MLDSA5 double signature (ECDSA P-384 ∥ ML-DSA-5) of each log entry. Integrity verification. |
| 6 | **Device Signature Scheme Choice** | Technical decision: ECC-hybrid-MLDSA5 (consistent with logs, heavier) vs. ML-DSA-65 (lighter) for device certificates. Documented justification. |

### Files Under Responsibility

```
security/
├── ca/
│   ├── ca.crt                ← Root certificate (ECC-hybrid-MLDSA5)
│   └── ca.key                ← Root private key (AES-256 encrypted)
├── gateway/
│   ├── gateway.crt           ← Gateway identity certificate
│   └── gateway.key           ← Hybrid private key (perm. 600)
├── middleware/
│   ├── middleware.crt        ← Middleware identity certificate
│   └── middleware.key        ← Hybrid private key
├── allowlist.json            ← List of authorised certificates (mTLS)
├── log_signer.py             ← ECC-hybrid-MLDSA5 log signing
└── gen_certs.py              ← [NEW] Certificate generation script
```

### Deliverables

- [ ] Working hybrid CA (root certificate + ECC-hybrid-MLDSA5 key)
- [ ] Gateway and Middleware certificates generated and signed by the CA
- [ ] mTLS allowlist operational (mutual authentication validated)
- [ ] `.pem` keys encrypted with AES-256 + automatic provisioning
- [ ] `log_signer.py`: log signing + verification working
- [ ] Technical note on ML-DSA-5 vs. ML-DSA-65 choice for devices

---

## Comparative Summary

| Criterion | Ryan | Rania |
|-----------|------|-------|
| **Scope** | Transport & Tunnel | Identity & Integrity |
| **Workload** | 15% | 15% |
| **Main Technologies** | Nginx, OQS-provider, Docker Networks | liboqs, oqs-python, OpenSSL |
| **Primary Algorithm** | X25519MLKEM768 (KEM) | ECC-hybrid-MLDSA5 (Signature) |
| **Focus** | Tunnel performance, latency | Chain of trust, non-repudiation |
| **Deliverables** | 6 | 6 |

---

## Cross-Dependencies

```
Rania generates certificates ──► Ryan uses them in Nginx config
     (ca.crt, gateway.crt,          (ssl_certificate, ssl_certificate_key
      middleware.crt)                 in nginx.conf)

Ryan provides the TLS tunnel ──► Rania validates end-to-end mTLS
     (forward + reverse proxy)       (allowlist.json verified under real conditions)
```

> **Synchronisation point:** Rania's certificates must be generated **before** Ryan can test the full tunnel. Plan an intermediate certificate delivery as a priority.

---

*Document created on 26/04/2026*
