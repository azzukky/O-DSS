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
BLER_THRESHOLD = 5.0  # BLER threshold in percentage
MCS_REDUCTION_STEP = 2  # Amount to reduce MCS by when BLER is below threshold
LOG_FILE1_PATH = 'radar_power_log_2db.txt'
LOG_FILE2_PATH = 'odss-timing-radarxapp2.txt'
MODEL_KPMS_PATH = "/home/ajchieji/spectrumsharing_4g/models/kpmmodel_len5.h5"
MODEL_SPEC_PATH = "/home/ajchieji/spectrumsharing_4g/models/best.pt"
MAX_METRICS = [45839996.0, 100, 24.34091, 148525]
METRICS_TO_EXTRACT = ["rx_bitrate", "rx_block_error_rate", "ul_mcs", "ul_buffer"]


# Global variables
server = None
sdl2 = SyncStorage()
log_file1 = open(LOG_FILE1_PATH, 'w')
log_file2 = open(LOG_FILE2_PATH, 'w')
model_kpms = load_model(MODEL_KPMS_PATH)

optimal_mcs_final = 24
interf_res_final = [0, 0, optimal_mcs_final]
current_mode = "KPMs"  # Initial mode
command = b'k'
prev_command = None
BLER_prev = 0
MAX_MCS = 24
MIN_MCS = 1

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

def process_kpms():
    """Retrieve and process KPMs from the database."""
    print("=====Processing KPMs======")
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
        # print(curr_extracted_metrics)
        repeated_max_metrics = MAX_METRICS * num_samples
        normalized_metrics = [x / y for x, y in zip(curr_extracted_metrics, repeated_max_metrics)]
        # print(normalized_metrics)
        pred = model_kpms.predict(np.array(normalized_metrics).reshape(1,len(METRICS_TO_EXTRACT)*num_samples))
        pred = np.argmax(pred, axis=1)[0]
        duration = time.perf_counter() - start_time
        # log_file2.write(f"Time to process KPMs: {duration:.6f}\n")
        return curr_extracted_metrics, pred
    
    return None, None


def optimize_mcs(MCS_BS, BLER, BLER_prev, BLER_thresh, MCS_max, MCS_min, gamma=1, beta=2):
    """
    Parameters:
    - MCS_BS: int, current MCS index at BS
    - BLER: float, current BLER observed
    - BLER_prev: float, previous BLER
    - gamma: float, BLER variation threshold
    - BLER_thresh: float, maximum acceptable BLER
    - MCS_max: int, maximum MCS value allowed
    - MCS_min: int, minimum MCS value allowed
    - beta: int, step size for MCS adjustment (default: 1)
    """
    if BLER == 100:
        return MCS_min
    
    if BLER_prev != BLER:
        if abs(BLER - BLER_prev) < gamma:
            return MCS_BS  # No significant change

    if BLER > BLER_thresh:
        action = 'DECR'
        MCS_BS = max(MCS_BS//beta, MCS_min)
    else:
        action = 'INCR'
        MCS_BS = min(MCS_BS + beta, MCS_max)

    return round(MCS_BS)

def mcs_optim(metrics,BLER_prev):
    mcs_val = metrics[2::len(METRICS_TO_EXTRACT)]   
    bler_val = metrics[1::len(METRICS_TO_EXTRACT)]
    curr_mcs = sum(mcs_val) // len(mcs_val)
    curr_bler = sum(bler_val) // len(bler_val)
    # curr_mcs = metrics[18]
    # curr_bler = metrics[17]
    optimal_mcs = optimize_mcs(curr_mcs,curr_bler,BLER_prev,BLER_THRESHOLD,MAX_MCS,MIN_MCS)
    optimal_mcs = math.floor(optimal_mcs)
    print("current mcs, current bler and previous bler", curr_mcs,curr_bler,BLER_prev)
    print("---------===",optimal_mcs,"===----------")
    return optimal_mcs,curr_bler
    

def entry():
    """Main entry point for RAN automation."""
    post_init()
    global current_mode,interf_res_final,command,prev_command,BLER_prev,MAX_MCS,MIN_MCS,optimal_mcs_final
    model_spec = load_model_spec()
    prev_raw_bytes = None
    prev_extracted_metrics = []
    counter = 0

    
    while True:
        try:
            conn, addr = server.accept()
            log_info(f'Connected to IMI by {addr}')
            conn.send(array.array('i', interf_res_final).tobytes())
            print("This is the entry: send default configuration", interf_res_final)
            while True:
                # Process KPMs in both modes
                start_time_total = time.perf_counter()
                start_time = time.perf_counter()
                metrics, kpm_pred = process_kpms()

                print("KPM Prediction is", kpm_pred)
                if metrics and metrics != prev_extracted_metrics:
                    prev_extracted_metrics = metrics
                    if kpm_pred is not None:                    
                        if kpm_pred == 0:
                            current_mode = "KPMs"
                        else:
                            current_mode = "I/Qs"

                        if current_mode == "KPMs":
                            print("==========Entering KPMs mode===========")
                            command = b'k'
                            if command != prev_command:
                                prev_command = command
                                conn.send(command)
                            print("Metrics seen in KPMs mode: ", metrics)
                    
                            if kpm_pred == 0:
                                print("====NO RADAR DETECTED USING KPMS=====")
                                # optimal_mcs_final = 23
                                optimal_mcs,curr_bler = mcs_optim(metrics,BLER_prev)
                                BLER_prev = curr_bler
                                optimal_mcs_final = optimal_mcs
                                interf_res_final = [0, 0, optimal_mcs_final]
                                conn.send(array.array('i', interf_res_final).tobytes())
                                print("Current BLER: ", BLER_prev, "Optimal MCS: ", optimal_mcs_final)
                                print("In KPMs mode: Sent control to unblank PRBs and use OPTIMAL MCS")
                                current_mode = "KPMs"
                            else: 
                                print("====RADAR DETECTED USING KPMS=====")
                                print("Metrics seen when we have radar", metrics)
                                optimal_mcs,curr_bler = mcs_optim(metrics,BLER_prev)
                                BLER_prev = curr_bler
                                optimal_mcs_final = optimal_mcs
                                interf_res_final[2]= optimal_mcs_final
                                print("Current BLER: ", BLER_prev, "Optimal MCS: ", optimal_mcs_final)
                                print(f"Sent last updated control: {interf_res_final}")
                                conn.send(array.array('i', interf_res_final).tobytes())
                                command = b'i'
                                if command != prev_command:
                                    prev_command = command
                                    conn.send(command)
                                    current_mode = "I/Qs"
                                    print("===Radar signal detected! Switching to I/Q mode===")

                            end_time = time.perf_counter()
                            duration = end_time - start_time
                            log_entry1 = f" Processing KPMs and Model Inference (MODE 1) {duration} \n"
                            print("===========",log_entry1,"=========")
                            log_file2.write(log_entry1)  # Write to file   

                        elif current_mode == "I/Qs":
                            command = b'i'
                            if command != prev_command:
                                conn.send(command)
                            print("===========Entering I/Q mode===========")
                            print("====RADAR DETECTED USING KPMS=====")
                            print("Metrics seen when we have radar", metrics)
                            
                            start_time = time.perf_counter()

                            curr_raw_bytes = get_bytes()
                            print("Gotten RAW bytes")
                            interf_res = run_prediction(model_spec, curr_raw_bytes)
                            print(interf_res)
                            if interf_res not in ["No detections made", "There is no interference detected"]:
                                print("=======Radar detected=========")
                                if interf_res[0][0] > 0 and interf_res[0][1] > interf_res[0][0] and interf_res[0][0] < 50 and interf_res[0][1] < 50 :
                                    interf_res = sorted(interf_res[0])
                                    # interf_res_final = interf_res.append(23)
                                    print("=======Valid PRB range========:",interf_res)
                                    optimal_mcs,curr_bler = mcs_optim(metrics,BLER_prev)
                                    BLER_prev = curr_bler
                                    optimal_mcs_final = optimal_mcs
                                    interf_res.append(optimal_mcs_final)
                                    interf_res_final = interf_res
                                    print("Current BLER: ", BLER_prev, "Optimal MCS: ", optimal_mcs_final)
                                    print(interf_res_final)
                                    conn.send(array.array('i', interf_res_final).tobytes())
                                    print(f"======>Sent updated control: {interf_res_final}")
                                    current_mode = "I/Qs"
                                else:
                                    print("=========Invalid PRB range so retain previous valid interference to blank========")
                                    optimal_mcs,curr_bler = mcs_optim(metrics,BLER_prev)
                                    BLER_prev = curr_bler
                                    optimal_mcs_final = optimal_mcs
                                    interf_res_final[2]= optimal_mcs_final
                                    print("Current BLER: ", BLER_prev, "Optimal MCS: ", optimal_mcs_final)
                                    print(f"Sent last updated control: {interf_res_final}")
                                    conn.send(array.array('i', interf_res_final).tobytes())
                                    command = b'i'
                                    if command != prev_command:
                                        prev_command = command
                                        conn.send(command)
                                        current_mode = "I/Qs"
                                        print("===Staying in I/Q MODE===")
                                # interf_res_final[0:2] = interf_res[0]
                                

                            elif interf_res in ["No detections made", "There is no interference detected"]:
                                print("====There is probability of being interfered======") 
                                optimal_mcs,curr_bler = mcs_optim(metrics,BLER_prev)
                                BLER_prev = curr_bler
                                optimal_mcs_final = optimal_mcs
                                interf_res_final[2]= optimal_mcs_final
                                print("Current BLER: ", BLER_prev, "Optimal MCS: ", optimal_mcs_final)
                                print(f"Sent last updated control: {interf_res_final}")
                                conn.send(array.array('i', interf_res_final).tobytes())
                                command = b'k'
                                if command != prev_command:
                                    prev_command = command
                                    conn.send(command)
                                    current_mode = "KPMs"
                                    print("===Switching back to KPMs MODE===")

                            optimal_mcs,curr_bler = mcs_optim(metrics,BLER_prev)
                            BLER_prev = curr_bler
                            optimal_mcs_final = optimal_mcs
                            interf_res_final[2]= optimal_mcs_final
                            print("Current BLER: ", BLER_prev, "Optimal MCS: ", optimal_mcs_final)
                            print(f"Sent last updated control: {interf_res_final}")
                            conn.send(array.array('i', interf_res_final).tobytes())
                            command = b'i'
                            if command != prev_command:
                                prev_command = command
                                conn.send(command)
                                current_mode = "I/Qs"
                                print("=== Remain in I/Q mode===")


                            end_time = time.perf_counter()
                            duration = end_time - start_time
                            log_entry2 = f" Processing Spectrograms and Model Inference (MODE 2) {duration} \n"
                            print("==============",log_entry2,"===============")
                            log_file2.write(log_entry2)  # Write to file
                                                                    
                    else:
                        if command != prev_command:
                            command = b'k'
                            prev_command = command
                            conn.send(command)
                            print("Sent KPMs command")
                            current_mode = "KPMs"
                        print("====No valid KPM prediction, remaining in KPMs mode====")
                        # optimal_mcs_final = 23
                        # interf_res = [0, 0, optimal_mcs_final]
                        conn.send(array.array('i', interf_res_final).tobytes())   
                        print("In KPMs mode: Sent previous control:",interf_res_final)

                end_time_total = time.perf_counter()
                duration = end_time_total - start_time_total
                log_entry3 = f" Total time for entire xApp {duration} \n"
                # log_file2.write(log_entry1)  # Write to file   
                # log_file2.write(log_entry2)  # Write to file   
                log_file2.write(log_entry3)  # Write to file
                print("===========================",log_entry3, "========================")
                time.sleep(0.25)
        except OSError as e:
            log_error(e)
            break
    
    log_file1.close()
    log_file2.close()

if __name__ == '__main__':
    entry()