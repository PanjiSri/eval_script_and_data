import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import sys
import os

def plot_multiple_cdfs(csv_files, output_image):
    # A figure for the plot is created
    plt.figure(figsize=(10, 6))
    
    # A list of colors is defined so that each file has a different line color
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
    
    # An iteration is performed for each inputted CSV file
    for i, csv_file in enumerate(csv_files):
        try:
            df = pd.read_csv(csv_file)
        except FileNotFoundError:
            print(f"Error: File '{csv_file}' was not found. Skipped.")
            continue
        except Exception as e:
            print(f"Error when reading '{csv_file}': {e}. Skipped.")
            continue

        if 'latency_ms' not in df.columns:
            print(f"Error: Column 'latency_ms' was not found in '{csv_file}'. Skipped.")
            continue

        # Latency data is extracted and cleaned
        latency_data = df['latency_ms'].dropna()

        # The CDF data generation process is executed
        x = np.sort(latency_data)
        y = np.arange(1, len(x) + 1) / len(x)

        # The file name without its extension is extracted to be used as the label name in the graph
        label_name = os.path.splitext(os.path.basename(csv_file))[0]
        
        # The color is determined based on the file order
        color = colors[i % len(colors)]

        # The CDF line is plotted
        plt.plot(x, y, linestyle='-', color=color, linewidth=2, label=f'CDF {label_name}')
        
        # Optional: The p95 line is added for each file so that the comparison is clearer
        p95 = np.percentile(x, 95)
        plt.axvline(p95, color=color, linestyle=':', alpha=0.8, label=f'p95 {label_name} ({p95:.2f} ms)')

    # The overall plot appearance is customized
    plt.title('CDF of Latency Comparison', fontsize=14, fontweight='bold')
    plt.xlabel('Latency (ms)', fontsize=12)
    plt.ylabel('Cumulative Probability', fontsize=12)
    plt.ylim(0, 1.05)
    plt.xlim(left=0)
    plt.grid(True, which="major", linestyle="--", alpha=0.7)
    
    # The legend is displayed
    plt.legend(loc='lower right')
    plt.tight_layout()

    # The results are saved and displayed
    plt.savefig(output_image, dpi=300)
    print(f"Success! The comparison graph was successfully saved as: {output_image}")
    plt.show()


if __name__ == "__main__":
    # The minimum arguments are checked (Script + Number of Files + Minimum 1 CSV File)
    if len(sys.argv) < 3:
        print("Correct usage:")
        print("python3 latency_raft.py <number_of_csv_files> <csv_file_1> <csv_file_2> ... [output_image_name.png]")
        sys.exit(1)
    
    # The number of CSV files is captured from the first argument
    try:
        num_files = int(sys.argv[1])
    except ValueError:
        print("Error: The <number_of_csv_files> argument must be an integer.")
        sys.exit(1)
        
    # It is ensured that the number of arguments matches the claimed number of files
    if len(sys.argv) < 2 + num_files:
        print(f"Error: It was stated that there are {num_files} CSV files, but the file name arguments are insufficient.")
        sys.exit(1)
        
    # The list of CSV file names is extracted
    csv_files = sys.argv[2:2+num_files]
    
    # It is checked whether there is an additional argument for the output image name at the very end
    if len(sys.argv) > 2 + num_files:
        output_img = sys.argv[2 + num_files]
        if not output_img.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
            output_img += '.png'
    else:
        # A default name is assigned if there is no output name argument
        output_img = 'cdf_comparison.png'
    
    # The main function is executed
    plot_multiple_cdfs(csv_files, output_img)