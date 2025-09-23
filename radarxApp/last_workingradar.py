import sctp
import socket
import array
import time
import json
import numpy as np
from PIL import Image
import math
import io
from ultralytics import YOLO
from tensorflow.keras.models import load_model
from ricsdl.syncstorage import SyncStorage
from log import *
import matplotlib.pyplot as plt


# Constants
CHANNEL_BANDWIDTH = 10e6
NUM_PRBS = 50
SPEC_WIDTH_PX = 640
SPEC_HEIGHT_PX = 640
PROTOCOL = 'SCTP'
ENABLE_DEBUG = False
BLER_THRESHOLD = 1.0  # BLER threshold in percentage
MCS_REDUCTION_STEP = 2  # Amount to reduce MCS by when BLER is below threshold
LOG_FILE1_PATH = 'radar_power_log_2db.txt'
LOG_FILE2_PATH = 'odss-timing-radarxapp.txt'
MODEL_KPMS_PATH = "/home/azuka/spectrumsharing_4g/models/kpmmodel_len5.h5"
MODEL_SPEC_PATH = "/home/azuka/spectrumsharing_4g/models/best.pt"
MAX_METRICS = [45839996.0, 100, 24.34091, 148525]
METRICS_TO_EXTRACT = ["rx_bitrate", "rx_block_error_rate", "ul_mcs", "ul_buffer"]


# Global variables
server = None
sdl2 = SyncStorage()
log_file1 = open(LOG_FILE1_PATH, 'w')
log_file2 = open(LOG_FILE2_PATH, 'w')
model_kpms = load_model(MODEL_KPMS_PATH)
interf_res_final = [34, 47, 23]
current_mode = "KPMs"  # Initial mode
command = b'k'
prev_command = None

def post_init():
    """Initialize the SCTP server."""
    ip_addr = socket.gethostbyname(socket.gethostname())
    port_radarxapp = 5002
    log_info(f"Connecting using {PROTOCOL} on {ip_addr}:{port_radarxapp}")
    
    global server
    server = sctp.sctpsocket_tcp(socket.AF_INET)
    server.bind((ip_addr, port_radarxapp))
    server.listen()
    log_info('Server started')

def load_model_spec():
    """Load the YOLO model for spectrogram analysis."""
    return YOLO(MODEL_SPEC_PATH)

def get_bytes():
    """Retrieve spectrogram bytes from the database."""
    data_dict = sdl2.get("Spectrograms", {'new_spec'})
    raw_bytes = None
    for key, val in data_dict.items():
        raw_bytes = val
    return raw_bytes

def raw_bytes_to_image(raw_bytes):
    """Convert raw bytes to a PIL image."""
    ret = io.BytesIO(raw_bytes)
    image = Image.open(ret)
    arr = np.array(image)
    # print("Shape of image is",arr.shape)
    # print("Plotting image")
    # plt.imshow(arr)
    # plt.show()
    # plt.close()
    return image

def predict_newdata(model_spec,sample):
    """Run YOLO prediction on the spectrogram image."""
    pred = model_spec(sample)
    result = pred[0]
    # inference = result.plot()
    # print("Plotting image")
    # plt.imshow(inference)
    # plt.show()
    # plt.close()
    
    soi, p0n2 = [], []
    for box in result.boxes:
        class_id = result.names[box.cls[0].item()]
        cords = box.xyxy[0].tolist()
        conf = round(box.conf[0].item(), 2)
        prediction = {"class": class_id, "cords": cords, "confidence": conf}
        
        if box.cls == 0 and conf > 0.60:
            soi.append(prediction)
        elif box.cls == 1 and conf > 0.50:
            p0n2.append(prediction)
    
    ymin_soi = soi[0]["cords"][1] if soi else "nil"
    ymax_soi = soi[0]["cords"][3] if soi else "nil"
    ymin_p0n2 = p0n2[0]["cords"][1] if p0n2 else "nil"
    ymax_p0n2 = p0n2[0]["cords"][3] if p0n2 else "nil"
    
    return ymin_soi, ymax_soi, ymin_p0n2, ymax_p0n2

def get_affected_prbs(ymin_soi, ymax_soi, ymin_p0n2, ymax_p0n2):
    """Calculate affected PRBs based on spectrogram predictions."""
    if ymin_p0n2 == "nil" and ymin_soi == "nil":
        return "No detections made"
    if ymin_p0n2 == "nil" and ymin_soi != "nil":
        return "There is no interference detected"
    
    ymin_soi, ymax_soi = 93.23387145996094, 552.609619140625
    guardband_bandwidth = 0.1 * CHANNEL_BANDWIDTH
    occupied_bandwidth = CHANNEL_BANDWIDTH - guardband_bandwidth
    soi_fullheight_px = float(ymax_soi) - float(ymin_soi)
    soi_effectiveheight_px = (occupied_bandwidth * soi_fullheight_px) / CHANNEL_BANDWIDTH
    effective_px_prb = soi_effectiveheight_px / NUM_PRBS
    guardbands_px = soi_fullheight_px - soi_effectiveheight_px
    guardband_low_px = guardbands_px / 2
    soi_start = ymin_soi + guardband_low_px
    soi_end = soi_start + soi_effectiveheight_px
    
    prb_affected1 = math.floor((soi_end - float(ymax_p0n2)) / effective_px_prb)
    prb_affected2 = math.ceil((soi_end - float(ymin_p0n2)) / effective_px_prb)
    if prb_affected1 < 0 or prb_affected2 < 0:
        prb_affected1 += 1
        prb_affected2 += 2
    
    return [[prb_affected1, prb_affected2]]


# This runs the prediction
def run_prediction(model_spec,raw_bytes):
    sample = raw_bytes_to_image(raw_bytes)
    ymin_soi, ymax_soi, ymin_cwis, ymax_cwis = predict_newdata(model_spec,sample)
    prbs_affected = get_affected_prbs(ymin_soi, ymax_soi, ymin_cwis, ymax_cwis) 
    # print("checking predictions",len(result))
    return prbs_affected

def optimize_mcs(mcs, bler):
    """Adjust MCS based on BLER threshold."""
    mcs_val = mcs - MCS_REDUCTION_STEP if bler < BLER_THRESHOLD else mcs
    return [max(0, mcs_val)]

def process_kpms():
    """Retrieve and process KPMs from the database."""
    start_time = time.perf_counter()
    key_pattern = "kpm_*"
    num_samples = 5
    # time.sleep(0.2)
    keys = sdl2.find_keys("Kpms", key_pattern)
    sorted_keys = sorted(keys, key=lambda x: int(x.split('_')[1]))[-num_samples:]
    print("These are the keys I am getting ", sorted_keys)
    values = sdl2.get("Kpms", set(sorted_keys))
    curr_extracted_metrics = []
    for key, value_bytes in values.items():
        if value_bytes:
            value = json.loads(value_bytes.decode('utf-8'))
            for ue_metric in value.get("ue_metrics", []):
                if all(ue_metric.get(m, 0) == 0 for m in ["rx_bitrate", "rx_block_error_rate", "ul_buffer"]):
                    continue
                curr_extracted_metrics.extend([ue_metric.get(metric, 0) for metric in METRICS_TO_EXTRACT])
    # print("Length of extracted metrics",len(curr_extracted_metrics))
    if curr_extracted_metrics and len(curr_extracted_metrics) == len(METRICS_TO_EXTRACT)*num_samples:
        print(curr_extracted_metrics)
        repeated_max_metrics = MAX_METRICS * num_samples
        normalized_metrics = [x / y for x, y in zip(curr_extracted_metrics, repeated_max_metrics)]
        print(normalized_metrics)
        pred = model_kpms.predict(np.array(normalized_metrics).reshape(1,len(METRICS_TO_EXTRACT)*num_samples))
        pred = np.argmax(pred, axis=1)[0]
        duration = time.perf_counter() - start_time
        # log_file2.write(f"Time to process KPMs: {duration:.6f}\n")
        return curr_extracted_metrics, pred
    
    return None, None


def optimize_mcs(old_bler,current_bler,old_mcs,current_mcs):

    optimal_mcs = 0
    return optimal_mcs


def entry():
    """Main entry point for RAN automation."""
    post_init()
    global current_mode, interf_res_final, command,prev_command
    model_spec = load_model_spec()
    prev_raw_bytes = None
    prev_extracted_metrics = []
    counter = 0
    while True:
        try:
            conn, addr = server.accept()
            log_info(f'Connected to IMI by {addr}')
            
            while True:
                start_time = time.perf_counter()
                
                # Process KPMs in both modes
                
                metrics, kpm_pred = process_kpms()
                # if metrics and metrics != prev_extracted_metrics:
                #     prev_extracted_metrics = metrics
                #     log_file1.write(f"Epoch: {time.time():.6f}, KPMs Prediction: {kpm_pred}\n")
                #     print(f"KPMs detection at {time.time():.6f} seconds")
                
                if current_mode == "KPMs":
                    command = b'k'
                    if command != prev_command:
                        prev_command = command
                        conn.send(command)
                    print("In KPMs mode")
                    # metrics, kpm_pred = process_kpms()
                    print(metrics)
                    if metrics and metrics != prev_extracted_metrics:
                        prev_extracted_metrics = metrics
                        # log_file1.write(f"Epoch: {time.time():.6f}, KPMs Prediction: {kpm_pred}\n")
                        print(f"KPMs detection in KPMs mode at {time.time():.6f} seconds")
                        if kpm_pred is not None:  # Only act if a valid prediction is made
                            check = all(metrics[i] <= BLER_THRESHOLD for i in range(1, len(metrics), len(METRICS_TO_EXTRACT)))
                            if check:
                            # if metrics[1] <= BLER_THRESHOLD and metrics[5] <= BLER_THRESHOLD:
                                kpm_pred = 0
                            else:
                                kpm_pred = 1
                            print("Final KPMs prediction: ", kpm_pred)
                            if kpm_pred == 0:
                                interf_res = [0, 0, 23]
                                conn.send(array.array('i', interf_res).tobytes())
                                # log_file1.write(f"KPMs mode: Unblanking PRBs \n")
                                print("In KPMs mode: Sent control to unblank PRBs")
                                # conn.send(b'k')
                                current_mode = "KPMs"

                            else:  # kpm_pred == 1, radar detected
                                interf_res = interf_res_final
                                conn.send(array.array('i', interf_res).tobytes())
                                print(f"Entering I/Q Mode: Sent control: {interf_res}")
                                command = b'i'
                                if command != prev_command:
                                    prev_command = command
                                    conn.send(command)
                                    current_mode = "I/Qs"
                                    # log_file1.write("Switching to I/Q mode\n")
                                    print("Radar signal detected! Switching to I/Q mode")
                                    continue
                    else:
                        # try:
                        # conn.send(b'k')
                        if command != prev_command:
                            command = b'k'
                            prev_command = command
                            conn.send(command)
                            print("Sent KPMs command")
                        current_mode = "KPMs"
                        print("No valid KPM prediction, remaining in KPMs mode")
                        interf_res = [0, 0, 23]
                        conn.send(array.array('i', interf_res).tobytes())
                        print("Sent control to unblank PRBs")
                        # log_file1.write("No valid KPM prediction, remaining in KPMs mode\n")
                    # prev_command = command 
                    # if command != prev_command:
                    #     command = b'k'
                    #     prev_command = command
                    #     conn.send(command)    
                
                elif current_mode == "I/Qs":
                    command = b'i'
                    if command != prev_command:
                        conn.send(command)
                    # conn.send(b'i')
                    print("In I/Q mode")
                    # metrics, kpm_pred = process_kpms()
                    if metrics and metrics != prev_extracted_metrics:
                        prev_extracted_metrics = metrics
                        # log_file1.write(f"Epoch: {time.time():.6f}, KPMs Prediction: {kpm_pred}\n")
                        print(f"KPMs detection in I/Q mode at {time.time():.6f} seconds")
                        print("Metrics seen in I/Q mode", metrics)
                        check = all(metrics[i] <= BLER_THRESHOLD for i in range(1, len(metrics), len(METRICS_TO_EXTRACT)))
                        if check:
                    # if metrics[1] <= BLER_THRESHOLD and metrics[5] <=BLER_THRESHOLD:
                            conn.send(array.array('i', [0, 0, 23]).tobytes())
                            print("Switch to KPMs mode and send control to unblank PRBs")
                            command = b'k'
                            if command != prev_command:
                                conn.send(command)
                            current_mode = "KPMs"
                        else:
                            interf_res = interf_res_final
                            print("Retaining previous blanked value", interf_res)
                            conn.send(array.array('i', interf_res).tobytes())
                            # conn.send(b'i')
                            current_mode = "I/Qs"
                    # if len(interf_res) ==  1:
                    #     print("Retaining previous blanked value with final blanked PRBs", interf_res[0])
                    #     conn.send(array.array('i', interf_res[0]).tobytes())
                    # else:
                    #     print("Retaining previous blanked value with final blanked PRBs", interf_res)
                    #     conn.send(array.array('i', interf_res).tobytes())
                    # time.sleep(0.2)
                    curr_raw_bytes = get_bytes()
                    
                    if curr_raw_bytes and curr_raw_bytes != prev_raw_bytes:
                        print("Gotten RAW bytes")
                        prev_raw_bytes = curr_raw_bytes
                        interf_res = run_prediction(model_spec, curr_raw_bytes)
                        print(interf_res)
                        # log_file1.write(f"Epoch: {time.time():.6f}, Spectrograms Prediction: {interf_res}\n")
                        if interf_res not in ["No detections made", "There is no interference detected"]:
                            print("Radar detected")
                            
                            # optimal_mcs = [4,0]
                            # optimal_mcs = optimize_mcs(metrics[3], metrics[2]) if metrics else [0]
                            if interf_res[0][0] > 0 and interf_res[0][1] > interf_res[0][0] and interf_res[0][0] < 50 and interf_res[0][1] < 50 :
                                interf_res = sorted(interf_res[0])
                                interf_res_final = interf_res.append(23)

                                print("Valid PRB range")
                            else:
                                print("Invalid PRB range so retain previous valid interference to blank")
                            print(interf_res_final)
                            conn.send(array.array('i', interf_res_final).tobytes())
                            # conn.send(array.array('i', optimal_mcs).tobytes())
                            print(f"Sent Affected PRBs: {interf_res_final}, MCS:Loading")
                            # conn.send(b'i')
                            current_mode = "I/Qs"
                        else: 
                            if interf_res in ["No detections made", "There is no interference detected"]: 
                                check = any(metrics[i] >= BLER_THRESHOLD for i in range(1, len(metrics), len(METRICS_TO_EXTRACT)))
                                if check:
                                # if metrics and (metrics[1] >= BLER_THRESHOLD or metrics[5] >= BLER_THRESHOLD):
                                    interf_res = interf_res_final
                                    print("Retaining previous blanked value", interf_res)
                                    conn.send(array.array('i', interf_res).tobytes())
                                    # conn.send(b'i') 
                                    current_mode = "I/Qs"
                                

                                else:
                                    conn.send(array.array('i', [0, 0, 23]).tobytes())
                                    print("Sent control to unblank PRBs")
                                    command = b'k'
                                    if command != prev_command:
                                        conn.send(command)
                                    # conn.send(b'k')
                                    current_mode = "KPMs"
                    # prev_command = command
                            
                            # log_file1.write("Switching to KPMs mode\n")
                # time.sleep(1)
                # Check BLER and adjust MCS in I/Q mode

                # Inside your loop
                # counter += 1
                # if counter % 10 == 0 and metrics and (metrics[1] >= BLER_THRESHOLD or metrics[5] >= BLER_THRESHOLD):
                #     optimal_mcs = [4]
                #     conn.send(array.array('i', optimal_mcs).tobytes())
                #     print("Now Sending optimal mcs")
                    # current_mode = "KPMs"
                # if metrics and (metrics[1] >= BLER_THRESHOLD or metrics[5] >= BLER_THRESHOLD):
                #     optimal_mcs = [4,0]
                #     conn.send(array.array('i', optimal_mcs).tobytes())
                #     print("Now Sending optimal mcs")
                #     current_mode = "KPMs"
                # if metrics and metrics[2] < BLER_THRESHOLD:
                #     optimal_mcs = optimize_mcs(metrics[3], metrics[2])
                #     conn.send(array.array('i', optimal_mcs).tobytes())
                #     log_file1.write(f"BLER {metrics[2]:.2f} below threshold {BLER_THRESHOLD}. Adjusted MCS to {optimal_mcs}\n")
                #     print(f"Adjusted MCS to {optimal_mcs} due to low BLER")
                # time.sleep(2)
                duration = time.perf_counter() - start_time
                # log_file2.write(f"Total cycle time: {duration:.6f}\n")
        
        except OSError as e:
            log_error(e)
            break
    
    log_file1.close()
    log_file2.close()

if __name__ == '__main__':
    entry()