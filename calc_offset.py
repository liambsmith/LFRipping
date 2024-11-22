import csv
import numpy as np
from scipy.stats import linregress

def calculate_disc_height(file_path):
    """Calculate the disc height and default offset from the CSV file."""
    disc_counts = []
    offsets = []

    # Read the CSV file
    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bin_num = int(row["Bin"])
            count = int(row["Count"])
            offset = int(row["Offset"])

            # Only process data for a specific bin (e.g., Bin 1)
            if bin_num == 1:
                disc_counts.append(count)
                offsets.append(offset)

    # Perform linear regression
    slope, intercept, r_value, p_value, std_err = linregress(disc_counts, offsets)

    # The slope is the disc height, and the intercept is the default offset
    return slope, intercept

if __name__ == "__main__":
    # Replace with the actual path to your offset.txt file
    file_path = "offset.txt"

    disc_height, default_offset = calculate_disc_height(file_path)
    print(f"Estimated Disc Height: {disc_height:.4f}")
    print(f"Default Offset: {default_offset:.2f}")

