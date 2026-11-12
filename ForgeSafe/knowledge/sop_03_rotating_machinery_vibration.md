# SOP-03: Rotating Machinery Vibration and Spindle Bearing Degradation

## Standard Reference
ISO 10816-3 (Mechanical Vibration - Evaluation of Machine Vibration on Industrial Machines), ISO 20816, and ANSI/ASA S2.75.

## Purpose and Scope
Applies to CNC Lathes, CNC Mills, multi-axis machining centers, and high-speed rotary drives. Establishes vibration velocity limits (RMS mm/s) and bearing wear escalation rules.

## Vibration Severity Zones (ISO 10816-3 Class II & III)
- **Zone A / B (Healthy / Acceptable):** Vibration < 4.5 mm/s. Machine is in optimal operational condition.
- **Zone C (Degrading / Unsatisfactory):** Vibration 4.5 mm/s - 7.1 mm/s. Indicates early stage bearing race spalling, spindle unbalance, or chuck misalignment.
- **Zone D (Unacceptable / Critical Fault):** Vibration > 7.1 mm/s or acoustic noise > 85.0 dB. Imminent catastrophic bearing seizure or tool breakage hazard.

## Mandatory Mitigation Steps
- **Bearing Degradation / Severe Vibration Fault (> 7.1 mm/s or Model Risk >= 80%):**
  - Severity: CRITICAL.
  - Risk: Spindle runaway, chuck projectile hazard, workpiece ejection, motor burn-out.
  - Mandatory Action: Initiate immediate Simulated Spindle Stop / Machine Shutdown. Tag machine out of production. Perform vibration spectrum FFT analysis and inspect race bearings and drive belt tension.
  - Designated Owner: Maintenance Lead & Lead Machinist.

- **Vibration Degradation / Warning State (4.5 - 7.1 mm/s):**
  - Severity: HIGH.
  - Mandatory Action: Throttle feed rate to 70%, schedule spindle bearing inspection and re-greasing within 24 hours, and continuously log acoustic decibel levels.
