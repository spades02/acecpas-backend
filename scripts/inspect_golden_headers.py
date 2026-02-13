
import os
import sys
import pandas as pd
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inspect_headers")

BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Golden Data Set - 5 Deals of GLs before and after")

def find_golden_files(base_dir: str):
    golden_files = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if "Final Output" in root and file.endswith(".xlsx") and not file.startswith("~$"):
                golden_files.append(os.path.join(root, file))
    return golden_files

def inspect():
    files = find_golden_files(BASE_DIR)
    for f in files:
        print(f"\n--- Analyzing file: {os.path.basename(f)} ---")
        try:
            # Load workbook to check sheet names
            xls = pd.ExcelFile(f)
            print(f"Sheets found: {xls.sheet_names}")
            
            for sheet in xls.sheet_names:
                print(f"\n  >> Sheet: {sheet}")
                # Read specific sheet
                df = pd.read_excel(f, sheet_name=sheet, nrows=5, header=None)
                
                # Check row 0-5 for header-like content
                for i in range(min(5, len(df))):
                    row_vals = [str(x).lower() for x in df.iloc[i].values if str(x).lower() not in ('nan', 'none', '')]
                    if row_vals:
                        print(f"     Row {i}: {row_vals}")

        except Exception as e:
            print(f"Error reading {f}: {e}")

if __name__ == "__main__":
    inspect()
