
import os
import pandas as pd

BASE_DIR = r"c:\AceCpas docs\Acecpas-backend\Golden Data Set - 5 Deals of GLs before and after"

def inspect_files():
    for root, dirs, files in os.walk(BASE_DIR):
        for file in files:
            if "Final Output" in root and file.endswith(".xlsx") and not file.startswith("~$"):
                full_path = os.path.join(root, file)
                print(f"Reading: {full_path}")
                try:
                    df = pd.read_excel(full_path, nrows=5)
                    print("Columns:", df.columns.tolist())
                    print("First row:", df.iloc[0].to_dict())
                    return # Just check one
                except Exception as e:
                    print(f"Error reading {file}: {e}")

if __name__ == "__main__":
    inspect_files()
