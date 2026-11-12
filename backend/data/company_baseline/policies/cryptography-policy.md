# Cryptography Policy (سياسة التشفير)

- Document ID: POL-003
- Version: 1.0
- Last reviewed: 2025-11-10
- Owner: IT Security Lead
- Approved by: Executive Management
- Applicable regulation: NCA ECC-1:2018

## 1. Purpose (الغرض)

This policy defines how cryptography is used to protect company data, product firmware and communications, and how cryptographic keys are managed.

## 2. Scope (النطاق)

It applies to all corporate systems, to data held by the company on servers, laptops and backups, and to the firmware and management interfaces of the ICU-200 Industrial Control Unit and the SCADA-Lite Monitoring System.

## 3. Approved cryptographic solutions

- Only the algorithms and minimum key lengths in the approved cryptographic standard list are used.
- Symmetric encryption: AES with a key length of at least 128 bits.
- Asymmetric encryption and signing: RSA with a key length of at least 2048 bits, or ECDSA with the P-256 curve.
- Hashing: SHA-256 or stronger. MD5 and SHA-1 are not allowed for security purposes.
- Transport security: TLS 1.2 or higher.
- The IT Security Lead maintains the approved list and records the technical and regulatory limitations of each solution.

## 4. Key management

- Cryptographic keys are managed through their full lifecycle: generation, distribution, storage, rotation, revocation and destruction.
- Keys are generated and stored in approved secure storage. Firmware signing keys are held in a hardware security module.
- Keys are rotated at least once every two years, and immediately if compromise is suspected.

## 5. Encryption of data at rest

- Laptops, servers holding confidential data, corporate databases and backups are encrypted at rest.
- Classification level determines the minimum protection. Confidential data is always encrypted.

## 6. Encryption of data in transit

- All connections to corporate systems, web applications, the VPN and the SCADA-Lite remote dashboard use TLS 1.2 or higher.
- Industrial protocol traffic inside the segmented OT production network is currently not encrypted. It is protected by network segmentation and access control instead.

## 7. Exceptions

Any exception to this policy needs a written risk acceptance signed by the IT Security Lead and reviewed every year.

## Change log

- 1.0 (2025-11-10): Initial approved release aligned with NCA ECC-1:2018.
