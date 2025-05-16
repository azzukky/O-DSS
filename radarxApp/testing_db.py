from ricsdl.syncstorage import SyncStorage
import json
import numpy as np
import xgboost as xgb
import io
from PIL import Image
import matplotlib.pyplot as plt


namespace = "Kpms"
sdl1= SyncStorage()
# Retrieve all keys in the namespace
# Retrieve all keys in the namespace
key_pattern = "kpm_*"
keys = sdl1.find_keys(namespace, key_pattern)

# Sort the keys numerically based on the number in the key
sorted_keys = sorted(keys, key=lambda x: int(x.split('_')[1]))
n = 2
# Select the lastn keys
lastn_keys = sorted_keys[-n:]


# Retrieve the values for the last n keys
values = sdl1.get(namespace, set(lastn_keys))  # Pass keys as a set
# print(values)
# Dictionary to store the last n UE metrics from each of the last n keys
last_n_ue_metrics = {}
metrics_to_extract = ["pusch_sinr", "rx_bitrate", "rx_block_error_rate", "ul_mcs", "ul_buffer"]
extracted_metrics = []
# Process each key in the sorted order returned by the get method
for key, value_bytes in values.items():
    # print(key)
    if value_bytes:
        # Decode the value from bytes to a JSON object
        value = json.loads(value_bytes.decode('utf-8'))
        # print(value)
        # Extract the last n UE metrics from the current key's value
        ue_metrics = value.get("ue_metrics", [])
        # print(ue_metrics)
        
        last_n_ue_metrics[key] = ue_metrics[-n:]  # Get the last n UE metrics
        for ue_metric in ue_metrics:
            # print(ue_metric.get("rx_bitrate"))
            if (ue_metric.get("rx_bitrate") == 0 
                and ue_metric.get("rx_block_error_rate") == 0 
                and ue_metric.get("ul_buffer") == 0):
                continue  # Skip appending if all three are zero

            # Extract and append metrics only if the condition above is not met
            extracted_metrics.extend([ue_metric.get(metric) for metric in metrics_to_extract])
        # print(last_n_ue_metrics)
# print(ue_metrics)
# print(extracted_metrics)
# print(len(extracted_metrics))

# extracted_metrics = np.array(extracted_metrics).reshape(1,len(metrics_to_extract)*n)
# print(extracted_metrics)


# # For testing the prediction using xgboost
# model = xgb.XGBClassifier() 
# model.load_model("/home/azuka/spectrumsharing_4g/models/prelim_xgboost_model.model")  
# pred = model.predict(extracted_metrics)
# print(pred[0])



# Testing db for I/Q

ns2 = "Spectrograms"
data_dict = sdl1.get(ns2, {'new_spec'})
raw_bytes = None

  
    
for key, val in data_dict.items():
    raw_bytes = val
print(raw_bytes)
ret = io.BytesIO(raw_bytes)
image = Image.open(ret)
image = image.convert("L")
arr = np.array(image)
print("Shape of image is",arr.shape)
print("Plotting image")
plt.imshow(arr, cmap="gray")
plt.show()
plt.close()  