# Network Security Procedure (إجراء أمن الشبكات)

- Document ID: PRO-001
- Version: 1.0
- Last reviewed: 2025-11-15
- Owner: OT Engineering Lead
- Approved by: IT Security Lead
- Applicable regulation: NCA ECC-1:2018

## 1. Purpose (الغرض)

This procedure describes how the networks of Eastern Industrial Company are segmented, protected and monitored, so that a compromise in one area cannot spread to the production line.

## 2. Scope (النطاق)

It covers the corporate network, the demilitarized zone (DMZ), the OT production network at the Dammam Plant, and the test and development network.

## 3. Network zones

| Zone | Purpose | Connected to |
| --- | --- | --- |
| Corporate | Office systems and business applications | DMZ, Internet through the perimeter firewall |
| DMZ | SCADA-Lite remote dashboard, remote access gateway | Corporate, Internet |
| OT production | Assembly, test and calibration cells, ICU-200 units on the line | Corporate through a controlled firewall only |
| Test and development | Firmware build and test systems | Corporate only |

## 4. Segmentation rules

- Each zone is separated by a firewall with a default-deny rule. Only traffic that is documented and approved is allowed.
- The OT production network has no direct connection to the Internet.
- The production environment is separated from the test and development environment. Test systems never connect to production controllers.
- The OT Network Segmentation Design is the reference diagram and is updated whenever a firewall rule or a zone changes.

## 5. Remote access

- Remote access to the corporate network and to OT systems goes only through the VPN gateway in the DMZ.
- Multi-factor authentication is required for every remote session.
- Vendor remote access to OT systems is enabled only for the duration of an approved maintenance window.

## 6. Wireless networks

- Wireless networks use WPA2-Enterprise or stronger authentication and encryption.
- Wireless access points are not connected to the OT production network.
- A risk assessment is completed before any new wireless network is connected to the internal network.

## 7. Network services, protocols and ports

- Only the services, protocols and ports listed in the approved rule set are enabled. Anything else is blocked.
- Intrusion prevention is enabled on the perimeter firewall and on the firewall in front of the OT production network.
- DNS is provided by internal resolvers with DNS security controls enabled.

## 8. Logging and monitoring

- Firewall, VPN and network device logs are sent to the central log platform.
- The IT Security Lead reviews security alerts daily on working days.
- Logs are kept for at least 12 months.

## 9. Review

- Firewall rules are reviewed every six months by the OT Engineering Lead and the IT Security Lead.
- Unused rules are removed after the review.

## Change log

- 1.0 (2025-11-15): Initial approved release aligned with NCA ECC-1:2018.
