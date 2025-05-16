import sctp, socket
from ultralytics import YOLO
import torch, torchvision
import time
import random
import array
import math
import io
from datetime import datetime
from log import *
import threading
from PIL import Image
import numpy as np
import matplotlib.pyplot as plt
from ricsdl.syncstorage import SyncStorage
import json
import xgboost as xgb

# SAMPLING_RATE = 7.68e6
chann_bandwidth = 10e6
num_prbs = 50
spec_width_px = 640
spec_height_px = 640
# spectrogram_time = 0.010  # 10 ms
# num_of_samples = SAMPLING_RATE * spectrogram_time
# SPEC_SIZE = num_of_samples * 8  # size in bytes, where 8 bytes is the size of one sample (complex64)

PROTOCOL = 'SCTP'
ENABLE_DEBUG = False
server = None
interf_res_final = [0,0]
# create the sdl client
ns1 = "Spectrograms"
ns2 = "Kpms"
sdl2= SyncStorage()
log_file1 = open('radar_power_log_12db.txt', 'w')  # Open log file in write mode
should_send = True

def post_init(self):
    global server

    ip_addr = socket.gethostbyname(socket.gethostname())
    # ip_addr = "127.0.1.1"
    port_radarxApp = 5002

    log_info(f"connecting using SCTP on {ip_addr}")
    server = sctp.sctpsocket_tcp(socket.AF_INET)
    server.bind((ip_addr, port_radarxApp)) 
    server.listen()

    log_info('Server started')

interf_res = None


def entry(self):
    global server, model_spec, interf_res_final

    post_init(self)
    model_spec = load_model_spec()
    # State variable to track the current mode
    current_mode = "KPMs"  # Can be "KPMs" or "I/Q"
    while True:
        try:
            conn, addr = server.accept() 
            log_info(f'Connected to IMI by {addr}')
            prev_raw_bytes = None
            prev_extracted_metrics = []
            print("Starting inferences")
            while True:
                #  For KPMs inference
                if current_mode == "KPMs":
                    key_pattern = "kpm_*"
                    n = 2
                    keys = sdl2.find_keys(ns2, key_pattern)
                    
                    sorted_keys = sorted(keys, key=lambda x: int(x.split('_')[1]))
                    # print(len(sorted_keys))
                    lastn_keys = sorted_keys[-n:]
                    values = sdl2.get(ns2, set(lastn_keys)) 
                    metrics_to_extract = ["pusch_sinr", "rx_bitrate", "rx_block_error_rate", "ul_mcs", "ul_buffer"]
                    curr_extracted_metrics = []
                    
                    for key, value_bytes in values.items():
                        if value_bytes:
                            value = json.loads(value_bytes.decode('utf-8'))
                            ue_metrics = value.get("ue_metrics", [])
                            # print(ue_metrics)
                            for ue_metric in ue_metrics:
                                if (ue_metric.get("rx_bitrate") == 0 
                                    and ue_metric.get("rx_block_error_rate") == 0 
                                    and ue_metric.get("ul_buffer") == 0):
                                    continue  # Skip appending if all three are zero
                                curr_extracted_metrics.extend([ue_metric.get(metric) for metric in metrics_to_extract])

                    if len(curr_extracted_metrics) == len(metrics_to_extract)*n:          
                        if curr_extracted_metrics!=prev_extracted_metrics:
                            print("Gotten KPMs from RAN")
                            # print(f"KPMs gotten from the RAN: {curr_extracted_metrics}")
                            metrics = curr_extracted_metrics
                            log_entry1 = f"{metrics}\n"
                            log_file1.write(log_entry1)  # Write to file
                            prev_extracted_metrics = curr_extracted_metrics
                            # print(len((curr_extracted_metrics)))
                            curr_extracted_metrics = np.array(curr_extracted_metrics).reshape(1,len(metrics_to_extract)*n)
                            model_kpms = xgb.XGBClassifier() 
                            model_kpms.load_model("/home/azuka/spectrumsharing_4g/models/prelim_xgboost_model.model")  
                            start_time = time.perf_counter()
                            pred = model_kpms.predict(curr_extracted_metrics)
                            if metrics[2] >= 5 or metrics[7] >=5:
                                pred[0] = 1
                            else:
                                pred[0] = 0
                            epoch_time1 = time.time()
                            end_time = time.perf_counter()
                            duration = end_time - start_time
                            print(f"KPMs detection Time {duration:.6f} seconds")
                            log_entry1 = f"Epoch: {epoch_time1}, KPMs Prediction: {pred[0]}\n"
                            print(f"KPMs detection at {epoch_time1:.6f} seconds")
                            log_file1.write(log_entry1)  # Write to file
                            log_file1.flush()  # Ensure immediate write to disk
                            if pred[0] == 0:
                                # No radar detected, stay in KPMs mode
                                # First ensure that the BS is not blanking
                                if metrics[2] >= 5 or metrics[7] >=5:
                                    interf_restoarr = array.array('i',interf_res_final)
                                    interf_restobytes = interf_restoarr.tobytes()
                                    # print(f"Confirmed Affected PRBs are {interf_res}")
                                    conn.send(interf_restobytes)
                                    print("Retain previous blanked PRBs")
                                    log_entry1 = f"In KPMs mode. Retain previous blanked PRBs\n"
                                    log_file1.write(log_entry1)  # Write to file
                                else:
                                    interf_res = [0,0]
                                    interf_restoarr = array.array('i',interf_res)
                                    interf_restobytes = interf_restoarr.tobytes()
                                    # print(f"Confirmed Affected PRBs are {interf_res}")
                                    conn.send(interf_restobytes)
                                    print(f"Sent control to unblank PRBs")
                                    log_entry1 = f"In KPMs mode. Unblanking PRBS\n"
                                    log_file1.write(log_entry1)  # Write to file

                                if current_mode != "KPMs":
                                    command = b'k'
                                    print(f"No Radar signal detected! Sending command {command} to imi") 
                                    conn.send(command)
                                    current_mode = "KPMs"
                                else:
                                    print("Remaining in KPMs state (NO Radar Signal detected)")
                            else:
                                command = b'i'
                                print(f"Radar signal detected! Sending command {command} to imi")
                                conn.send(command)
                                end_time = time.perf_counter()
                                current_mode = "I/Qs"
                                continue
                                
                                

                elif current_mode == "I/Qs":
                    # print("Now in I/Q mode")
                    # Now the object detection algorithm
                    start_time = time.perf_counter()
                    curr_raw_bytes = get_bytes()
                    end_time = time.perf_counter()
                    duration = end_time - start_time
                    # print(f"Sending took {duration:.6f} seconds")
                    # print(curr_raw_bytes)
                    if curr_raw_bytes!= prev_raw_bytes:
                        # Prediction is run here
                        prev_raw_bytes = curr_raw_bytes
                        print("Entering prediction function")
                        # Measure time
                        start_time = time.perf_counter()
                        interf_res = run_prediction(curr_raw_bytes)
                        end_time = time.perf_counter()
                        epoch_time1 = time.time()
                        duration = end_time - start_time
                        log_entry1 = f"Epoch: {epoch_time1}, Spectrogram Prediction: {interf_res}\n"
                        print(f"KPMs detection at {epoch_time1:.6f} seconds")
                        log_file1.write(log_entry1)  # Write to file
                        log_file1.flush()  # Ensure immediate write to disk
                        # Calculate duration
                        # duration = end_time - start_time
                        # print(f"Function took {duration:.6f} seconds")
                        print(interf_res)
                        if interf_res != "No detections made" and interf_res != "There is no interference detected":
                            # print("Detections made")
                            interf_res = sorted(interf_res[0])
                            interf_res_final = interf_res
                            # print(f"Affected PRBs are {interf_res}")
                            if interf_res_final[0] > 0 and interf_res_final[1] > interf_res_final[0] and interf_res_final[0] < 50 and interf_res_final[1] < 50 :
                                interf_restoarr = array.array('i',interf_res_final)
                                interf_restobytes = interf_restoarr.tobytes()
                                print(f"Confirmed Affected PRBs are {interf_res_final}")
                                conn.send(interf_restobytes)
                                print(f"Sent Affected PRBs to IMI")
                                # time.sleep(0.2)
                                current_mode = "KPMs"
                        else:
                            # No interference detected, desired state is KPMs
                            print("No interference")
                            if current_mode != "KPMs":

                                if metrics[2] >= 5 or metrics[7] >=5:
                                    interf_restoarr = array.array('i',interf_res_final)
                                    interf_restobytes = interf_restoarr.tobytes()
                                    # print(f"Confirmed Affected PRBs are {interf_res}")
                                    conn.send(interf_restobytes)
                                    print("Retain previous blanked PRBs")
                                    log_entry1 = f"In I/Qs mode. Retain previous blanked PRBs\n"
                                    log_file1.write(log_entry1)  # Write to file
                                # First ensure that the xApp sends command to BS to unblank
                                else:
                                    interf_res = [0,0]
                                    interf_restoarr = array.array('i',interf_res)
                                    interf_restobytes = interf_restoarr.tobytes()
                                    # print(f"Confirmed Affected PRBs are {interf_res}")
                                    conn.send(interf_restobytes)
                                    print(f"Sent control to unblank PRBs")
                                    log_entry1 = f"In I/Qs mode. Unblanking PRBs\n"
                                    log_file1.write(log_entry1)  # Write to file

                            
                                # Only send command if there's a state change
                                command = b'k'
                                print(f"No Radar signal detected! Sending command {command} to imi")
                                conn.send(command)
                                current_mode = "KPMs"  # Update current mode

                            # low = random.randint(5,10)
                            # dummy_data = [low, random.randint(low+1, 20)]
                            # print(dummy_data)
                            # interf_restoarr = array.array('i',dummy_data)
                            # interf_restobytes = interf_restoarr.tobytes()
                            # print("Sent bytes", interf_restobytes)
                            # conn.send(interf_restobytes)
                        # end = time.perf_counter()-start
                        # print(f"Total time taken is {end}")

            log_file1.close()  # Close the log file
        except OSError as e:
            log_error(e)
            break


# This function gets the bytes from the database
def get_bytes():
    data_dict = sdl2.get(ns1, {'new_spec'})
    raw_bytes = None
    for key, val in data_dict.items():
        raw_bytes = val
    return raw_bytes

# This converts the raw bytes back to an image and then processes it to the desired shape required
# by the ML model!!!!
def raw_bytes_to_image(raw_bytes):
    # Read as a PIL image and return
    ret = io.BytesIO(raw_bytes)
    image = Image.open(ret)
    arr = np.array(image)
    # print("Shape of image is",arr.shape)
    # print("Plotting image")
    # plt.imshow(arr)
    # plt.show()
    # plt.close()
    
    return image

# This runs the prediction
def run_prediction(raw_bytes):
    sample = raw_bytes_to_image(raw_bytes)
    ymin_soi, ymax_soi, ymin_cwis, ymax_cwis = predict_newdata(sample)
    prbs_affected = get_affected_prbs(ymin_soi, ymax_soi, ymin_cwis, ymax_cwis) 
    # print("checking predictions",len(result))
    return prbs_affected


# Load model_spec
def load_model_spec():
    model_spec_path = '/home/azuka/spectrumsharing_4g/models/best.pt'
    best_model_spec = YOLO(model_spec_path)
        
    return best_model_spec

def predict_newdata(sample):
    pred = model_spec(sample)
    # print("Printing predictions",pred)
    result = pred[0]
    inference = result.plot()
    # print("Plotting image")
    # plt.imshow(inference)
    # plt.show()
    # plt.close()


    for box in result.boxes:
        class_id = result.names[box.cls[0].item()]
        cords_xyxy = box.xyxy[0].tolist()
        cords_xyxyn = box.xyxyn[0].tolist()
        cords_xywh = box.xywh[0].tolist()
        cords_xywhn = box.xywhn[0].tolist()
        conf = round(box.conf[0].item(), 2)
        # print("Object type:", class_id)


        # print("Coordinates in xyxy:", cords_xyxy)
        # print("Coordinates in xyxyn:", cords_xyxyn)
        # print("Coordinates in xywh:", cords_xywh)
        # print("Coordinates in xywhn:", cords_xywhn)



        # print("Probability:", conf)
        # print("---")

    
    soi = []
    p0n2 = []
    ymin_soi = "nil" 
    ymin_p0n2 = "nil"
    ymax_soi = "nil"
    ymax_p0n2 = "nil"
    # ymin_p0n2 = []
    # ymax_p0n2 = []
    for box in result.boxes:
        if box.cls == 0:
            class_idsoi = result.names[box.cls[0].item()]
            coordinatessoi = box.xyxy[0].tolist()
            confidencesoi = round(box.conf[0].item(),2)
            soi_predictions = {
                "class": class_idsoi,
                "cords":coordinatessoi,
                "confidence": confidencesoi,
            }
            soi.append(soi_predictions)
        elif box.cls == 1:
            class_idp0n2 = result.names[box.cls[0].item()]
            coordinatesp0n2 = box.xyxy[0].tolist()
            confidencep0n2 = round(box.conf[0].item(),2)
            p0n2_predictions = {
                "class": class_idp0n2,
                "cords":coordinatesp0n2,
                "confidence": confidencep0n2,
            }
            p0n2.append(p0n2_predictions)

    if len(soi) != 0:     
        soi = sorted(soi, key=lambda x: x['confidence'], reverse=True)
        for i in range(len(soi)):
            if soi[i]["confidence"] > 0.60:
                ymin_soi = soi[i]["cords"][1]
                ymax_soi = soi[i]["cords"][3]
    if len(p0n2) != 0:
        p0n2 = sorted(p0n2, key=lambda y: y['confidence'], reverse=True)
        for i in range(len(p0n2)):
            if p0n2[i]["confidence"] > 0.20:
                ymin_p0n2 = p0n2[i]["cords"][1]
                ymax_p0n2 = p0n2[i]["cords"][3]
    print(soi)
    return ymin_soi, ymax_soi, ymin_p0n2, ymax_p0n2


def get_affected_prbs(ymin_soi, ymax_soi, ymin_p0n2, ymax_p0n2):
    if ymin_p0n2 == "nil" and ymin_soi == "nil":
        return "No detections made"
    elif ymin_p0n2 == "nil" and ymin_soi != "nil":
        return "There is no interference detected"
    ymin_soi = 93.23387145996094
    ymax_soi = 552.609619140625
    # print(f"{ymin_soi}, {ymax_soi}")
    guardband_bandwidth = 0.1*chann_bandwidth
    occupied_bandwidth = chann_bandwidth - guardband_bandwidth
    # spectral_occupancy_prb = occupied_bandwidth/num_prbs
    soi_fullheight_px = float(ymax_soi)-float(ymin_soi) #Height of chann bandwidth in px
    soi_effectiveheight_px = (occupied_bandwidth*soi_fullheight_px)/chann_bandwidth
    effective_px_prb = soi_effectiveheight_px/num_prbs # A prb thus covers this amount of px
    guardbands_px = soi_fullheight_px - soi_effectiveheight_px
    guardband_low_px = guardbands_px/2
    # guardband_high_px = guardband_low_px
    soi_start = ymin_soi + guardband_low_px
    soi_end = soi_start+soi_effectiveheight_px
    interfered_prbsrange = []
    interfered_prbsexact = []
    affected_prbs = []
    prb_affected1 = math.floor((soi_end-ymax_p0n2)/(effective_px_prb))
    prb_affected2 = math.ceil((soi_end-ymin_p0n2)/(effective_px_prb)) 
    if prb_affected1 < 0 or prb_affected2 < 0:
        prb_affected1 =  prb_affected1+1
        prb_affected2 = prb_affected2+2
        
    affected_prbs.append(prb_affected1)
    affected_prbs.append(prb_affected2)
    
    interfered_prbsrange.append(affected_prbs)
        
    return interfered_prbsrange



def start(thread=False):
    entry(None)


if __name__ == '__main__':
    start()