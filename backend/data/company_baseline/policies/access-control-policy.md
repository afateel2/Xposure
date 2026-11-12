# Access Control Policy (سياسة التحكم في الوصول)

- Document ID: POL-002
- Version: 1.0
- Last reviewed: 2025-11-10
- Owner: IT Security Lead
- Approved by: Executive Management
- Applicable regulation: NCA ECC-1:2018

## 1. Purpose (الغرض)

This policy defines how access to company information systems, production systems and product management interfaces is requested, granted, used and reviewed.

## 2. Scope (النطاق)

It applies to all user accounts, service accounts and shared accounts on corporate IT systems, the SCADA-Lite Monitoring System and the OT network at the Dammam Plant.

## 3. User authentication

- Every user is identified by a unique account. Shared accounts are not allowed except where a system cannot support individual accounts, and each exception is approved by the IT Security Lead.
- Users authenticate with a username and a password that meets the password standard: at least 12 characters, no reuse of the last 10 passwords, changed when compromise is suspected.
- Multi-factor authentication is required for all remote access to the corporate network and to OT systems.

## 4. Authorization

- Access is granted on the principles of need-to-know and need-to-use, least privilege and segregation of duties.
- Every access request is approved by the data or system owner before the account is created or changed.
- Access is removed within one working day when an employee leaves or changes role.

## 5. Privileged access management

- Privileged accounts (administrators and OT engineering accounts) are separate from day-to-day accounts and are issued only to named individuals.
- Privileged sessions on production systems are logged.
- Privileged account passwords are stored in the approved password vault.

## 6. Access review

- The IT Security Lead reviews user identities and access rights every six months.
- Privileged accounts are reviewed every quarter.
- Review results and follow-up actions are recorded in the Access Review Log.

## 7. Operational technology access

- Access to OT systems is granted by the OT Engineering Lead and follows the same principles as corporate access.
- Local accounts on control units are limited to the maintenance roles listed in the Production Line Control Procedure.

## Change log

- 1.0 (2025-11-10): Initial approved release aligned with NCA ECC-1:2018.
