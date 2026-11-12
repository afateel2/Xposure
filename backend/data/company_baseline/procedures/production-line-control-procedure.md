# Production Line Control Procedure (إجراء التحكم في خط الإنتاج)

- Document ID: PRO-002
- Version: 1.0
- Last reviewed: 2025-11-15
- Owner: Operations Manager
- Approved by: IT Security Lead
- Applicable regulation: NCA ECC-1:2018

## 1. Purpose (الغرض)

This procedure defines how the assembly, test and calibration cells at the Dammam Plant are operated and changed without putting production or product security at risk.

## 2. Scope (النطاق)

It covers all production line controllers, operator stations, the SCADA-Lite Monitoring System used on the plant floor, and every ICU-200 Industrial Control Unit while it is in production or test.

## 3. Roles

- The Operations Manager is accountable for the production line and approves production changes.
- The OT Engineering Lead approves and applies changes to controllers, control programs and product firmware.
- The IT Security Lead reviews changes that affect network connections or access rights.

## 4. Access to line control systems

- Only named, trained operators and engineers have accounts on line control systems.
- Engineering workstations are separate from operator stations, and both are separate from the office network.
- Access rights follow the Access Control Policy and are reviewed every six months.

## 5. Change control

- Every change to a controller program, configuration or firmware version needs a change request with a description, a risk assessment, a test result and a rollback plan.
- Changes are tested on the test line before they are applied to production.
- Emergency changes are approved by the Operations Manager and reviewed by the OT Engineering Lead within two working days.

## 6. Removable media and portable devices

- Removable media and portable engineering laptops are scanned on a dedicated scanning station before use on the line.
- Personal devices are never connected to the production network.

## 7. Vulnerability and patch management

- The OT Engineering Lead keeps an inventory of OT systems and reviews vendor vulnerability notices every month.
- Patches are tested and applied during planned maintenance windows.

## 8. Backup and recovery

- Controller programs and configurations are backed up after every approved change and at least once a month.
- Recovery from backup is tested once a year on the test line.

## 9. Monitoring and incident handling

- Alarms from the SCADA-Lite Monitoring System and network security alerts are reviewed by the shift supervisor.
- A suspected cybersecurity incident on the line is reported to the IT Security Lead at once. The Operations Manager decides whether to stop production.

## Change log

- 1.0 (2025-11-15): Initial approved release aligned with NCA ECC-1:2018.
