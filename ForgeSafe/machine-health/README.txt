Six independent machine-specific CatBoost failure prediction models.
Each model is trained only on its own machine data.
Target: Failure_Within_7_Days.
Excluded: Machine_ID and Remaining_Useful_Life_days (target leakage).
Each model retains its relevant machine-specific sensor.

The faulty demonstration feed starts each machine with a FAULT row so the dashboard
immediately shows the labeled anomaly type: bearing/vibration, vibration, pressure,
cooling, or overheating degradation. The dashboard reports this demo label separately
from the model's Failure_Within_7_Days probability.
