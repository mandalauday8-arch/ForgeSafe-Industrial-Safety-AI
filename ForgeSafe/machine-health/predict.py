from pathlib import Path
import json

from catboost import CatBoostClassifier
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_NAMES = {
    "CNC_Lathe": "cnc_lathe",
    "CNC_Mill": "cnc_mill",
    "Hydraulic_Press": "hydraulic_press",
    "Injection_Molder": "injection_molder",
    "Industrial_Chiller": "industrial_chiller",
    "Furnace": "furnace",
}


def load_model(machine_type):
    model_name = MODEL_NAMES.get(machine_type)
    if model_name is None:
        raise ValueError(f"Unsupported machine type: {machine_type}")

    with (MODEL_DIR / f"{model_name}_metadata.json").open() as metadata_file:
        metadata = json.load(metadata_file)
    model = CatBoostClassifier()
    model.load_model(str(MODEL_DIR / f"{model_name}_failure_model.cbm"))

    return model, metadata


def predict_machine(machine_data):
    """
    Predict whether a machine is likely to fail within 7 days.

    machine_data must contain the features expected by the model.
    Machine-specific sensors that are unavailable can be left as None.
    """

    machine_type = machine_data.get("Machine_Type")
    model, metadata = load_model(machine_type)

    features = metadata["features"]

    # Check required fields
    missing = [
        feature for feature in features
        if feature not in machine_data
    ]

    if missing:
        raise ValueError(
            f"Missing required fields: {missing}"
        )

    # Create input dataframe
    input_data = pd.DataFrame(
        [[machine_data[feature] for feature in features]],
        columns=features
    )

    # Prediction
    prediction = model.predict(input_data)[0]

    # Probability
    probabilities = model.predict_proba(input_data)[0]

    failure_probability = float(probabilities[1]) * 100

    # Risk level
    if failure_probability >= 80:
        risk = "CRITICAL"
    elif failure_probability >= 60:
        risk = "HIGH"
    elif failure_probability >= 30:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {
        "machine_type": machine_data["Machine_Type"],
        "failure_within_7_days": bool(prediction),
        "failure_probability": round(failure_probability, 2),
        "risk_level": risk
    }


if __name__ == "__main__":

    # Example machine telemetry
    machine = {
        "Machine_Type": "Hydraulic_Press",

        "Installation_Year": 2020,
        "Operational_Hours": 8500,

        "Temperature_C": 72.5,
        "Vibration_mms": 4.2,
        "Sound_dB": 78.0,

        "Oil_Level_pct": 62.0,
        "Coolant_Level_pct": 55.0,

        "Power_Consumption_kW": 18.5,

        "Last_Maintenance_Days_Ago": 45,
        "Maintenance_History_Count": 12,
        "Failure_History_Count": 1,

        "AI_Supervision": 1,
        "Error_Codes_Last_30_Days": 2,

        "Laser_Intensity": None,
        "Hydraulic_Pressure_bar": 145.0,
        "Coolant_Flow_L_min": 18.0,

        "Heat_Index": 0.72,
        "AI_Override_Events": 1
    }

    result = predict_machine(machine)

    print("\n==============================")
    print("  INDUSTRIAL MACHINE MONITOR")
    print("==============================")

    for key, value in result.items():
        print(f"{key}: {value}")

    print("==============================\n")