# SOP-05: Industrial Chiller and Closed-Loop Cooling Circuit Safety

## Standard Reference
ASHRAE Standard 15 (Safety Standard for Refrigeration Systems), EN 378 (Refrigerating systems and heat pumps), and ASME Boiler and Pressure Vessel Code Section VIII.

## Purpose and Scope
Prescribes monitoring parameters and emergency protocols for industrial chillers providing process cooling to heavy machinery, spindles, and plastic injection molds.

## Operational Parameters
- **Nominal Chiller Temperature:** 7.0°C - 22.0°C supply loop.
- **Nominal Coolant Flow Rate:** 25.0 - 55.0 L/min.
- **Coolant Level Safe Range:** > 65% capacity.
- **Critical Cooling Degradation:** Coolant flow < 15.0 L/min, coolant level < 40%, or chiller circuit temperature > 45.0°C.

## Fault Mitigation Protocol
- **Cooling Degradation / Chiller Failure State:**
  - Severity: CRITICAL.
  - Risk: Downstream tool seizure, mold thermal warping, compressor burnout, refrigerant overpressure.
  - Mandatory Action: Initiate Simulated Chiller Standby / Downstream Interlock Pause. Switch to backup auxiliary heat exchanger. Inspect coolant pumps, strainer valves, and supply line connections for cavitation or blockages.
  - Designated Owner: HVAC Plant Engineer & Operations Supervisor.

- **Low Coolant Warning (40% - 60% Level):**
  - Severity: MEDIUM.
  - Mandatory Action: Refill deionized coolant/glycol mix to 90% capacity and test for micro-leaks in evaporator coil.
